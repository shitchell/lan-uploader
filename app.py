#!/usr/bin/env python3
import os
import argparse
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path
from configparser import ConfigParser
from typing import Optional, List, Dict, Any, Tuple, Union
from argparse import Namespace

import aiofiles
from fastapi import FastAPI, UploadFile, File, Form, Query, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from werkzeug.utils import secure_filename

from models import DatabaseManager, FileIndex
from thumbnails import ThumbnailGenerator

# ---- Configuration Loading ----
# Priority: 1) Command line args, 2) Environment variables, 3) Config file, 4) Hardcoded defaults

def parse_args() -> Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="LAN Uploader - A mobile-first file browser for your local network"
    )
    parser.add_argument(
        "--upload-root",
        type=str,
        help="Upload root directory (default: ./uploads)",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        help="Maximum upload size in MB (default: 1024)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Server port (default: 8080)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Host to bind to (default: 0.0.0.0, use 127.0.0.1 for localhost only)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Database file path (default: ./lanuploader.db)",
    )
    return parser.parse_args()

def load_config(args: Optional[Namespace] = None) -> Dict[str, str]:
    """Load configuration with priority: CLI args > env vars > config file > defaults."""
    # Defaults
    config: Dict[str, str] = {
        "UPLOAD_ROOT": "./uploads",
        "MAX_CONTENT_LENGTH_MB": "1024",
        "PORT": "8080",
        "HOST": "0.0.0.0",
        "DB_PATH": "./lanuploader.db",
    }

    # Read from config file if it exists
    config_path = Path.home() / ".lanuploaderc"
    if config_path.exists():
        parser = ConfigParser()
        parser.read(config_path)
        if "lanuploader" in parser:
            for key in config.keys():
                if key in parser["lanuploader"]:
                    config[key] = parser["lanuploader"][key]

    # Override with environment variables
    for key in config.keys():
        if key in os.environ:
            config[key] = os.environ[key]

    # Override with command line arguments (highest priority)
    if args:
        if args.upload_root is not None:
            config["UPLOAD_ROOT"] = args.upload_root
        if args.max_size is not None:
            config["MAX_CONTENT_LENGTH_MB"] = str(args.max_size)
        if args.port is not None:
            config["PORT"] = str(args.port)
        if args.host is not None:
            config["HOST"] = args.host
        if args.db_path is not None:
            config["DB_PATH"] = args.db_path

    return config

args = parse_args()
config = load_config(args)
UPLOAD_ROOT = Path(config["UPLOAD_ROOT"]).resolve()
MAX_CONTENT_LENGTH = int(config["MAX_CONTENT_LENGTH_MB"]) * 1024 * 1024  # MB -> bytes
PORT = int(config["PORT"])
HOST = config["HOST"]
DB_PATH = Path(config["DB_PATH"]).resolve()

# Initialize FastAPI app
app = FastAPI(
    title="LAN Uploader",
    description="Mobile-first file browser and uploader for local networks",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Ensure root exists
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# Initialize database
db_url = f"sqlite:///{DB_PATH}"
db = DatabaseManager(db_url)
db.init_db()

# Initialize thumbnail generator
THUMBNAIL_CACHE_DIR = UPLOAD_ROOT / ".thumbnails"
thumbnail_gen = ThumbnailGenerator(THUMBNAIL_CACHE_DIR)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# ---- Preview Type Detection ----

PREVIEW_HANDLERS = {
    'image': {
        'extensions': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico'},
        'method': 'inline',
    },
    'video': {
        'extensions': {'.mp4', '.webm', '.ogg', '.mov', '.avi', '.mkv'},
        'method': 'inline',
    },
    'audio': {
        'extensions': {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'},
        'method': 'inline',
    },
    'text': {
        'extensions': {'.txt', '.md', '.log', '.csv', '.json', '.xml', '.yaml', '.yml', '.ini', '.conf'},
        'method': 'text',
    },
    'code': {
        'extensions': {'.py', '.js', '.html', '.css', '.sh', '.bash', '.c', '.cpp', '.h', '.java', '.go', '.rs', '.php', '.rb'},
        'method': 'text',
    },
}

def get_preview_type(extension: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Determine preview type and method for a file extension.

    Args:
        extension: File extension including the dot (e.g., '.jpg')

    Returns:
        Tuple of (preview_type, preview_method), or (None, None) if no preview available
    """
    extension = extension.lower()
    for preview_type, info in PREVIEW_HANDLERS.items():
        if extension in info['extensions']:
            return preview_type, str(info['method'])
    return None, None

# ---- Security Functions ----
# All path operations use these functions to prevent directory traversal attacks

def within_root(p: Path) -> bool:
    """
    Check if a path is inside UPLOAD_ROOT.

    This prevents path traversal attacks (e.g., ../../etc/passwd).
    Returns True only if the resolved path is a child of UPLOAD_ROOT.
    """
    try:
        p.resolve().relative_to(UPLOAD_ROOT)
        return True
    except (ValueError, RuntimeError):
        # ValueError: path is not relative to UPLOAD_ROOT
        # RuntimeError: symlink loop or other path resolution error
        return False

def safe_target_dir(subpath: str) -> Path:
    """
    Sanitize and validate a user-provided subpath within UPLOAD_ROOT.

    Normalizes the path, resolves it, verifies it's within UPLOAD_ROOT,
    and creates it if it doesn't exist. Returns the validated Path object.

    Raises HTTPException 400 if path attempts to escape UPLOAD_ROOT.
    """
    subpath = (subpath or "").strip().strip("/")
    target = (UPLOAD_ROOT / subpath).resolve()
    if not within_root(target):
        raise HTTPException(status_code=400, detail="Invalid target directory.")
    target.mkdir(parents=True, exist_ok=True)
    return target

# ---- Streaming Upload Functions ----

def check_disk_space(path: Path) -> Tuple[int, int, int]:
    """
    Check disk space for the given path.

    Args:
        path: Path to check disk space for

    Returns:
        Tuple of (total_bytes, used_bytes, available_bytes)
    """
    stat = os.statvfs(str(path))
    total = stat.f_blocks * stat.f_frsize
    available = stat.f_bavail * stat.f_frsize
    used = total - available
    return (total, used, available)


async def stream_upload_to_file(
    upload_file: UploadFile,
    destination: Path,
    chunk_size: int = 1024 * 1024  # 1MB chunks
) -> int:
    """
    Stream an uploaded file directly to destination without using temp files.

    Reads the upload in chunks and writes them directly to the destination file,
    avoiding the need for temporary file storage.

    Args:
        upload_file: The FastAPI UploadFile object to stream
        destination: Path where the file should be written
        chunk_size: Size of chunks to read/write (default: 1MB)

    Returns:
        Total bytes written

    Raises:
        OSError: If disk is full, permission denied, or other I/O error occurs
    """
    bytes_written = 0

    try:
        async with aiofiles.open(destination, 'wb') as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                await f.write(chunk)
                bytes_written += len(chunk)
    except Exception as e:
        # Clean up partial file on any error
        if destination.exists():
            destination.unlink()
        raise

    return bytes_written

# ---- Routes ----

@app.get("/", include_in_schema=False)
async def index(request: Request) -> Any:
    """
    Serve the main file browser page.

    Reads the 'last_dir' cookie to remember the user's last upload location.
    """
    last_dir = request.cookies.get("last_dir", "")
    # Sanitize cookie value for display (validation happens on upload)
    last_dir = last_dir.strip().strip("/")
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "last_dir": last_dir
    })

@app.post("/upload", tags=["Files"])
async def upload_files(
    files: List[UploadFile] = File(...),
    target_dir: str = Form("")
) -> JSONResponse:
    """
    Upload one or more files to a directory with streaming.

    Files are written directly to the upload directory as they arrive,
    avoiding the use of temporary file storage.

    - **files**: List of files to upload
    - **target_dir**: Target directory path (relative to upload root)

    Returns a list of uploaded files with metadata.
    Sets a cookie to remember the upload directory.
    """
    target_dir = target_dir.strip().strip("/")
    target = safe_target_dir(target_dir)

    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    # Check disk space before starting upload
    try:
        _, _, available_bytes = check_disk_space(UPLOAD_ROOT)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check disk space: {str(e)}"
        )

    saved = []
    errors = []

    for file in files:
        if not file.filename:
            continue

        filename = secure_filename(file.filename)
        if not filename or filename in (".", ".."):
            errors.append({
                "file": file.filename,
                "error": "Invalid filename"
            })
            continue

        dest = target / filename

        # Check if file already exists
        if dest.exists():
            errors.append({
                "file": filename,
                "error": "File already exists"
            })
            continue

        try:
            # Stream file directly to destination
            bytes_written = await stream_upload_to_file(file, dest)

            # Index the file in the database
            file_stat = dest.stat()
            extension = dest.suffix.lower()
            mime_type, _ = mimetypes.guess_type(str(dest))
            preview_type, preview_method = get_preview_type(extension)
            has_thumbnail = preview_type == 'image'

            filepath_rel = dest.relative_to(UPLOAD_ROOT).as_posix()
            parent_path_rel = target.relative_to(UPLOAD_ROOT).as_posix()

            db.index_file(
                filepath=filepath_rel,
                filename=filename,
                parent_path=parent_path_rel,
                size=file_stat.st_size,
                modified_at=datetime.fromtimestamp(file_stat.st_mtime),
                extension=extension,
                mime_type=mime_type,
                has_thumbnail=has_thumbnail,
                preview_type=preview_type,
            )

            # Generate thumbnail if image
            if preview_type == 'image':
                try:
                    thumbnail_gen.generate(dest)
                except Exception as e:
                    # Thumbnail generation failure is not critical
                    pass

            saved.append({
                "filename": filename,
                "relative_path": f"/{target_dir}" if target_dir else "/",
                "bytes": bytes_written,
            })

        except OSError as e:
            # Handle disk full, permission denied, etc.
            if dest.exists():
                dest.unlink()  # Clean up partial file

            error_msg = str(e)
            if e.errno == 28:  # ENOSPC - No space left on device
                error_msg = "Disk full"
                errors.append({
                    "file": filename,
                    "error": error_msg
                })
                # Stop processing remaining files if disk is full
                raise HTTPException(
                    status_code=507,
                    detail=f"Disk full after {len(saved)} files. {len(files) - len(saved) - len(errors)} files not uploaded."
                )
            elif e.errno == 13:  # EACCES - Permission denied
                error_msg = "Permission denied"

            errors.append({
                "file": filename,
                "error": error_msg
            })

        except Exception as e:
            # Handle any other errors
            if dest.exists():
                dest.unlink()  # Clean up partial file
            errors.append({
                "file": filename,
                "error": str(e)
            })

    response = JSONResponse({
        "ok": True,
        "saved": saved,
        "errors": errors,
        "target_dir": target_dir,
        "message": f"Uploaded {len(saved)}/{len(files)} files"
    })
    # Remember last dir for 30 days
    response.set_cookie(
        key="last_dir",
        value=target_dir,
        max_age=60*60*24*30,
        samesite="lax"
    )
    return response

@app.get("/api/browse", tags=["Browse"])
async def browse(
    path: str = Query("", description="Directory path relative to upload root")
) -> Dict[str, Any]:
    """
    List files and directories within a given path.

    - **path**: Directory path (relative to upload root, default: root)

    Returns:
    - breadcrumbs: Navigation breadcrumb trail
    - directories: List of subdirectories with metadata
    - files: List of files with metadata from database index
    """
    rel = path.strip().strip("/")
    base = (UPLOAD_ROOT / rel).resolve()

    if not within_root(base):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not base.exists():
        raise HTTPException(status_code=404, detail="Path not found.")

    # Get directories from filesystem
    directories = []
    for p in sorted(base.iterdir()):
        if p.is_dir():
            rp = p.resolve().relative_to(UPLOAD_ROOT).as_posix()
            # Count files in directory (from database)
            file_count = len(db.list_files(parent_path=rp))
            directories.append({
                "name": p.name,
                "path": rp,
                "file_count": file_count,
            })

    # Get files from database index
    files = []
    db_files = db.list_files(parent_path=rel)
    for file_obj in db_files:
        files.append({
            "name": file_obj.filename,
            "path": file_obj.filepath,
            "size": file_obj.size,
            "modified": file_obj.modified_at.isoformat() if file_obj.modified_at else None,
            "extension": file_obj.extension,
            "mime_type": file_obj.mime_type,
            "preview_type": file_obj.preview_type,
            "has_thumbnail": file_obj.has_thumbnail,
        })

    # Build breadcrumbs
    crumbs = []
    current = Path(rel)
    parts = [part for part in current.parts if part not in (".",)]
    acc = Path("")
    crumbs.append({"label": "Home", "path": ""})
    for part in parts:
        acc = (acc / part)
        crumbs.append({"label": part, "path": acc.as_posix()})

    return {
        "ok": True,
        "path": rel,
        "breadcrumbs": crumbs,
        "directories": directories,
        "files": files,
    }

@app.get("/api/file/{filepath:path}", tags=["Files"])
async def get_file(
    filepath: str,
    download: bool = Query(False, description="Force download instead of inline display")
) -> FileResponse:
    """
    Serve or download a file.

    - **filepath**: File path relative to upload root
    - **download**: If true, force download; otherwise display inline
    """
    filepath = filepath.strip().strip("/")
    target = (UPLOAD_ROOT / filepath).resolve()

    if not within_root(target):
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot download a directory.")

    # Determine MIME type
    mime_type, _ = mimetypes.guess_type(str(target))

    # Return file
    if download:
        return FileResponse(
            path=target,
            media_type=mime_type,
            filename=target.name
        )
    else:
        return FileResponse(
            path=target,
            media_type=mime_type
        )

@app.delete("/api/file/{filepath:path}", tags=["Files"], response_model=None)
async def delete_file(
    filepath: str,
    force: bool = Query(False, description="Force delete non-empty directories")
) -> Union[Dict[str, Any], JSONResponse]:
    """
    Delete a file or directory.

    - **filepath**: File/directory path relative to upload root
    - **force**: If true, delete non-empty directories (use with caution)
    """
    filepath = filepath.strip().strip("/")
    target = (UPLOAD_ROOT / filepath).resolve()

    if not within_root(target):
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    if target.is_file():
        # Delete file from filesystem
        target.unlink()
        # Remove from database index
        db.remove_file(filepath)
        return {"ok": True, "message": "File deleted successfully."}

    # Handle directory
    # Check if directory is empty
    has_contents = any(target.iterdir())

    if has_contents and not force:
        # Return error indicating directory is not empty
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "directory_not_empty",
                "message": "Directory is not empty. Use force=true to delete anyway."
            }
        )

    # Delete directory (and all contents if force=true)
    shutil.rmtree(target)

    # Remove all files under this directory from index
    db.remove_directory(filepath)

    return {"ok": True, "message": "Directory deleted successfully."}

@app.post("/api/directory", tags=["Browse"])
async def create_directory(
    path: str = Query("", description="Parent directory path (relative to upload root)"),
    name: str = Query(..., min_length=1, max_length=255, description="New directory name")
) -> Dict[str, Any]:
    """
    Create a new directory.

    - **path**: Parent directory path (relative to upload root, default: root)
    - **name**: Name of the new directory

    Returns the full path of the created directory.
    """
    # Sanitize the directory name
    safe_name = secure_filename(name)

    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(
            status_code=400,
            detail="Invalid directory name. Avoid special characters, '.', and '..'."
        )

    # Validate and resolve parent directory
    parent_path = path.strip().strip("/")
    parent_dir = (UPLOAD_ROOT / parent_path).resolve()

    if not within_root(parent_dir):
        raise HTTPException(status_code=400, detail="Invalid parent directory path.")
    if not parent_dir.exists():
        raise HTTPException(status_code=404, detail="Parent directory not found.")
    if not parent_dir.is_dir():
        raise HTTPException(status_code=400, detail="Parent path is not a directory.")

    # Create the new directory
    new_dir = parent_dir / safe_name

    if new_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Directory '{safe_name}' already exists in this location."
        )

    try:
        new_dir.mkdir(parents=False, exist_ok=False)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create directory: {str(e)}"
        )

    # Return the relative path of the new directory
    new_dir_rel = new_dir.relative_to(UPLOAD_ROOT).as_posix()

    return {
        "ok": True,
        "message": f"Directory '{safe_name}' created successfully.",
        "path": new_dir_rel,
        "name": safe_name
    }

@app.get("/api/search", tags=["Search"])
async def search_files(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
) -> Dict[str, Any]:
    """
    Search for files by filename.

    - **q**: Search query (searches filename)
    - **limit**: Maximum number of results (default: 100, max: 1000)

    Returns list of matching files with full metadata.
    """
    # Search database
    results = db.search(q, limit=limit)

    # Format results
    files = []
    for file_obj in results:
        files.append({
            "name": file_obj.filename,
            "path": file_obj.filepath,
            "parent_path": file_obj.parent_path,
            "size": file_obj.size,
            "modified": file_obj.modified_at.isoformat() if file_obj.modified_at else None,
            "extension": file_obj.extension,
            "mime_type": file_obj.mime_type,
            "preview_type": file_obj.preview_type,
            "has_thumbnail": file_obj.has_thumbnail,
        })

    return {
        "ok": True,
        "query": q,
        "count": len(files),
        "results": files,
    }

@app.get("/api/thumbnail/{filepath:path}", tags=["Thumbnails"])
async def get_thumbnail(filepath: str) -> FileResponse:
    """
    Get or generate a thumbnail for an image file.

    - **filepath**: Image file path relative to upload root

    Returns JPEG thumbnail image.
    """
    filepath = filepath.strip().strip("/")
    source_file = (UPLOAD_ROOT / filepath).resolve()

    if not within_root(source_file):
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not source_file.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if not source_file.is_file():
        raise HTTPException(status_code=400, detail="Cannot generate thumbnail for directory.")

    # Check if file is an image
    extension = source_file.suffix.lower()
    preview_type, _ = get_preview_type(extension)
    if preview_type != 'image':
        raise HTTPException(status_code=400, detail="Thumbnails only available for images.")

    # Generate or retrieve thumbnail
    thumbnail_path = thumbnail_gen.generate(source_file)
    if not thumbnail_path:
        raise HTTPException(status_code=500, detail="Failed to generate thumbnail.")

    return FileResponse(thumbnail_path, media_type='image/jpeg')

@app.get("/healthz", tags=["Health"])
async def healthz() -> Dict[str, Any]:
    """
    Health check endpoint.

    Returns service status and configured upload root directory.
    """
    return {
        "ok": True,
        "root": str(UPLOAD_ROOT),
        "version": "2.0.0"
    }

# ---- Deprecated Routes (for backwards compatibility) ----

@app.get("/api/dirs", tags=["Browse"], deprecated=True)
async def list_dirs(
    path: str = Query("", description="Directory path relative to upload root")
) -> Dict[str, Any]:
    """
    List subdirectories within a given path.

    **DEPRECATED**: Use /api/browse instead for both files and directories.
    """
    rel = path.strip().strip("/")
    base = (UPLOAD_ROOT / rel).resolve()

    if not within_root(base):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not base.exists():
        raise HTTPException(status_code=404, detail="Path not found.")

    entries = []
    for p in sorted(base.iterdir()):
        if p.is_dir():
            rp = p.resolve().relative_to(UPLOAD_ROOT).as_posix()
            entries.append({"name": p.name, "relpath": rp})

    # Build breadcrumbs
    crumbs = []
    current = Path(rel)
    parts = [part for part in current.parts if part not in (".",)]
    acc = Path("")
    crumbs.append({"label": "/", "relpath": ""})
    for part in parts:
        acc = (acc / part)
        crumbs.append({"label": part, "relpath": acc.as_posix()})

    return {
        "ok": True,
        "path": rel,
        "breadcrumbs": crumbs,
        "dirs": entries,
    }

# ---- Startup ----

if __name__ == "__main__":
    import uvicorn

    # Print configuration on startup
    print("\n" + "="*50)
    print("LAN Uploader Configuration")
    print("="*50)
    print(f"Upload Root:    {UPLOAD_ROOT}")
    print(f"Max Size:       {config['MAX_CONTENT_LENGTH_MB']} MB")
    print(f"Database:       {DB_PATH}")
    print(f"Host:           {HOST}")
    print(f"Port:           {PORT}")
    print(f"API Docs:       http://{HOST}:{PORT}/docs")
    print("="*50 + "\n")

    # Run with uvicorn
    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        reload=True
    )

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
from fastapi import FastAPI, UploadFile, File, Form, Query, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from werkzeug.utils import secure_filename
from dataclasses import dataclass, field
from enum import Enum
import uuid
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

from models import DatabaseManager, FileIndex
from thumbnails import ThumbnailGenerator

# Thread pool for CPU-bound thumbnail generation (prevents blocking async event loop)
_thumbnail_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbnail")

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

# Set temp directory to upload root to avoid /tmp partition filling up on large uploads
# This affects Starlette's SpooledTemporaryFile used by UploadFile
import tempfile
UPLOAD_TEMP_DIR = UPLOAD_ROOT / ".tmp"
UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(UPLOAD_TEMP_DIR)

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

# Add cache-busting filter for static files
STATIC_DIR = Path("static")
def static_url(path: str) -> str:
    """Generate static URL with cache-busting query string based on file mtime."""
    file_path = STATIC_DIR / path
    if file_path.exists():
        mtime = int(file_path.stat().st_mtime)
        return f"/static/{path}?v={mtime}"
    return f"/static/{path}"

templates.env.globals["static_url"] = static_url

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

# ---- WebSocket Infrastructure ----

class UploadStatus(Enum):
    """Upload session status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class UploadSession:
    """Represents an upload session."""
    id: str
    status: UploadStatus = UploadStatus.PENDING
    total_files: int = 0
    files_completed: int = 0
    total_bytes: int = 0
    bytes_written: int = 0
    files_saved: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class UploadSessionManager:
    """
    Manages upload sessions and WebSocket connections.

    Responsibilities:
        - Track active upload sessions
        - Manage WebSocket connections
        - Broadcast progress updates
        - Handle session lifecycle
    """

    def __init__(self) -> None:
        """Initialize the upload session manager."""
        self.sessions: Dict[str, UploadSession] = {}
        self.connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    def register_connection(self, session_id: str, websocket: WebSocket) -> None:
        """
        Register a WebSocket connection for a session.

        Args:
            session_id: Unique session identifier
            websocket: WebSocket connection to register
        """
        self.connections[session_id] = websocket
        self.sessions[session_id] = UploadSession(id=session_id)

    def unregister_connection(self, session_id: str) -> None:
        """
        Unregister a WebSocket connection.

        Args:
            session_id: Session identifier to unregister
        """
        if session_id in self.connections:
            del self.connections[session_id]

        # Keep session data for a while for potential reconnects
        # Clean up old sessions after 1 hour
        try:
            asyncio.create_task(self._cleanup_session(session_id, delay=3600))
        except RuntimeError:
            # No event loop running (e.g., during testing)
            pass

    async def _cleanup_session(self, session_id: str, delay: int) -> None:
        """
        Clean up session after delay.

        Args:
            session_id: Session to clean up
            delay: Delay in seconds before cleanup
        """
        await asyncio.sleep(delay)
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                if session.status in (UploadStatus.COMPLETED, UploadStatus.FAILED, UploadStatus.CANCELLED):
                    del self.sessions[session_id]

    def get_session(self, session_id: str) -> Optional[UploadSession]:
        """
        Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            UploadSession if found, None otherwise
        """
        return self.sessions.get(session_id)

    async def start_upload(
        self,
        session_id: str,
        total_files: int,
        total_bytes: int = 0
    ) -> None:
        """
        Mark upload as started.

        Args:
            session_id: Session identifier
            total_files: Total number of files to upload
            total_bytes: Total bytes to upload (optional)
        """
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                session.status = UploadStatus.IN_PROGRESS
                session.total_files = total_files
                session.total_bytes = total_bytes
                session.started_at = datetime.now()

        await self.send_message(session_id, {
            "type": "upload_started",
            "total_files": total_files,
            "total_bytes": total_bytes
        })

    async def update_progress(
        self,
        session_id: str,
        files_completed: int,
        bytes_written: int
    ) -> None:
        """
        Update upload progress.

        Args:
            session_id: Session identifier
            files_completed: Number of files completed so far
            bytes_written: Number of bytes written so far
        """
        async with self._lock:
            if session_id not in self.sessions:
                return

            session = self.sessions[session_id]
            session.files_completed = files_completed
            session.bytes_written = bytes_written

            # Calculate percentage
            if session.total_files > 0:
                percent = int((files_completed / session.total_files) * 100)
            else:
                percent = 0

        await self.send_message(session_id, {
            "type": "progress",
            "percent": percent,
            "files_done": files_completed,
            "total_files": session.total_files,
            "bytes_written": bytes_written,
            "total_bytes": session.total_bytes
        })

    async def file_completed(
        self,
        session_id: str,
        filename: str,
        size: int,
        path: str
    ) -> None:
        """
        Notify that a file was completed.

        Args:
            session_id: Session identifier
            filename: Name of completed file
            size: File size in bytes
            path: Relative path to file
        """
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                session.files_saved.append({
                    "name": filename,
                    "size": size,
                    "path": path
                })

        await self.send_message(session_id, {
            "type": "file_complete",
            "filename": filename,
            "size": size,
            "path": path
        })

    async def upload_error(
        self,
        session_id: str,
        error_message: str,
        error_code: int = 500,
        filename: Optional[str] = None
    ) -> None:
        """
        Report an upload error.

        Args:
            session_id: Session identifier
            error_message: Error message
            error_code: HTTP error code
            filename: Optional filename that caused the error
        """
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                session.status = UploadStatus.FAILED
                session.error_message = error_message
                session.errors.append({
                    "file": filename,
                    "error": error_message,
                    "code": error_code
                })
                session.completed_at = datetime.now()

        await self.send_message(session_id, {
            "type": "error",
            "message": error_message,
            "code": error_code,
            "filename": filename
        })

    async def upload_complete(self, session_id: str) -> None:
        """
        Mark upload as complete.

        Args:
            session_id: Session identifier
        """
        async with self._lock:
            if session_id not in self.sessions:
                return

            session = self.sessions[session_id]
            session.status = UploadStatus.COMPLETED
            session.completed_at = datetime.now()

        await self.send_message(session_id, {
            "type": "complete",
            "total_files": session.files_completed,
            "total_bytes": session.bytes_written,
            "files_saved": session.files_saved,
            "errors": session.errors
        })

    async def cancel_upload(self, session_id: str) -> None:
        """
        Cancel an upload (future feature).

        Args:
            session_id: Session identifier
        """
        async with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                session.status = UploadStatus.CANCELLED
                session.completed_at = datetime.now()

        await self.send_message(session_id, {
            "type": "cancelled"
        })

    async def send_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """
        Send a message to a specific session.

        Args:
            session_id: Session identifier
            message: Message dictionary to send as JSON
        """
        if session_id in self.connections:
            websocket = self.connections[session_id]
            try:
                await websocket.send_json(message)
            except Exception:
                # Silently ignore send errors (connection may have closed)
                pass


# Global upload session manager instance
upload_manager = UploadSessionManager()

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
    Stream an uploaded file to a .part file, then rename on success.

    Writes to a temporary .part file in the same directory as the destination,
    avoiding /tmp partition issues for large files. On success, atomically
    renames to the final destination.

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
    part_file = destination.parent / f".{destination.name}.part"

    try:
        async with aiofiles.open(part_file, 'wb') as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                await f.write(chunk)
                bytes_written += len(chunk)
        # Atomic rename on success
        part_file.rename(destination)
    except Exception as e:
        # Clean up partial file on any error
        if part_file.exists():
            part_file.unlink()
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
    target_dir: str = Form(""),
    session_id: Optional[str] = Form(None)
) -> JSONResponse:
    """
    Upload one or more files to a directory with streaming.

    Files are written directly to the upload directory as they arrive,
    avoiding the use of temporary file storage.

    - **files**: List of files to upload
    - **target_dir**: Target directory path (relative to upload root)
    - **session_id**: Optional WebSocket session ID for real-time progress updates

    If session_id is provided, progress updates are sent via WebSocket.
    Otherwise, operates in legacy mode (no real-time updates).

    Returns a list of uploaded files with metadata.
    Sets a cookie to remember the upload directory.
    """
    target_dir = target_dir.strip().strip("/")
    target = safe_target_dir(target_dir)

    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    # Calculate total size for progress tracking
    total_files = len(files)
    total_bytes = sum(file.size or 0 for file in files)

    # Check disk space before starting upload
    try:
        _, _, available_bytes = check_disk_space(UPLOAD_ROOT)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check disk space: {str(e)}"
        )

    # Check if we have enough disk space
    if total_bytes > available_bytes:
        error_msg = f"Insufficient storage. Need {total_bytes//1024//1024}MB, have {available_bytes//1024//1024}MB"

        # Send error via WebSocket if session exists
        if session_id:
            await upload_manager.upload_error(session_id, error_msg, error_code=507)

        raise HTTPException(status_code=507, detail=error_msg)

    # Start upload session if session_id provided
    if session_id:
        await upload_manager.start_upload(session_id, total_files, total_bytes)

    saved = []
    errors = []
    bytes_written_total = 0

    for index, file in enumerate(files):
        if not file.filename:
            continue

        filename = secure_filename(file.filename)
        if not filename or filename in (".", ".."):
            error = {"file": file.filename, "error": "Invalid filename"}
            errors.append(error)

            # Notify via WebSocket
            if session_id:
                await upload_manager.upload_error(
                    session_id,
                    "Invalid filename",
                    error_code=400,
                    filename=file.filename
                )
            continue

        dest = target / filename

        # Check if file already exists
        if dest.exists():
            error = {"file": filename, "error": "File already exists"}
            errors.append(error)

            if session_id:
                await upload_manager.upload_error(
                    session_id,
                    "File already exists",
                    error_code=409,
                    filename=filename
                )
            continue

        try:
            # Stream file directly to destination
            bytes_written = await stream_upload_to_file(file, dest)
            bytes_written_total += bytes_written

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

            # Generate thumbnail in background (non-blocking) if image
            if preview_type == 'image':
                def _generate_thumbnail(path: Path) -> None:
                    try:
                        thumbnail_gen.generate(path)
                    except Exception:
                        pass  # Thumbnail generation failure is not critical
                asyncio.get_event_loop().run_in_executor(_thumbnail_executor, _generate_thumbnail, dest)

            file_info = {
                "filename": filename,
                "relative_path": f"/{target_dir}" if target_dir else "/",
                "bytes": bytes_written,
            }
            saved.append(file_info)

            # Send file completion via WebSocket
            if session_id:
                await upload_manager.file_completed(
                    session_id,
                    filename=filename,
                    size=bytes_written,
                    path=filepath_rel
                )

                # Send progress update
                await upload_manager.update_progress(
                    session_id,
                    files_completed=index + 1,
                    bytes_written=bytes_written_total
                )

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

                # Send error via WebSocket IMMEDIATELY
                if session_id:
                    await upload_manager.upload_error(
                        session_id,
                        error_msg,
                        error_code=507,
                        filename=filename
                    )

                # Stop processing remaining files if disk is full
                error_detail = f"Disk full after {len(saved)} files. {len(files) - len(saved) - len(errors)} files not uploaded."

                if session_id:
                    await upload_manager.upload_error(session_id, error_detail, error_code=507)

                raise HTTPException(status_code=507, detail=error_detail)

            elif e.errno == 13:  # EACCES - Permission denied
                error_msg = "Permission denied"

            errors.append({
                "file": filename,
                "error": error_msg
            })

            if session_id:
                await upload_manager.upload_error(
                    session_id,
                    error_msg,
                    error_code=507 if e.errno == 28 else 500,
                    filename=filename
                )

        except Exception as e:
            # Handle any other errors
            if dest.exists():
                dest.unlink()  # Clean up partial file

            error = {"file": filename, "error": str(e)}
            errors.append(error)

            if session_id:
                await upload_manager.upload_error(
                    session_id,
                    str(e),
                    error_code=500,
                    filename=filename
                )

    # Mark upload as complete
    if session_id:
        await upload_manager.upload_complete(session_id)

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


# ---- Filesystem/DB Helpers ----

def index_file_from_path(path: Path) -> 'FileIndex':
    """
    Index a file from filesystem and return the DB record.

    This performs lazy caching: reads file metadata from filesystem,
    stores it in the database, and returns the record.

    Args:
        path: Absolute path to the file

    Returns:
        FileIndex object with file metadata
    """
    stat = path.stat()
    rel_path = path.relative_to(UPLOAD_ROOT).as_posix()
    parent = path.parent.relative_to(UPLOAD_ROOT).as_posix() if path.parent != UPLOAD_ROOT else ""
    ext = path.suffix.lower()
    mime, _ = mimetypes.guess_type(path.name)
    preview_type, _ = get_preview_type(ext)

    # Check if thumbnail actually exists in cache
    has_thumb = preview_type == 'image' and thumbnail_gen.get_cached(path) is not None

    return db.index_file(
        filepath=rel_path,
        filename=path.name,
        parent_path=parent,
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime),
        extension=ext,
        mime_type=mime,
        has_thumbnail=has_thumb,
        preview_type=preview_type,
    )


@app.get("/api/browse", tags=["Browse"])
async def browse(
    path: str = Query("", description="Directory path relative to upload root"),
    limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> Dict[str, Any]:
    """
    List files and directories within a given path.

    Uses filesystem as source of truth for what exists, with DB as metadata cache.
    New files discovered on filesystem are automatically indexed (lazy caching).
    Supports pagination via limit/offset for large directories.

    - **path**: Directory path (relative to upload root, default: root)
    - **limit**: Maximum number of items to return (default: 50, max: 500)
    - **offset**: Number of items to skip for pagination (default: 0)

    Returns:
    - breadcrumbs: Navigation breadcrumb trail
    - directories: List of subdirectories with file counts (paginated)
    - files: List of files with metadata (paginated)
    - total_directories: Total number of directories in this path
    - total_files: Total number of files in this path
    - has_more: Whether more items are available
    """
    rel = path.strip().strip("/")
    base = (UPLOAD_ROOT / rel).resolve()

    if not within_root(base):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not base.exists():
        raise HTTPException(status_code=404, detail="Path not found.")

    # Get directories and files from FILESYSTEM (source of truth for what exists)
    # First pass: collect all paths for counting and pagination
    all_dir_paths = []
    all_file_paths = []

    for p in sorted(base.iterdir()):
        # Skip hidden files/directories
        if p.name.startswith('.'):
            continue

        if p.is_dir():
            all_dir_paths.append(p)
        elif p.is_file():
            all_file_paths.append(p)

    # Calculate totals before pagination
    total_directories = len(all_dir_paths)
    total_files = len(all_file_paths)
    total_items = total_directories + total_files

    # Apply pagination: directories first, then files
    # Determine which items to include based on offset and limit
    directories = []
    files = []
    items_returned = 0

    # Process directories (they come first in the listing)
    dir_start = offset
    dir_end = min(offset + limit, total_directories)

    if dir_start < total_directories:
        for p in all_dir_paths[dir_start:dir_end]:
            rp = p.resolve().relative_to(UPLOAD_ROOT).as_posix()
            # Count files directly from filesystem
            try:
                file_count = sum(1 for f in p.iterdir() if f.is_file() and not f.name.startswith('.'))
            except PermissionError:
                file_count = 0
            directories.append({
                "name": p.name,
                "path": rp,
                "file_count": file_count,
            })
            items_returned += 1

    # Process files (after directories)
    remaining_limit = limit - items_returned
    if remaining_limit > 0:
        # Calculate file offset: if we've passed all directories, adjust offset for files
        file_offset = max(0, offset - total_directories)
        file_end = min(file_offset + remaining_limit, total_files)

        for p in all_file_paths[file_offset:file_end]:
            rel_path = p.relative_to(UPLOAD_ROOT).as_posix()

            # Check DB cache for metadata
            db_file = db.get_file(rel_path)

            if db_file is None:
                # Lazy cache: index this file now
                db_file = index_file_from_path(p)

            files.append({
                "name": db_file.filename,
                "path": db_file.filepath,
                "size": db_file.size,
                "modified": db_file.modified_at.isoformat() if db_file.modified_at else None,
                "extension": db_file.extension,
                "mime_type": db_file.mime_type,
                "preview_type": db_file.preview_type,
                "has_thumbnail": db_file.has_thumbnail,
            })
            items_returned += 1

    # Calculate if there are more items
    has_more = (offset + items_returned) < total_items

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
        "total_directories": total_directories,
        "total_files": total_files,
        "has_more": has_more,
    }


@app.post("/api/sync", tags=["Admin"])
async def sync_database() -> Dict[str, Any]:
    """
    Synchronize database with filesystem.

    Walks the entire upload directory and:
    - Adds files that exist on disk but not in DB
    - Updates files where size has changed (stale cache)
    - Removes DB entries for files that no longer exist

    Run via cron: 0 3 * * * curl -X POST http://localhost:8080/api/sync
    """
    added = 0
    updated = 0
    removed = 0

    # Track all files found on filesystem
    fs_files = set()

    # Walk filesystem and sync to DB
    for path in UPLOAD_ROOT.rglob('*'):
        if path.is_file() and not path.name.startswith('.'):
            rel_path = path.relative_to(UPLOAD_ROOT).as_posix()
            fs_files.add(rel_path)

            db_file = db.get_file(rel_path)

            if db_file is None:
                # New file - add to DB
                index_file_from_path(path)
                added += 1
            else:
                # Check if size changed (file was modified)
                try:
                    stat = path.stat()
                    if db_file.size != stat.st_size:
                        index_file_from_path(path)
                        updated += 1
                except OSError:
                    pass  # File may have been deleted between rglob and stat

    # Remove stale DB entries (files deleted from filesystem)
    with db.get_session() as session:
        from models import FileIndex
        all_db_files = session.query(FileIndex).all()
        for db_file in all_db_files:
            if db_file.filepath not in fs_files:
                session.delete(db_file)
                removed += 1
        session.commit()

    return {
        "ok": True,
        "added": added,
        "updated": updated,
        "removed": removed,
        "total_files": len(fs_files),
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

@app.websocket("/api/upload/ws")
async def upload_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time upload progress and status updates.

    Protocol:
        Client -> Server:
            - (implicit connection = request session)
            - { "type": "ping" } - Keepalive ping

        Server -> Client:
            - { "type": "session_id", "id": "uuid" } - Session initialization
            - { "type": "upload_started", "total_files": N, "total_bytes": N }
            - { "type": "progress", "percent": N, "files_done": N, "total_files": N, ... }
            - { "type": "file_complete", "filename": "...", "size": N, "path": "..." }
            - { "type": "error", "message": "...", "code": N, "filename": "..." }
            - { "type": "complete", "total_files": N, "total_bytes": N, ... }
            - { "type": "pong" } - Keepalive response
    """
    await websocket.accept()

    # Generate session ID
    session_id = str(uuid.uuid4())

    # Register connection
    upload_manager.register_connection(session_id, websocket)

    try:
        # Send session ID to client
        await websocket.send_json({
            "type": "session_id",
            "id": session_id
        })

        # Keep connection alive and listen for messages
        while True:
            # Receive messages (client might send cancel, pause, etc. in future)
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle client messages
            if message.get('type') == 'ping':
                await websocket.send_json({"type": "pong"})
            elif message.get('type') == 'cancel':
                # Future: Handle cancel request
                await upload_manager.cancel_upload(session_id)

    except WebSocketDisconnect:
        pass  # Normal disconnection
    except Exception:
        pass  # Other errors during WebSocket communication
    finally:
        # Cleanup
        upload_manager.unregister_connection(session_id)


@app.get("/api/upload/status/{session_id}", tags=["Upload"])
async def get_upload_status(session_id: str) -> Dict[str, Any]:
    """
    Get upload status for a session (polling fallback if WebSocket unavailable).

    Args:
        session_id: Session identifier

    Returns:
        Session status with progress information
    """
    session = upload_manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Calculate progress percentage
    if session.total_files > 0:
        percent = int((session.files_completed / session.total_files) * 100)
    else:
        percent = 0

    return {
        "session_id": session.id,
        "status": session.status.value,
        "total_files": session.total_files,
        "files_completed": session.files_completed,
        "total_bytes": session.total_bytes,
        "bytes_written": session.bytes_written,
        "percent": percent,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "errors": session.errors
    }


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

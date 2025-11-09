#!/usr/bin/env python3
import os
import argparse
import mimetypes
from datetime import datetime
from pathlib import Path
from configparser import ConfigParser
from flask import Flask, request, render_template, jsonify, make_response, abort, send_file
from werkzeug.utils import secure_filename
from models import DatabaseManager, FileIndex
from thumbnails import ThumbnailGenerator

# ---- Configuration Loading ----
# Priority: 1) Command line args, 2) Environment variables, 3) Config file, 4) Hardcoded defaults

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="LAN Uploader - A tiny, mobile-first file uploader for your local network"
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

def load_config(args=None):
    """Load configuration with priority: CLI args > env vars > config file > defaults."""
    # Defaults
    config = {
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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Ensure root exists
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# Initialize database
db_url = f"sqlite:///{DB_PATH}"
db = DatabaseManager(db_url)
db.init_db()

# Initialize thumbnail generator
THUMBNAIL_CACHE_DIR = UPLOAD_ROOT / ".thumbnails"
thumbnail_gen = ThumbnailGenerator(THUMBNAIL_CACHE_DIR)

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

def get_preview_type(extension: str) -> tuple[str, str]:
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
            return preview_type, info['method']
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

    Raises 400 error if path attempts to escape UPLOAD_ROOT.
    """
    subpath = (subpath or "").strip().strip("/")
    target = (UPLOAD_ROOT / subpath).resolve()
    if not within_root(target):
        abort(400, description="Invalid target directory.")
    target.mkdir(parents=True, exist_ok=True)
    return target

@app.route("/", methods=["GET"])
def index():
    """
    Serve the main upload page.

    Reads the 'last_dir' cookie to prefill the directory input field,
    providing a better UX by remembering the user's last upload location.
    """
    last_dir = request.cookies.get("last_dir", "")
    # Sanitize cookie value for display (validation happens on upload)
    last_dir = last_dir.strip().strip("/")
    return render_template("upload.html", last_dir=last_dir)

@app.route("/upload", methods=["POST"])
def upload():
    """
    Handle file uploads.

    Accepts single or multiple files via form data, validates the target
    directory, saves files with secure filenames, and returns upload results.
    Sets a cookie to remember the upload directory for future uploads.
    """
    target_dir = request.form.get("target_dir", "").strip().strip("/")
    target = safe_target_dir(target_dir)

    # Accept both single and multiple file inputs
    # HTML will submit name="files" (multiple), but support "file" too.
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]

    if not files:
        abort(400, description="No files provided.")

    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        filename = secure_filename(f.filename)
        dest = (target / filename)
        f.save(dest)

        # Index the file in the database
        file_stat = dest.stat()
        extension = dest.suffix.lower()
        mime_type, _ = mimetypes.guess_type(str(dest))
        preview_type, preview_method = get_preview_type(extension)
        has_thumbnail = preview_type == 'image'  # For now, only images get thumbnails

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

        saved.append({
            "filename": filename,
            "relative_path": f"/{target_dir}" if target_dir else "/",
            "bytes": file_stat.st_size,
        })

    resp = make_response(jsonify({"ok": True, "saved": saved, "target_dir": target_dir}))
    # Remember last dir for 30 days (samesite=Lax prevents CSRF)
    resp.set_cookie("last_dir", target_dir, max_age=60*60*24*30, samesite="Lax")
    return resp

@app.route("/api/dirs", methods=["GET"])
def list_dirs():
    """
    List subdirectories within a given path (relative to root).
    Query params:
      - path: relative path from UPLOAD_ROOT

    DEPRECATED: Use /api/browse instead for both files and directories.
    """
    rel = (request.args.get("path") or "").strip().strip("/")
    base = (UPLOAD_ROOT / rel).resolve()
    if not within_root(base):
        abort(400, description="Invalid path.")
    if not base.exists():
        abort(404, description="Path not found.")

    entries = []
    for p in sorted(base.iterdir()):
        if p.is_dir():
            rp = p.resolve().relative_to(UPLOAD_ROOT).as_posix()
            entries.append({"name": p.name, "relpath": rp})

    # Also include breadcrumbs
    crumbs = []
    current = Path(rel)
    # Build breadcrumb segments
    parts = [part for part in current.parts if part not in (".",)]
    acc = Path("")
    crumbs.append({"label": "/", "relpath": ""})
    for part in parts:
        acc = (acc / part)
        crumbs.append({"label": part, "relpath": acc.as_posix()})
    return jsonify({
        "ok": True,
        "path": rel,
        "breadcrumbs": crumbs,
        "dirs": entries,
    })

@app.route("/api/browse", methods=["GET"])
def browse():
    """
    List files and directories within a given path (relative to root).
    Query params:
      - path: relative path from UPLOAD_ROOT (default: "")

    Returns:
      - breadcrumbs: navigation breadcrumb trail
      - directories: list of subdirectories with names and paths
      - files: list of files with metadata (from database index)
    """
    rel = (request.args.get("path") or "").strip().strip("/")
    base = (UPLOAD_ROOT / rel).resolve()

    if not within_root(base):
        abort(400, description="Invalid path.")
    if not base.exists():
        abort(404, description="Path not found.")

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

    return jsonify({
        "ok": True,
        "path": rel,
        "breadcrumbs": crumbs,
        "directories": directories,
        "files": files,
    })

@app.route("/api/file/<path:filepath>", methods=["GET", "DELETE"])
def file_operation(filepath):
    """
    Handle file operations (download/serve or delete).

    GET: Serve/download the file
    DELETE: Delete the file (or directory with ?force=1)

    Args:
        filepath: Relative path from UPLOAD_ROOT
        Query params (DELETE only):
          - force: Set to '1' or 'true' to delete non-empty directories
    """
    # Sanitize and validate path
    filepath = filepath.strip().strip("/")
    target = (UPLOAD_ROOT / filepath).resolve()

    if not within_root(target):
        abort(400, description="Invalid file path.")
    if not target.exists():
        abort(404, description="File not found.")

    if request.method == "GET":
        # Serve the file
        if target.is_dir():
            abort(400, description="Cannot download a directory.")

        # Determine if we should force download or display inline
        download = request.args.get("download", "").lower() in ("1", "true")
        return send_file(
            target,
            as_attachment=download,
            mimetype=mimetypes.guess_type(str(target))[0]
        )

    elif request.method == "DELETE":
        # Delete the file or directory
        if target.is_file():
            # Delete file from filesystem
            target.unlink()
            # Remove from database index
            db.remove_file(filepath)
            return jsonify({"ok": True, "message": "File deleted successfully."})

        elif target.is_dir():
            # Check if directory is empty
            has_contents = any(target.iterdir())
            force = request.args.get("force", "").lower() in ("1", "true")

            if has_contents and not force:
                # Return error indicating directory is not empty
                return jsonify({
                    "ok": False,
                    "error": "directory_not_empty",
                    "message": "Directory is not empty. Use force=1 to delete anyway."
                }), 400

            # Delete directory (and all contents if force=1)
            import shutil
            shutil.rmtree(target)

            # Remove all files under this directory from index
            db.remove_directory(filepath)

            return jsonify({"ok": True, "message": "Directory deleted successfully."})

@app.route("/api/search", methods=["GET"])
def search():
    """
    Search for files by filename.

    Query params:
      - q: search query
      - limit: maximum number of results (default: 100)

    Returns:
      List of matching files with full metadata
    """
    query = request.args.get("q", "").strip()
    if not query:
        abort(400, description="Search query required (param: q)")

    limit = request.args.get("limit", "100")
    try:
        limit = int(limit)
    except ValueError:
        limit = 100

    # Search database
    results = db.search(query, limit=limit)

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

    return jsonify({
        "ok": True,
        "query": query,
        "count": len(files),
        "results": files,
    })

@app.route("/api/thumbnail/<path:filepath>", methods=["GET"])
def get_thumbnail(filepath):
    """
    Get or generate a thumbnail for an image file.

    Args:
        filepath: Relative path from UPLOAD_ROOT

    Returns:
        JPEG thumbnail image
    """
    # Sanitize and validate path
    filepath = filepath.strip().strip("/")
    source_file = (UPLOAD_ROOT / filepath).resolve()

    if not within_root(source_file):
        abort(400, description="Invalid file path.")
    if not source_file.exists():
        abort(404, description="File not found.")
    if not source_file.is_file():
        abort(400, description="Cannot generate thumbnail for directory.")

    # Check if file is an image
    extension = source_file.suffix.lower()
    preview_type, _ = get_preview_type(extension)
    if preview_type != 'image':
        abort(400, description="Thumbnails only available for images.")

    # Generate or retrieve thumbnail
    thumbnail_path = thumbnail_gen.generate(source_file)
    if not thumbnail_path:
        abort(500, description="Failed to generate thumbnail.")

    return send_file(thumbnail_path, mimetype='image/jpeg')

@app.route("/healthz")
def healthz():
    """
    Health check endpoint.

    Returns a simple JSON response indicating the service is running
    and shows the configured upload root directory.
    """
    return {"ok": True, "root": str(UPLOAD_ROOT)}, 200

if __name__ == "__main__":
    # Print configuration on startup
    print("\n" + "="*50)
    print("LAN Uploader Configuration")
    print("="*50)
    print(f"Upload Root:    {UPLOAD_ROOT}")
    print(f"Max Size:       {config['MAX_CONTENT_LENGTH_MB']} MB")
    print(f"Host:           {HOST}")
    print(f"Port:           {PORT}")
    print("="*50 + "\n")

    # Bind to configured host (0.0.0.0 for LAN access, 127.0.0.1 for localhost only)
    app.run(host=HOST, port=PORT, debug=True)

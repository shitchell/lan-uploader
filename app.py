#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
from configparser import ConfigParser
from flask import Flask, request, render_template, jsonify, make_response, abort
from werkzeug.utils import secure_filename

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
    return parser.parse_args()

def load_config(args=None):
    """Load configuration with priority: CLI args > env vars > config file > defaults."""
    # Defaults
    config = {
        "UPLOAD_ROOT": "./uploads",
        "MAX_CONTENT_LENGTH_MB": "1024",
        "PORT": "8080",
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

    return config

args = parse_args()
config = load_config(args)
UPLOAD_ROOT = Path(config["UPLOAD_ROOT"]).resolve()
MAX_CONTENT_LENGTH = int(config["MAX_CONTENT_LENGTH_MB"]) * 1024 * 1024  # MB -> bytes
PORT = int(config["PORT"])

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Ensure root exists
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

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
        saved.append({
            "filename": filename,
            "relative_path": f"/{target_dir}" if target_dir else "/",
            "bytes": dest.stat().st_size,
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

@app.route("/healthz")
def healthz():
    """
    Health check endpoint.

    Returns a simple JSON response indicating the service is running
    and shows the configured upload root directory.
    """
    return {"ok": True, "root": str(UPLOAD_ROOT)}, 200

if __name__ == "__main__":
    # Bind on all interfaces for LAN access
    app.run(host="0.0.0.0", port=PORT, debug=True)

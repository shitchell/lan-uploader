#!/usr/bin/env python3
import os
from pathlib import Path
from flask import Flask, request, render_template, jsonify, make_response, send_from_directory, abort
from werkzeug.utils import secure_filename

# ---- Configuration ----
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "./uploads")).resolve()
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", "1024")) * 1024 * 1024  # MB -> bytes

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Ensure root exists
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

def within_root(p: Path) -> bool:
    """Return True if path p is inside UPLOAD_ROOT."""
    try:
        p.resolve().relative_to(UPLOAD_ROOT)
        return True
    except Exception:
        return False

def safe_target_dir(subpath: str) -> Path:
    """Sanitize/resolve a user-provided subpath within UPLOAD_ROOT."""
    # Normalize and remove leading slashes to keep it relative
    subpath = (subpath or "").strip().strip("/")
    target = (UPLOAD_ROOT / subpath).resolve()
    if not within_root(target):
        abort(400, description="Invalid target directory.")
    target.mkdir(parents=True, exist_ok=True)
    return target

@app.route("/", methods=["GET"])
def index():
    last_dir = request.cookies.get("last_dir", "")
    # Ensure the cookie path is safe-ish for prefill (don't create/resolve here)
    last_dir = last_dir.strip().strip("/")
    return render_template("upload.html", last_dir=last_dir)

@app.route("/upload", methods=["POST"])
def upload():
    # Choose target dir (relative to root)
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
    # Remember last dir for 30 days
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
    return {"ok": True, "root": str(UPLOAD_ROOT)}, 200

if __name__ == "__main__":
    # Bind on all interfaces for LAN access
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True)

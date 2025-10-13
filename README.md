# LAN Uploader (Flask)

A tiny, mobile‑first file uploader for your local network.

## Features
- **Mobile‑first UI**: Drag‑and‑drop or tap‑to‑pick (camera capture attribute enabled on many phones)
- **File preview**: See selected files with names and sizes before uploading
- **Cumulative selection**: Add more files to your selection without replacing existing ones
- **Directory management**: Save to a chosen subdirectory **within a configured root**
- **Smart memory**: Remembers last used directory via localStorage (persists across sessions)
- **Directory browser**: Server‑side browser limited to the configured root
- **Path security**: Prevents directory traversal attacks
- **Multi‑file support**: Upload single or multiple files at once
- **Dark mode**: Automatically follows system theme preference
- **Flexible config**: Environment variables, config file, or hardcoded defaults
- **Health check**: `/healthz` endpoint for monitoring

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Or with custom settings:
```bash
python app.py --upload-root /var/mywebapp/uploads --port 8080 --max-size 2048
```

Then visit from phone/desktop on same LAN:
```
http://<server-ip>:8080
```

## Configuration

Configuration is loaded in this priority order:
1. **Command line arguments** (highest priority)
2. **Environment variables**
3. **Config file** at `~/.lanuploaderc`
4. **Hardcoded defaults** (lowest priority)

### Available Options
- `UPLOAD_ROOT`: absolute or relative path to the root directory for uploads (default: `./uploads`)
- `MAX_CONTENT_LENGTH_MB` / `max-size`: max request size in megabytes (default: `1024` = 1GB)
- `PORT`: HTTP port (default: `8080`)
- `HOST`: host to bind to - `0.0.0.0` for LAN access, `127.0.0.1` for localhost only (default: `0.0.0.0`)

### Command Line Arguments
```bash
python app.py --help
python app.py --upload-root /path/to/uploads --port 8080 --max-size 2048 --host 0.0.0.0
```

Options:
- `--upload-root PATH`: Upload root directory
- `--port PORT`: Server port
- `--max-size MB`: Maximum upload size in megabytes
- `--host HOST`: Host to bind to (0.0.0.0 for LAN, 127.0.0.1 for localhost only)

### Environment Variables
```bash
export UPLOAD_ROOT="/var/mywebapp/uploads"
export PORT=8080
export MAX_CONTENT_LENGTH_MB=2048
export HOST=0.0.0.0
python app.py
```

### Config File Format
Create `~/.lanuploaderc` with INI format:
```ini
[lanuploader]
UPLOAD_ROOT = /var/mywebapp/uploads
MAX_CONTENT_LENGTH_MB = 2048
PORT = 8080
HOST = 0.0.0.0
```

See `.lanuploaderc.example` for a template.

## Systemd (optional)

A systemd service file is included in the repository: `lan-uploader.service`

To install:
```bash
# Copy the service file
sudo cp lan-uploader.service /etc/systemd/system/

# Edit environment variables as needed
sudo nano /etc/systemd/system/lan-uploader.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now lan-uploader

# Check status
sudo systemctl status lan-uploader
```

The service file includes:
- Example environment variable configuration (commented out)
- Working directory setup
- Auto-restart on failure
- Security hardening options

## Notes
- Camera capture: `<input capture>` is enabled; some mobile browsers require `accept="image/*"` to auto‑open camera. This app sets `capture` and allows any file. If you want camera‑only, change `accept` to `image/*` or `video/*` in `templates/upload.html`.
- Security: No auth by default (LAN‑only). Consider adding a simple PIN header or HTTP Basic if you expose beyond your LAN.
- Path safety: All paths are resolved and enforced to be children of `UPLOAD_ROOT`.
- Extending: Add auth, file type filters, or a progress bar via `XMLHttpRequest` + progress events.

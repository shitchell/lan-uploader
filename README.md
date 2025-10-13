# LAN Uploader (Flask)

A tiny, mobile‑first file uploader for your local network.

## Features
- Drag‑and‑drop or tap‑to‑pick (mobile friendly; camera capture attribute enabled on many phones)
- Save to a chosen subdirectory **within a configured root**
- Remembers last used directory via cookie (per browser/device)
- Directory browser (server‑side) limited to the configured root
- Safe path handling (prevents path traversal)
- Single file or multi‑file uploads
- Health check endpoint: `/healthz`

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install flask
export UPLOAD_ROOT="$PWD/uploads"   # or /var/mywebapp/uploads
export PORT=8080
python app.py
```

Then visit from phone/desktop on same LAN:
```
http://<server-ip>:8080
```

## Configuration
- `UPLOAD_ROOT` (env): absolute or relative path to the root directory for uploads (default: `./uploads`)
- `MAX_CONTENT_LENGTH_MB` (env): max request size in megabytes (default: `1024` = 1GB)
- `PORT` (env): HTTP port (default: 8080)

## Systemd (optional)
Create `/etc/systemd/system/lan-uploader.service`:
```
[Unit]
Description=LAN Uploader (Flask)
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/lan-uploader
Environment=UPLOAD_ROOT=/var/mywebapp/uploads
Environment=PORT=8080
Environment=MAX_CONTENT_LENGTH_MB=2048
ExecStart=/opt/lan-uploader/.venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lan-uploader
```

## Notes
- Camera capture: `<input capture>` is enabled; some mobile browsers require `accept="image/*"` to auto‑open camera. This app sets `capture` and allows any file. If you want camera‑only, change `accept` to `image/*` or `video/*` in `templates/upload.html`.
- Security: No auth by default (LAN‑only). Consider adding a simple PIN header or HTTP Basic if you expose beyond your LAN.
- Path safety: All paths are resolved and enforced to be children of `UPLOAD_ROOT`.
- Extending: Add auth, file type filters, or a progress bar via `XMLHttpRequest` + progress events.

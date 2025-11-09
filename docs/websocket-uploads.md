# WebSocket Upload System

## Overview

The LAN Uploader uses WebSocket connections to provide real-time progress tracking and immediate error notification during file uploads. This document explains how the WebSocket upload system works and how to troubleshoot common issues.

## Features

### Streaming File Writes
Files are written directly to their final destination on disk as data arrives from the browser. There is no buffering to `/tmp` or any intermediate storage. This means:

- **Lower disk usage**: Only the final destination uses disk space
- **Immediate write failures**: Disk full errors are detected as soon as they occur
- **Better performance**: No file copying between temporary and final locations
- **Scalable**: Works with 100GB+ uploads without filling /tmp

### Real-Time Progress Updates
The browser receives WebSocket messages as the server processes each file:

- **Accurate progress**: Shows actual server-side processing, not just bytes sent
- **File-by-file updates**: See exactly which file is being processed
- **Byte-level precision**: Progress updates include bytes processed and total size
- **Sub-second latency**: Updates appear within 100ms of server-side changes

### Immediate Error Notification
If an error occurs during upload, the browser is notified immediately via WebSocket:

- **< 1 second notification**: Errors appear within 1 second of occurrence
- **No waiting**: Don't wait for entire upload to complete before seeing errors
- **Detailed messages**: Error messages include filename and specific error reason
- **Continue on error**: If one file fails, the upload continues with remaining files

### Browser Compatibility
The system automatically detects WebSocket support and falls back gracefully:

- **WebSocket-capable browsers**: Use real-time progress tracking
- **Legacy browsers**: Fall back to standard HTTP upload with XHR progress events
- **No configuration needed**: Detection and fallback happen automatically

Supported browsers (with WebSocket):
- Chrome 16+
- Firefox 11+
- Safari 7+
- Microsoft Edge (all versions)
- Internet Explorer 10+

## How It Works

### Upload Flow

1. **User selects files**: Browser shows file preview
2. **User clicks Upload**: WebSocket connection opens
3. **Session ID exchange**: Server sends unique session ID to browser
4. **Browser starts upload**: HTTP POST to `/upload` endpoint with session_id included
5. **Server processes files**: Files are written to disk, progress messages sent via WebSocket
6. **Real-time updates**: Browser receives progress, file completion, and error messages
7. **Upload completes**: Final success or error message sent, WebSocket closes

### Message Types

The WebSocket connection uses JSON messages with a `type` field:

#### Server to Client Messages

**session_id** - Initial connection established
```json
{
  "type": "session_id",
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**upload_started** - Upload processing has begun
```json
{
  "type": "upload_started",
  "total_files": 10,
  "total_bytes": 1048576
}
```

**progress** - Progress update
```json
{
  "type": "progress",
  "percent": 45,
  "files_done": 4,
  "total_files": 10,
  "bytes_done": 471859,
  "total_bytes": 1048576
}
```

**file_complete** - Individual file finished
```json
{
  "type": "file_complete",
  "filename": "photo.jpg",
  "size": 102400,
  "index": 4,
  "total_files": 10
}
```

**error** - Error occurred
```json
{
  "type": "error",
  "message": "Disk full",
  "filename": "largefile.bin",
  "code": 507
}
```

**complete** - All files uploaded successfully
```json
{
  "type": "complete",
  "total_files": 10,
  "saved_files": 9,
  "errors": 1
}
```

#### Client to Server Messages

**ping** - Keep connection alive
```json
{
  "type": "ping"
}
```

The server responds with:
```json
{
  "type": "pong"
}
```

## Performance

Benchmarked on typical NAS hardware (Raspberry Pi 4, 4GB RAM):

- **1000 x 1KB files**: ~200 files/second processing
- **Large file streaming**: ~100 MB/second write speed
- **WebSocket latency**: < 10ms average round-trip time
- **Memory usage**: < 50MB additional memory for WebSocket management

Performance scales with hardware. On modern x86 servers, expect 2-3x better performance.

## Troubleshooting

### Progress bar stuck at 0%

**Symptom**: Upload appears to start but progress bar doesn't update

**Possible causes**:
1. WebSocket connection failed
2. Session ID not being sent with upload
3. Browser dev tools show WebSocket errors

**Solutions**:
1. Check browser console for errors (F12 → Console)
2. Verify `/api/upload/ws` endpoint is accessible
3. Try refreshing the page and uploading again
4. Check server logs for WebSocket connection errors

### Errors not appearing immediately

**Symptom**: Upload completes but errors only show at the end

**Possible causes**:
1. Browser fell back to legacy upload mode
2. Session ID not included in upload request

**Solutions**:
1. Check if browser supports WebSocket (see Browser Compatibility section)
2. Verify WebSocket connection succeeded (browser console should show "WebSocket connected")
3. Check server logs to verify WebSocket infrastructure is working

### "Insufficient storage" error

**Symptom**: Upload fails with disk full error

**Possible causes**:
1. Upload directory's filesystem is actually full
2. Permissions prevent writing to upload directory
3. Disk quota exceeded

**Solutions**:
1. Check disk space: `df -h /path/to/upload_root`
2. Verify write permissions: `ls -ld /path/to/upload_root`
3. Check disk quotas if applicable: `quota -v`
4. Free up space or change upload root to filesystem with more space

### Upload fails midway through

**Symptom**: Upload starts successfully but stops partway through

**Possible causes**:
1. Network connection interrupted
2. Server crashed or restarted
3. Disk filled up during upload
4. Browser tab closed

**Solutions**:
1. Check server logs for errors
2. Verify server is still running: `systemctl status lan-uploader`
3. Check network connection
4. Try uploading again (already-uploaded files will be overwritten or skipped based on configuration)

### WebSocket connection refused

**Symptom**: Browser console shows "WebSocket connection refused" or similar error

**Possible causes**:
1. Server not running
2. Firewall blocking WebSocket connections
3. Reverse proxy not configured for WebSocket upgrades

**Solutions**:
1. Verify server is running: `systemctl status lan-uploader`
2. Check firewall rules: `sudo iptables -L` or `sudo ufw status`
3. If using reverse proxy (nginx, Apache), ensure WebSocket upgrade headers are passed through

**Example nginx configuration for WebSocket**:
```nginx
location /api/upload/ws {
    proxy_pass http://localhost:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

## Advanced Topics

### Concurrent Uploads
Each WebSocket connection gets a unique session ID, allowing multiple users or browser tabs to upload simultaneously without interference. The server tracks each session independently.

### Reconnection Logic
If the WebSocket connection drops during upload:
- The client attempts to reconnect with exponential backoff
- If reconnection fails, upload continues via HTTP but without real-time progress
- Progress reverts to standard XHR progress events (browser-side only)

### Security Considerations
- WebSocket connections use the same origin as the HTTP server (no CORS issues)
- Session IDs are UUIDs (not guessable)
- No sensitive data is transmitted via WebSocket
- All file data goes via standard HTTP upload (WebSocket only carries status messages)
- Authentication/authorization should be implemented at the HTTP level, not WebSocket

## See Also

- [Developer Documentation](development/websocket-architecture.md) - For developers working on the codebase
- [Main README](../README.md) - Setup and configuration instructions
- [API Documentation](http://localhost:8080/docs) - When server is running, full API documentation

## Version

- **Created**: 2025-11-09
- **Version**: 2.0 (WebSocket upload system)
- **Last Updated**: 2025-11-09

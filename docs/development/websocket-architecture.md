# WebSocket Architecture

## Overview

This document describes the technical architecture of the WebSocket upload system for developers working on the LAN Uploader codebase.

## Components

### Backend Components

#### UploadSessionManager (`app.py`)
Manages WebSocket connections and tracks upload sessions.

**Key responsibilities**:
- Generate unique session IDs
- Register and track WebSocket connections
- Send progress/error/completion messages to clients
- Clean up completed sessions
- Handle concurrent sessions

**Key methods**:
- `register_connection(session_id, websocket)` - Associate WebSocket with session ID
- `unregister_connection(session_id)` - Remove WebSocket connection
- `start_upload(session_id, total_files, total_bytes)` - Notify client upload started
- `update_progress(session_id, ...)` - Send progress update
- `file_completed(session_id, filename, size, ...)` - Notify file completion
- `upload_error(session_id, message, ...)` - Send error message
- `upload_complete(session_id, ...)` - Send completion message
- `cleanup_session(session_id)` - Remove session from tracking

**Data structures**:
```python
class UploadSession:
    status: UploadStatus  # PENDING, IN_PROGRESS, COMPLETED, ERROR, CANCELLED
    websocket: Optional[WebSocket]
    total_files: int
    files_done: int
    total_bytes: int
    bytes_done: int
    errors: List[Dict[str, Any]]
```

#### WebSocket Endpoint (`/api/upload/ws`)
FastAPI WebSocket endpoint that handles client connections.

**Responsibilities**:
- Accept WebSocket connections
- Generate and send session ID
- Handle ping/pong keep-alive messages
- Manage connection lifecycle
- Clean up on disconnect

**Flow**:
1. Client connects to `/api/upload/ws`
2. Server generates UUID session ID
3. Server sends `session_id` message
4. Server registers connection in UploadSessionManager
5. Server starts ping interval (30 seconds)
6. On disconnect, server unregisters connection and cleans up

#### Upload Endpoint (`/upload`)
Modified to accept `session_id` parameter and send WebSocket messages.

**Key changes**:
- Accepts optional `session_id` form parameter
- Looks up WebSocket connection via UploadSessionManager
- Sends `upload_started`, `progress`, `file_complete`, `error`, and `complete` messages
- Maintains backwards compatibility (works without session_id)

**Streaming implementation**:
```python
async def save_upload_file(upload_file: UploadFile, destination: Path):
    """Stream file directly to destination."""
    async with aiofiles.open(destination, 'wb') as f:
        while chunk := await upload_file.read(8192):  # 8KB chunks
            await f.write(chunk)
```

### Frontend Components

#### UploadWebSocketClient (`static/js/websocket-client.js`)
JavaScript class that manages WebSocket connection.

**Key responsibilities**:
- Connect to WebSocket endpoint
- Receive and cache session ID
- Register event handlers for message types
- Handle reconnection with exponential backoff
- Implement ping/pong keep-alive
- Clean up resources on close

**Key methods**:
- `connect()` - Establish WebSocket connection
- `reconnect()` - Reconnect with exponential backoff
- `on(type, handler)` - Register message handler
- `off(type, handler)` - Unregister message handler
- `close()` - Close connection and clean up
- `isSupported()` - Static method to check browser support

**Features**:
- Automatic reconnection with exponential backoff
- 30-second ping interval to keep connection alive
- Promise-based connection API
- Event-driven message handling
- Resource cleanup (ping interval, WebSocket)

#### App Integration (`static/js/app.js`)
Modified to use WebSocket client for real-time progress.

**Key changes**:
- Create `UploadWebSocketClient` instance
- Connect and retrieve session ID before upload
- Include session ID in FormData
- Register handlers for all message types:
  - `upload_started` - Show progress container
  - `progress` - Update progress bar and text
  - `file_complete` - Log file completion
  - `error` - Display error immediately
  - `complete` - Hide modal, show success
- Implement legacy fallback for browsers without WebSocket
- Clean up WebSocket on upload completion/error

**Legacy fallback**:
If WebSocket is not supported or connection fails, the app falls back to `performUploadLegacy()` which uses standard XHR with progress events.

## Session Lifecycle

### Normal Upload Flow

1. **Connection**: Client connects to `/api/upload/ws`
2. **Session Creation**: Server generates UUID and sends `session_id` message
3. **Registration**: Server registers WebSocket in `UploadSessionManager`
4. **Upload Start**: Client includes session_id in `/upload` request
5. **Processing**: Server processes files and sends WebSocket messages:
   - `upload_started` (total files, total bytes)
   - `progress` (percent, files done, bytes done) - sent periodically
   - `file_complete` (per file) - sent after each file
   - `complete` (final summary)
6. **Cleanup**: Server removes session from UploadSessionManager
7. **Disconnect**: Client closes WebSocket connection

### Error Flow

If error occurs during upload:

1. Server detects error (disk full, invalid filename, permission denied, etc.)
2. Server sends `error` message via WebSocket immediately
3. Server continues processing remaining files (unless fatal error)
4. Server sends `complete` message with error count
5. Client displays error, cleans up WebSocket

### Connection Loss Flow

If WebSocket connection drops during upload:

1. Client detects disconnect event
2. Client attempts to reconnect with exponential backoff
3. **If reconnect succeeds**: Upload continues, messages resume
4. **If reconnect fails**: Upload completes via HTTP, no real-time progress

Note: File upload itself uses HTTP, so loss of WebSocket doesn't abort upload.

## Message Protocol

All messages are JSON objects with a `type` field.

### Server → Client Messages

| Type | Fields | Description |
|------|--------|-------------|
| `session_id` | `id: string` | Session ID for this connection |
| `upload_started` | `total_files: int, total_bytes: int` | Upload processing started |
| `progress` | `percent: int, files_done: int, total_files: int, bytes_done: int, total_bytes: int` | Progress update |
| `file_complete` | `filename: string, size: int, index: int, total_files: int` | File completed |
| `error` | `message: string, filename?: string, code?: int` | Error occurred |
| `complete` | `total_files: int, saved_files: int, errors: int` | Upload complete |
| `pong` | *(none)* | Response to ping |

### Client → Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `ping` | *(none)* | Keep-alive ping |
| `cancel` | *(none)* | Cancel upload *(not yet implemented)* |

## Testing

### Backend Tests

**File**: `tests/test_websocket.py`
- Unit tests for `UploadSessionManager`
- Tests for session lifecycle
- Tests for message sending
- Tests for cleanup

**File**: `tests/test_backend_integration.py`
- Integration tests with mock WebSocket
- Tests for upload with session_id
- Tests for error propagation
- Tests for backwards compatibility

### Frontend Tests

**File**: `tests/test_e2e.py`
- End-to-end tests with Playwright
- Tests for real browser WebSocket usage
- Tests for progress display
- Tests for error display
- Tests for fallback to legacy mode

### Running Tests

```bash
# All tests
pytest

# WebSocket tests only
pytest tests/test_websocket.py tests/test_backend_integration.py

# E2E tests only (requires Playwright)
pytest tests/test_e2e.py

# With coverage
pytest --cov=. --cov-report=term-missing
```

## Design Decisions

### Why WebSocket over Server-Sent Events (SSE)?

**WebSocket chosen because**:
- Bidirectional communication (future: cancel, pause/resume)
- Better browser support for our target (Chrome 16+, Firefox 11+)
- Lower latency for message delivery
- Can send ping/pong for connection health

**SSE considered but rejected**:
- One-way communication (server → client only)
- Would require separate endpoint for client commands
- More complex fallback strategy

### Why UUID session IDs?

**UUID v4 chosen because**:
- Cryptographically random (not guessable)
- No collision risk with concurrent sessions
- No central coordination needed
- Standard format, widely supported

### Why separate WebSocket and HTTP for upload?

**HTTP for file data, WebSocket for status chosen because**:
- HTTP better suited for large payloads
- Browsers have optimized HTTP upload path
- WebSocket frames have size limits
- Separation of concerns (data vs. status)
- Easier to implement streaming writes with HTTP

**Alternative considered**: WebSocket for both data and status
- **Rejected**: More complex, worse performance, no real benefit

### Why 8KB chunk size for streaming?

**8KB chosen because**:
- Balance between memory usage and system call overhead
- Standard filesystem block size (4KB-8KB)
- Small enough for real-time progress updates
- Large enough for efficient disk writes

## Future Enhancements

### Planned Features
- **Upload pause/resume**: Pause long uploads and resume later
- **Upload cancellation**: Cancel in-progress uploads via WebSocket message
- **Bandwidth throttling**: Limit upload speed to avoid saturating network
- **Chunked upload protocol**: Resume uploads after connection loss
- **Multiple concurrent uploads**: Queue management for multiple simultaneous uploads

### API Stability
The current message protocol is stable and should remain backwards-compatible. Any future enhancements should:
- Add new message types (don't modify existing ones)
- Add new optional fields to existing messages
- Maintain support for uploads without session_id (legacy mode)

### Performance Optimization Opportunities
- **Connection pooling**: Reuse WebSocket connections for multiple uploads
- **Message batching**: Batch progress updates to reduce overhead
- **Compression**: Enable WebSocket compression for lower bandwidth
- **Database indexing**: Move from filesystem scanning to database queries

## Code Organization

```
app.py                          # Main application
├── UploadSessionManager        # WebSocket session management
├── /api/upload/ws              # WebSocket endpoint
├── /upload                     # File upload endpoint (modified)
└── /api/upload/status          # Session status query endpoint

static/js/
├── websocket-client.js         # WebSocket client class
└── app.js                      # Upload UI (modified)

tests/
├── test_websocket.py           # WebSocket unit tests
├── test_backend_integration.py # Backend integration tests
└── test_e2e.py                 # End-to-end browser tests
```

## Debugging Tips

### Enable verbose logging

Set environment variable before starting server:
```bash
export LOG_LEVEL=DEBUG
python app.py
```

### Monitor WebSocket messages in browser

Open browser DevTools (F12):
1. Go to Network tab
2. Filter by "WS" (WebSocket)
3. Click on the WebSocket connection
4. View Messages tab to see all messages

### Inspect session state

Access the status endpoint:
```bash
curl http://localhost:8080/api/upload/status/<session-id>
```

Returns:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "IN_PROGRESS",
  "total_files": 10,
  "files_done": 4,
  "progress": 40
}
```

### Common issues

**"WebSocket connection closed immediately"**
- Check server logs for exceptions
- Verify `/api/upload/ws` endpoint is accessible
- Check firewall/proxy configuration

**"Progress stuck at 0%"**
- Verify session_id is included in upload request
- Check browser console for WebSocket messages
- Verify WebSocket connection is established

**"Messages not reaching client"**
- Check `upload_manager.sessions` dictionary in debugger
- Verify session_id matches between upload and WebSocket
- Check for exceptions in message sending code

## See Also

- [User Documentation](../websocket-uploads.md) - User-facing documentation
- [Main README](../../README.md) - Setup and configuration
- [Tests](../../tests/) - Test files for reference examples

## Version

- **Created**: 2025-11-09
- **Version**: 2.0 (WebSocket upload system)
- **Last Updated**: 2025-11-09

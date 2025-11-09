"""
Unit tests for WebSocket infrastructure.

Tests for:
- WebSocket connection and session management
- UploadSessionManager functionality
- Message protocol
- Session lifecycle
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime


class MockWebSocket:
    """Mock WebSocket for testing without real connections."""

    def __init__(self):
        """Initialize mock WebSocket with message tracking."""
        self.sent_messages = []
        self.closed = False

    async def send_json(self, data):
        """Mock send_json to track messages."""
        self.sent_messages.append(data)

    async def receive_text(self):
        """Mock receive_text."""
        return '{"type":"ping"}'

    async def receive_json(self):
        """Mock receive_json."""
        return {"type": "ping"}


class TestUploadStatus:
    """Test UploadStatus enum."""

    def test_upload_status_values(self):
        """Test that all expected status values exist."""
        from app import UploadStatus

        assert UploadStatus.PENDING.value == "pending"
        assert UploadStatus.IN_PROGRESS.value == "in_progress"
        assert UploadStatus.COMPLETED.value == "completed"
        assert UploadStatus.FAILED.value == "failed"
        assert UploadStatus.CANCELLED.value == "cancelled"

    def test_upload_status_count(self):
        """Test that exactly 5 status states exist."""
        from app import UploadStatus

        assert len(list(UploadStatus)) == 5


class TestUploadSession:
    """Test UploadSession dataclass."""

    def test_upload_session_creation(self):
        """Test creating an upload session with default values."""
        from app import UploadSession, UploadStatus

        session = UploadSession(id="test-session-1")

        assert session.id == "test-session-1"
        assert session.status == UploadStatus.PENDING
        assert session.total_files == 0
        assert session.files_completed == 0
        assert session.total_bytes == 0
        assert session.bytes_written == 0
        assert session.files_saved == []
        assert session.errors == []
        assert session.started_at is None
        assert session.completed_at is None
        assert session.error_message is None

    def test_upload_session_with_values(self):
        """Test creating an upload session with specific values."""
        from app import UploadSession, UploadStatus

        started = datetime.now()
        session = UploadSession(
            id="test-session-2",
            status=UploadStatus.IN_PROGRESS,
            total_files=10,
            files_completed=5,
            total_bytes=10240,
            bytes_written=5120,
            started_at=started
        )

        assert session.id == "test-session-2"
        assert session.status == UploadStatus.IN_PROGRESS
        assert session.total_files == 10
        assert session.files_completed == 5
        assert session.total_bytes == 10240
        assert session.bytes_written == 5120
        assert session.started_at == started

    def test_upload_session_mutable_defaults(self):
        """Test that mutable defaults (lists) are independent."""
        from app import UploadSession

        session1 = UploadSession(id="session-1")
        session2 = UploadSession(id="session-2")

        session1.files_saved.append({"name": "file1.txt"})
        session1.errors.append({"error": "test error"})

        # session2 should not be affected
        assert len(session2.files_saved) == 0
        assert len(session2.errors) == 0


class TestUploadSessionManager:
    """Test UploadSessionManager class."""

    def test_manager_initialization(self):
        """Test that manager initializes correctly."""
        from app import UploadSessionManager

        manager = UploadSessionManager()

        assert manager.sessions == {}
        assert manager.connections == {}
        assert manager._lock is not None

    def test_register_connection(self):
        """Test registering a WebSocket connection."""
        from app import UploadSessionManager, UploadStatus

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)

        assert session_id in manager.sessions
        assert session_id in manager.connections
        assert manager.connections[session_id] == mock_ws
        assert manager.sessions[session_id].id == session_id
        assert manager.sessions[session_id].status == UploadStatus.PENDING

    def test_unregister_connection(self):
        """Test unregistering a WebSocket connection."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        manager.unregister_connection(session_id)

        # Connection should be removed immediately
        assert session_id not in manager.connections
        # Session should still exist (cleanup happens later)
        assert session_id in manager.sessions

    def test_get_session_exists(self):
        """Test getting an existing session."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        session = manager.get_session(session_id)

        assert session is not None
        assert session.id == session_id

    def test_get_session_not_exists(self):
        """Test getting a non-existent session."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        session = manager.get_session("non-existent-session")

        assert session is None

    @pytest.mark.asyncio
    async def test_start_upload(self):
        """Test starting an upload session."""
        from app import UploadSessionManager, UploadStatus

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=10, total_bytes=10240)

        session = manager.get_session(session_id)
        assert session.status == UploadStatus.IN_PROGRESS
        assert session.total_files == 10
        assert session.total_bytes == 10240
        assert session.started_at is not None

        # Check message was sent
        assert len(mock_ws.sent_messages) == 1
        message = mock_ws.sent_messages[0]
        assert message['type'] == 'upload_started'
        assert message['total_files'] == 10
        assert message['total_bytes'] == 10240

    @pytest.mark.asyncio
    async def test_update_progress(self):
        """Test updating upload progress."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=10)
        await manager.update_progress(session_id, files_completed=5, bytes_written=5120)

        session = manager.get_session(session_id)
        assert session.files_completed == 5
        assert session.bytes_written == 5120

        # Check progress message was sent
        progress_msg = mock_ws.sent_messages[-1]
        assert progress_msg['type'] == 'progress'
        assert progress_msg['percent'] == 50  # 5/10 = 50%
        assert progress_msg['files_done'] == 5
        assert progress_msg['total_files'] == 10
        assert progress_msg['bytes_written'] == 5120

    @pytest.mark.asyncio
    async def test_update_progress_zero_files(self):
        """Test progress calculation when total_files is 0."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=0)
        await manager.update_progress(session_id, files_completed=0, bytes_written=0)

        # Check that percent is 0 (not division by zero)
        progress_msg = mock_ws.sent_messages[-1]
        assert progress_msg['percent'] == 0

    @pytest.mark.asyncio
    async def test_update_progress_nonexistent_session(self):
        """Test updating progress for non-existent session (should not crash)."""
        from app import UploadSessionManager

        manager = UploadSessionManager()

        # This should not raise an exception
        await manager.update_progress("non-existent", files_completed=5, bytes_written=100)

    @pytest.mark.asyncio
    async def test_file_completed(self):
        """Test marking a file as completed."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=10)
        await manager.file_completed(
            session_id,
            filename="test.txt",
            size=1024,
            path="uploads/test.txt"
        )

        session = manager.get_session(session_id)
        assert len(session.files_saved) == 1
        assert session.files_saved[0]['name'] == "test.txt"
        assert session.files_saved[0]['size'] == 1024
        assert session.files_saved[0]['path'] == "uploads/test.txt"

        # Check message was sent
        file_msg = mock_ws.sent_messages[-1]
        assert file_msg['type'] == 'file_complete'
        assert file_msg['filename'] == "test.txt"
        assert file_msg['size'] == 1024
        assert file_msg['path'] == "uploads/test.txt"

    @pytest.mark.asyncio
    async def test_upload_error(self):
        """Test reporting an upload error."""
        from app import UploadSessionManager, UploadStatus

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=10)
        await manager.upload_error(
            session_id,
            error_message="Disk full",
            error_code=507,
            filename="large.mp4"
        )

        session = manager.get_session(session_id)
        assert session.status == UploadStatus.FAILED
        assert session.error_message == "Disk full"
        assert session.completed_at is not None
        assert len(session.errors) == 1
        assert session.errors[0]['file'] == "large.mp4"
        assert session.errors[0]['error'] == "Disk full"
        assert session.errors[0]['code'] == 507

        # Check error message was sent
        error_msg = mock_ws.sent_messages[-1]
        assert error_msg['type'] == 'error'
        assert error_msg['message'] == "Disk full"
        assert error_msg['code'] == 507
        assert error_msg['filename'] == "large.mp4"

    @pytest.mark.asyncio
    async def test_upload_error_no_filename(self):
        """Test reporting an error without a specific filename."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=10)
        await manager.upload_error(
            session_id,
            error_message="Network error",
            error_code=500
        )

        # Check error message
        error_msg = mock_ws.sent_messages[-1]
        assert error_msg['filename'] is None

    @pytest.mark.asyncio
    async def test_upload_complete(self):
        """Test marking upload as complete."""
        from app import UploadSessionManager, UploadStatus

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=3)

        # Complete some files
        await manager.file_completed(session_id, "file1.txt", 100, "uploads/file1.txt")
        await manager.file_completed(session_id, "file2.txt", 200, "uploads/file2.txt")
        await manager.update_progress(session_id, 2, 300)

        # Mark as complete
        await manager.upload_complete(session_id)

        session = manager.get_session(session_id)
        assert session.status == UploadStatus.COMPLETED
        assert session.completed_at is not None

        # Check complete message
        complete_msg = mock_ws.sent_messages[-1]
        assert complete_msg['type'] == 'complete'
        assert complete_msg['total_files'] == 2
        assert complete_msg['total_bytes'] == 300
        assert len(complete_msg['files_saved']) == 2
        assert len(complete_msg['errors']) == 0

    @pytest.mark.asyncio
    async def test_upload_complete_nonexistent_session(self):
        """Test completing a non-existent session (should not crash)."""
        from app import UploadSessionManager

        manager = UploadSessionManager()

        # This should not raise an exception
        await manager.upload_complete("non-existent")

    @pytest.mark.asyncio
    async def test_cancel_upload(self):
        """Test cancelling an upload."""
        from app import UploadSessionManager, UploadStatus

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=10)
        await manager.cancel_upload(session_id)

        session = manager.get_session(session_id)
        assert session.status == UploadStatus.CANCELLED
        assert session.completed_at is not None

        # Check cancelled message
        cancel_msg = mock_ws.sent_messages[-1]
        assert cancel_msg['type'] == 'cancelled'

    @pytest.mark.asyncio
    async def test_send_message_connection_exists(self):
        """Test sending a message to an active connection."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.send_message(session_id, {"type": "test", "data": "hello"})

        assert len(mock_ws.sent_messages) == 1
        assert mock_ws.sent_messages[0]['type'] == 'test'
        assert mock_ws.sent_messages[0]['data'] == 'hello'

    @pytest.mark.asyncio
    async def test_send_message_no_connection(self):
        """Test sending a message when connection doesn't exist (should not crash)."""
        from app import UploadSessionManager

        manager = UploadSessionManager()

        # This should not raise an exception
        await manager.send_message("non-existent", {"type": "test"})

    @pytest.mark.asyncio
    async def test_send_message_handles_exception(self):
        """Test that send_message handles WebSocket exceptions gracefully."""
        from app import UploadSessionManager, UploadSession

        manager = UploadSessionManager()

        # Create a mock WebSocket that raises an exception
        mock_ws = MagicMock()
        mock_ws.send_json = AsyncMock(side_effect=Exception("Connection closed"))

        session_id = "test-session-1"
        manager.connections[session_id] = mock_ws
        manager.sessions[session_id] = UploadSession(id=session_id)

        # This should not raise an exception
        await manager.send_message(session_id, {"type": "test"})

    @pytest.mark.asyncio
    async def test_cleanup_session_completed(self):
        """Test that cleanup removes completed sessions after delay."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=1)
        await manager.upload_complete(session_id)

        # Manually call cleanup with 0 delay for testing
        await manager._cleanup_session(session_id, delay=0)

        # Session should be removed
        assert session_id not in manager.sessions

    @pytest.mark.asyncio
    async def test_cleanup_session_in_progress(self):
        """Test that cleanup does not remove in-progress sessions."""
        from app import UploadSessionManager

        manager = UploadSessionManager()
        mock_ws = MockWebSocket()
        session_id = "test-session-1"

        manager.register_connection(session_id, mock_ws)
        await manager.start_upload(session_id, total_files=1)

        # Manually call cleanup with 0 delay for testing
        await manager._cleanup_session(session_id, delay=0)

        # Session should NOT be removed (still in progress)
        assert session_id in manager.sessions

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sessions(self):
        """Test handling multiple concurrent upload sessions."""
        from app import UploadSessionManager, UploadStatus

        manager = UploadSessionManager()

        sessions = []
        for i in range(5):
            session_id = f"session-{i}"
            mock_ws = MockWebSocket()
            manager.register_connection(session_id, mock_ws)
            await manager.start_upload(session_id, total_files=10)
            sessions.append(session_id)

        # All sessions should exist
        assert len(manager.sessions) == 5
        assert len(manager.connections) == 5

        # Each session should be independent
        for i, session_id in enumerate(sessions):
            session = manager.get_session(session_id)
            assert session.status == UploadStatus.IN_PROGRESS
            assert session.total_files == 10


class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality."""

    def test_websocket_endpoint_exists(self):
        """Test that WebSocket endpoint is registered."""
        from app import app

        routes = [r.path for r in app.routes]
        assert '/api/upload/ws' in routes

    def test_status_endpoint_exists(self):
        """Test that status polling endpoint is registered."""
        from app import app

        routes = [r.path for r in app.routes]
        assert '/api/upload/status/{session_id}' in routes

    def test_websocket_connect(self, client):
        """Test WebSocket connection and session ID assignment."""
        with client.websocket_connect("/api/upload/ws") as websocket:
            # Should receive session_id message
            data = websocket.receive_json()

            assert data['type'] == 'session_id'
            assert 'id' in data
            assert len(data['id']) == 36  # UUID length with hyphens

    def test_websocket_ping_pong(self, client):
        """Test ping/pong keepalive."""
        with client.websocket_connect("/api/upload/ws") as websocket:
            # Get session ID
            session_data = websocket.receive_json()
            assert session_data['type'] == 'session_id'

            # Send ping
            websocket.send_json({"type": "ping"})

            # Receive pong
            pong = websocket.receive_json()
            assert pong['type'] == 'pong'

    def test_multiple_websocket_connections(self, client):
        """Test multiple concurrent WebSocket connections."""
        # Open multiple connections
        with client.websocket_connect("/api/upload/ws") as ws1:
            with client.websocket_connect("/api/upload/ws") as ws2:
                with client.websocket_connect("/api/upload/ws") as ws3:
                    # Get session IDs
                    session1 = ws1.receive_json()
                    session2 = ws2.receive_json()
                    session3 = ws3.receive_json()

                    # All should be unique
                    ids = {session1['id'], session2['id'], session3['id']}
                    assert len(ids) == 3

    def test_status_endpoint_session_not_found(self, client):
        """Test status endpoint returns 404 for non-existent session."""
        response = client.get("/api/upload/status/non-existent-session")

        assert response.status_code == 404
        assert response.json()['detail'] == "Session not found"

    @pytest.mark.asyncio
    async def test_status_endpoint_returns_session_data(self, client):
        """Test status endpoint returns correct session data."""
        from app import upload_manager

        # Create a session manually
        session_id = "test-status-session"
        mock_ws = MockWebSocket()
        upload_manager.register_connection(session_id, mock_ws)
        await upload_manager.start_upload(session_id, total_files=10, total_bytes=10240)
        await upload_manager.update_progress(session_id, files_completed=5, bytes_written=5120)

        # Query status endpoint
        response = client.get(f"/api/upload/status/{session_id}")

        assert response.status_code == 200
        data = response.json()
        assert data['session_id'] == session_id
        assert data['status'] == 'in_progress'
        assert data['total_files'] == 10
        assert data['files_completed'] == 5
        assert data['total_bytes'] == 10240
        assert data['bytes_written'] == 5120
        assert data['percent'] == 50

        # Cleanup
        upload_manager.unregister_connection(session_id)

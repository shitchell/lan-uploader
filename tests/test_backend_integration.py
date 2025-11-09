"""
Integration tests for backend WebSocket integration.

Tests the upload endpoint integrated with WebSocket infrastructure to verify:
- Real-time progress updates during upload
- Error propagation via WebSocket
- Backwards compatibility (upload without session_id)
- File-level error handling
- Disk space error handling
"""

import pytest
from unittest.mock import patch


class MockWebSocket:
    """Mock WebSocket for testing message propagation."""

    def __init__(self):
        self.sent_messages = []

    async def send_json(self, data):
        self.sent_messages.append(data)


class TestUploadWebSocketIntegration:
    """Test upload endpoint integrated with WebSocket progress updates."""

    def test_upload_with_session_sends_all_messages(self, client):
        """Test that upload with session_id sends all expected WebSocket messages."""
        import app

        # Create session and register mock WebSocket
        session_id = "test-session-123"
        mock_ws = MockWebSocket()
        app.upload_manager.register_connection(session_id, mock_ws)

        try:
            # Upload files with session_id
            files = [
                ("files", ("file1.txt", b"Content of file 1", "text/plain")),
                ("files", ("file2.txt", b"Content of file 2", "text/plain")),
            ]
            data = {"target_dir": "", "session_id": session_id}

            response = client.post("/upload", files=files, data=data)

            # Verify upload succeeded
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["ok"] is True
            assert len(response_data["saved"]) == 2

            # Verify WebSocket messages
            messages = mock_ws.sent_messages
            message_types = [msg["type"] for msg in messages]

            # Should have: upload_started, file_complete (x2), progress (x2), complete
            assert "upload_started" in message_types
            assert message_types.count("file_complete") == 2
            assert message_types.count("progress") >= 2
            assert "complete" in message_types

            # Verify upload_started message
            started_msg = next(msg for msg in messages if msg["type"] == "upload_started")
            assert started_msg["total_files"] == 2
            assert started_msg["total_bytes"] > 0

            # Verify file_complete messages
            file_complete_msgs = [msg for msg in messages if msg["type"] == "file_complete"]
            assert len(file_complete_msgs) == 2
            filenames = {msg["filename"] for msg in file_complete_msgs}
            assert filenames == {"file1.txt", "file2.txt"}

            # Verify progress messages
            progress_msgs = [msg for msg in messages if msg["type"] == "progress"]
            assert len(progress_msgs) >= 2
            # Last progress should be 100%
            last_progress = progress_msgs[-1]
            assert last_progress["percent"] == 100
            assert last_progress["files_done"] == 2

            # Verify complete message
            complete_msg = next(msg for msg in messages if msg["type"] == "complete")
            assert complete_msg["total_files"] == 2
            assert len(complete_msg["files_saved"]) == 2

        finally:
            # Cleanup
            app.upload_manager.unregister_connection(session_id)

    def test_upload_sends_progress_updates(self, client):
        """Test that progress updates are sent with correct percentages."""
        import app

        session_id = "test-session-progress"
        mock_ws = MockWebSocket()
        app.upload_manager.register_connection(session_id, mock_ws)

        try:
            # Upload 3 files
            files = [
                ("files", ("a.txt", b"A", "text/plain")),
                ("files", ("b.txt", b"B", "text/plain")),
                ("files", ("c.txt", b"C", "text/plain")),
            ]
            data = {"target_dir": "", "session_id": session_id}

            response = client.post("/upload", files=files, data=data)
            assert response.status_code == 200

            # Get progress messages
            messages = mock_ws.sent_messages
            progress_msgs = [msg for msg in messages if msg["type"] == "progress"]
            assert len(progress_msgs) == 3

            # Check progress percentages
            percentages = [msg["percent"] for msg in progress_msgs]
            assert percentages[0] == 33  # 1/3
            assert percentages[1] == 66  # 2/3
            assert percentages[2] == 100  # 3/3

        finally:
            app.upload_manager.unregister_connection(session_id)


class TestUploadErrorHandling:
    """Test error handling with WebSocket integration."""

    def test_invalid_filename_sends_error(self, client):
        """Test that invalid filename sends error via WebSocket."""
        import app

        session_id = "test-session-invalid"
        mock_ws = MockWebSocket()
        app.upload_manager.register_connection(session_id, mock_ws)

        try:
            # Upload file with invalid filename
            files = [
                ("files", ("..", b"Hack attempt", "text/plain")),
            ]
            data = {"target_dir": "", "session_id": session_id}

            response = client.post("/upload", files=files, data=data)
            assert response.status_code == 200  # Upload endpoint returns 200 even with errors

            # Should have error message
            messages = mock_ws.sent_messages
            error_msgs = [msg for msg in messages if msg["type"] == "error"]
            assert len(error_msgs) >= 1
            error = error_msgs[0]
            assert error["code"] == 400
            assert "Invalid filename" in error["message"]
            assert error["filename"] == ".."

        finally:
            app.upload_manager.unregister_connection(session_id)

    def test_file_exists_sends_error(self, client, temp_upload_dir):
        """Test that file exists error sends error via WebSocket."""
        import app

        # Create existing file
        existing = temp_upload_dir / "exists.txt"
        existing.write_text("Already here")

        session_id = "test-session-exists"
        mock_ws = MockWebSocket()
        app.upload_manager.register_connection(session_id, mock_ws)

        try:
            # Try to upload file with same name
            files = [
                ("files", ("exists.txt", b"New content", "text/plain")),
            ]
            data = {"target_dir": "", "session_id": session_id}

            response = client.post("/upload", files=files, data=data)
            assert response.status_code == 200

            # Should have error message
            messages = mock_ws.sent_messages
            error_msgs = [msg for msg in messages if msg["type"] == "error"]
            assert len(error_msgs) >= 1
            error = error_msgs[0]
            assert error["code"] == 409
            assert "already exists" in error["message"].lower()
            assert error["filename"] == "exists.txt"

        finally:
            app.upload_manager.unregister_connection(session_id)

    def test_disk_full_error_sent_via_websocket(self, client, monkeypatch):
        """Test that disk full error is immediately sent via WebSocket."""
        import app

        session_id = "test-session-diskfull"
        mock_ws = MockWebSocket()
        app.upload_manager.register_connection(session_id, mock_ws)

        try:
            # Mock check_disk_space to return insufficient space
            def mock_check_disk_space(path):
                return (1024 * 1024, 512 * 1024, 100)  # 100 bytes available

            monkeypatch.setattr("app.check_disk_space", mock_check_disk_space)

            # Try to upload large file
            files = [
                ("files", ("large.bin", b"x" * 1024, "application/octet-stream")),
            ]
            data = {"target_dir": "", "session_id": session_id}

            response = client.post("/upload", files=files, data=data)

            # Verify error message received via WebSocket
            messages = mock_ws.sent_messages
            error_msgs = [msg for msg in messages if msg["type"] == "error"]
            assert len(error_msgs) >= 1
            assert any(msg["code"] == 507 for msg in error_msgs)
            assert any("storage" in msg["message"].lower() for msg in error_msgs)

            # Verify HTTP response also indicates error
            assert response.status_code == 507

        finally:
            app.upload_manager.unregister_connection(session_id)

    def test_file_error_continues_upload(self, client, temp_upload_dir):
        """Test that error on one file doesn't stop upload of other files."""
        import app

        # Create one existing file
        existing = temp_upload_dir / "exists.txt"
        existing.write_text("Already here")

        session_id = "test-session-continue"
        mock_ws = MockWebSocket()
        app.upload_manager.register_connection(session_id, mock_ws)

        try:
            # Upload mix of valid and invalid files
            files = [
                ("files", ("valid1.txt", b"Content 1", "text/plain")),
                ("files", ("exists.txt", b"Should fail", "text/plain")),
                ("files", ("valid2.txt", b"Content 2", "text/plain")),
            ]
            data = {"target_dir": "", "session_id": session_id}

            response = client.post("/upload", files=files, data=data)
            assert response.status_code == 200

            # Should have 2 successes and 1 error
            messages = mock_ws.sent_messages
            file_complete_msgs = [msg for msg in messages if msg["type"] == "file_complete"]
            error_msgs = [msg for msg in messages if msg["type"] == "error"]

            assert len(file_complete_msgs) == 2
            assert len(error_msgs) >= 1

            # Verify correct files were uploaded
            uploaded_filenames = {msg["filename"] for msg in file_complete_msgs}
            assert uploaded_filenames == {"valid1.txt", "valid2.txt"}

            # Verify error was for correct file
            assert any(msg["filename"] == "exists.txt" for msg in error_msgs)

            # Verify complete message was sent
            complete_msgs = [msg for msg in messages if msg["type"] == "complete"]
            assert len(complete_msgs) == 1

            # Verify HTTP response shows partial success
            response_data = response.json()
            assert len(response_data["saved"]) == 2
            assert len(response_data["errors"]) == 1

        finally:
            app.upload_manager.unregister_connection(session_id)


class TestBackwardsCompatibility:
    """Test backwards compatibility - upload without session_id."""

    def test_upload_without_session_works(self, client):
        """Test upload still works without session_id (legacy mode)."""
        files = [
            ("files", ("test1.txt", b"Hello 1", "text/plain")),
            ("files", ("test2.txt", b"Hello 2", "text/plain")),
        ]
        # No session_id provided
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 2
        assert data["saved"][0]["filename"] == "test1.txt"
        assert data["saved"][1]["filename"] == "test2.txt"

    def test_upload_without_session_handles_errors(self, client, temp_upload_dir):
        """Test error handling works without session_id."""
        # Create existing file
        existing = temp_upload_dir / "exists.txt"
        existing.write_text("Already here")

        files = [
            ("files", ("valid.txt", b"Valid content", "text/plain")),
            ("files", ("exists.txt", b"Should fail", "text/plain")),
        ]
        # No session_id
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 1
        assert len(data["errors"]) == 1
        assert data["saved"][0]["filename"] == "valid.txt"
        assert data["errors"][0]["file"] == "exists.txt"

    def test_upload_with_invalid_session_id(self, client):
        """Test upload with non-existent session_id doesn't crash."""
        files = [
            ("files", ("test.txt", b"Content", "text/plain")),
        ]
        # Invalid session_id
        data = {"target_dir": "", "session_id": "non-existent-session-123"}

        # Should not crash - upload_manager methods handle invalid session_id
        response = client.post("/upload", files=files, data=data)

        # Upload should still succeed (WebSocket messages just get ignored)
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["ok"] is True
        assert len(response_data["saved"]) == 1

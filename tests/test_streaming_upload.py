"""
Tests for streaming file upload functionality.

This module tests:
- Streaming upload of small and large files
- Disk space checking utilities
- Error handling for disk full and permission errors
- Partial file cleanup on errors
- Multiple file upload streaming
"""

import io
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient


class TestStreamingUpload:
    """Test streaming upload functionality."""

    def test_stream_small_file(self, client: TestClient, temp_upload_dir: Path):
        """Test streaming a small text file."""
        file_content = b"Hello, this is a test file!"
        files = {"files": ("test.txt", file_content, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 1
        assert data["saved"][0]["filename"] == "test.txt"
        assert data["saved"][0]["bytes"] == len(file_content)

        # Verify file was written to disk
        uploaded_file = temp_upload_dir / "test.txt"
        assert uploaded_file.exists()
        assert uploaded_file.read_bytes() == file_content

    def test_stream_large_file(self, client: TestClient, temp_upload_dir: Path):
        """Test streaming a large file (10MB)."""
        # Create 10MB of data
        file_size = 10 * 1024 * 1024
        large_data = b"x" * file_size
        files = {"files": ("large.bin", large_data, "application/octet-stream")}

        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 1
        assert data["saved"][0]["bytes"] == file_size

        # Verify file was written correctly
        uploaded_file = temp_upload_dir / "large.bin"
        assert uploaded_file.exists()
        assert uploaded_file.stat().st_size == file_size

    def test_stream_multiple_files(self, client: TestClient, temp_upload_dir: Path):
        """Test streaming multiple files in one request."""
        files = [
            ("files", ("file1.txt", b"Content 1", "text/plain")),
            ("files", ("file2.txt", b"Content 2", "text/plain")),
            ("files", ("file3.txt", b"Content 3", "text/plain")),
        ]

        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 3

        # Verify all files were written
        assert (temp_upload_dir / "file1.txt").exists()
        assert (temp_upload_dir / "file2.txt").exists()
        assert (temp_upload_dir / "file3.txt").exists()
        assert (temp_upload_dir / "file1.txt").read_bytes() == b"Content 1"

    def test_stream_to_subdirectory(self, client: TestClient, temp_upload_dir: Path):
        """Test streaming file to a subdirectory."""
        file_content = b"Subdirectory test"
        files = {"files": ("subdir_test.txt", file_content, "text/plain")}
        response = client.post(
            "/upload", files=files, data={"target_dir": "subfolder"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 1

        # Verify file is in subdirectory
        uploaded_file = temp_upload_dir / "subfolder" / "subdir_test.txt"
        assert uploaded_file.exists()
        assert uploaded_file.read_bytes() == file_content

    def test_stream_empty_file(self, client: TestClient, temp_upload_dir: Path):
        """Test streaming an empty file."""
        files = {"files": ("empty.txt", b"", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 1
        assert data["saved"][0]["bytes"] == 0

        # Verify empty file exists
        uploaded_file = temp_upload_dir / "empty.txt"
        assert uploaded_file.exists()
        assert uploaded_file.stat().st_size == 0


class TestDiskSpaceChecking:
    """Test disk space checking utilities."""

    def test_check_disk_space_returns_valid_data(self, temp_upload_dir: Path):
        """Test that check_disk_space returns valid filesystem statistics."""
        import app

        total, used, available = app.check_disk_space(temp_upload_dir)

        # All values should be positive integers
        assert total > 0
        assert used >= 0
        assert available > 0

        # Basic sanity checks
        assert total >= used
        assert total >= available
        assert used + available <= total  # May not be exact due to reserved space

    def test_disk_space_check_in_upload(self, client: TestClient, monkeypatch):
        """Test that upload endpoint checks disk space."""
        # Mock check_disk_space to raise an exception
        def mock_check_disk_space(path):
            raise OSError("Disk check failed")

        import app

        monkeypatch.setattr(app, "check_disk_space", mock_check_disk_space)

        files = {"files": ("test.txt", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 500
        assert "Failed to check disk space" in response.json()["detail"]


class TestErrorHandling:
    """Test error handling for various failure conditions."""

    def test_duplicate_filename_error(self, client: TestClient, temp_upload_dir: Path):
        """Test that uploading a file with duplicate name returns error."""
        # Upload first file
        files = {"files": ("duplicate.txt", b"First version", "text/plain")}
        response1 = client.post("/upload", files=files, data={"target_dir": ""})
        assert response1.status_code == 200

        # Try to upload file with same name
        files = {"files": ("duplicate.txt", b"Second version", "text/plain")}
        response2 = client.post("/upload", files=files, data={"target_dir": ""})

        assert response2.status_code == 200
        data = response2.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 0
        assert len(data["errors"]) == 1
        assert data["errors"][0]["file"] == "duplicate.txt"
        assert "already exists" in data["errors"][0]["error"]

        # Verify original file unchanged
        uploaded_file = temp_upload_dir / "duplicate.txt"
        assert uploaded_file.read_bytes() == b"First version"

    def test_invalid_filename_error(self, client: TestClient):
        """Test that invalid filenames are rejected."""
        files = {"files": (".", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 0
        assert len(data["errors"]) == 1
        assert "Invalid filename" in data["errors"][0]["error"]

    def test_disk_full_error_simulation(
        self, client: TestClient, temp_upload_dir: Path, monkeypatch
    ):
        """Test handling of disk full error during streaming."""
        import app

        # Create a mock that simulates disk full error
        original_stream = app.stream_upload_to_file

        async def mock_stream_disk_full(upload_file, destination, chunk_size=1024 * 1024):
            # Raise ENOSPC error (errno 28)
            error = OSError("No space left on device")
            error.errno = 28
            raise error

        monkeypatch.setattr(app, "stream_upload_to_file", mock_stream_disk_full)

        files = {"files": ("test.txt", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 507
        assert "Disk full" in response.json()["detail"]

        # Verify no file was left behind
        assert not (temp_upload_dir / "test.txt").exists()

    def test_permission_denied_error_simulation(
        self, client: TestClient, temp_upload_dir: Path, monkeypatch
    ):
        """Test handling of permission denied error during streaming."""
        import app

        # Create a mock that simulates permission denied error
        async def mock_stream_permission_denied(
            upload_file, destination, chunk_size=1024 * 1024
        ):
            # Raise EACCES error (errno 13)
            error = OSError("Permission denied")
            error.errno = 13
            raise error

        monkeypatch.setattr(app, "stream_upload_to_file", mock_stream_permission_denied)

        files = {"files": ("test.txt", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 0
        assert len(data["errors"]) == 1
        assert "Permission denied" in data["errors"][0]["error"]

    def test_partial_file_cleanup_on_error(
        self, client: TestClient, temp_upload_dir: Path, monkeypatch
    ):
        """Test that partial files are cleaned up when streaming fails."""
        import app

        # Track if cleanup was called
        cleanup_called = []

        original_stream = app.stream_upload_to_file

        async def mock_stream_with_failure(
            upload_file, destination, chunk_size=1024 * 1024
        ):
            # Write some data first
            destination.write_bytes(b"partial content")
            # Then fail
            raise OSError("Simulated failure")

        monkeypatch.setattr(app, "stream_upload_to_file", mock_stream_with_failure)

        files = {"files": ("test.txt", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1

        # Verify partial file was cleaned up
        assert not (temp_upload_dir / "test.txt").exists()

    def test_multiple_files_with_mixed_results(
        self, client: TestClient, temp_upload_dir: Path
    ):
        """Test uploading multiple files where some succeed and some fail."""
        # Create first file to cause duplicate error later
        (temp_upload_dir / "duplicate.txt").write_text("existing")

        files = [
            ("files", ("success1.txt", b"Content 1", "text/plain")),
            ("files", ("duplicate.txt", b"Duplicate", "text/plain")),  # Will fail
            ("files", ("success2.txt", b"Content 2", "text/plain")),
        ]

        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 2  # Two successful uploads
        assert len(data["errors"]) == 1  # One error

        # Verify successful uploads
        assert (temp_upload_dir / "success1.txt").exists()
        assert (temp_upload_dir / "success2.txt").exists()
        # Verify duplicate file unchanged
        assert (temp_upload_dir / "duplicate.txt").read_text() == "existing"


class TestDatabaseIntegration:
    """Test that streaming uploads integrate correctly with database indexing."""

    def test_uploaded_file_indexed_in_database(
        self, client: TestClient, temp_upload_dir: Path
    ):
        """Test that uploaded files are indexed in the database."""
        import app

        files = {"files": ("indexed.txt", b"Content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200

        # Query database for the file
        results = app.db.search("indexed.txt")
        assert len(results) > 0
        indexed_file = results[0]
        assert indexed_file.filename == "indexed.txt"
        assert indexed_file.size == 7  # len(b"Content")

    def test_uploaded_image_generates_thumbnail(
        self, client: TestClient, temp_upload_dir: Path, mock_image_bytes: bytes
    ):
        """Test that image uploads generate thumbnails."""
        files = {"files": ("test.jpg", mock_image_bytes, "image/jpeg")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()
        assert len(data["saved"]) == 1

        # Check that thumbnail directory was created
        thumbnail_dir = temp_upload_dir / ".thumbnails"
        assert thumbnail_dir.exists()


class TestResponseFormat:
    """Test the format of upload endpoint responses."""

    def test_successful_upload_response_format(
        self, client: TestClient, temp_upload_dir: Path
    ):
        """Test that successful upload returns expected response format."""
        files = {"files": ("test.txt", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})

        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert "ok" in data
        assert "saved" in data
        assert "errors" in data
        assert "target_dir" in data
        assert "message" in data

        assert data["ok"] is True
        assert isinstance(data["saved"], list)
        assert isinstance(data["errors"], list)

        # Check saved file structure
        assert len(data["saved"]) == 1
        saved_file = data["saved"][0]
        assert "filename" in saved_file
        assert "relative_path" in saved_file
        assert "bytes" in saved_file

    def test_cookie_is_set(self, client: TestClient):
        """Test that upload sets last_dir cookie."""
        files = {"files": ("test.txt", b"content", "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": "mydir"})

        assert response.status_code == 200
        # Check that cookie was set
        assert "set-cookie" in response.headers
        cookie_header = response.headers["set-cookie"]
        assert "last_dir" in cookie_header
        assert "mydir" in cookie_header

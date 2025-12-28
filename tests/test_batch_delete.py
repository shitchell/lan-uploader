"""
Tests for batch delete API endpoint.

This module tests the POST /api/batch-delete endpoint including:
- Batch delete files
- Batch delete directories
- Mixed batch delete (files and directories)
- Empty paths array
- Non-existent paths handling
- Path traversal protection
- Invalid request handling
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class TestBatchDeleteFiles:
    """Tests for batch deleting files."""

    def test_batch_delete_single_file(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch deleting a single file."""
        # Upload a file
        files = {"files": ("delete_me.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Verify file exists
        assert (temp_upload_dir / "delete_me.txt").exists()

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["delete_me.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 1
        assert data["errors"] == []
        assert "Deleted 1 item" in data["message"]

        # Verify file is deleted
        assert not (temp_upload_dir / "delete_me.txt").exists()

    def test_batch_delete_multiple_files(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch deleting multiple files at once."""
        # Upload multiple files
        files = [
            ("files", ("file1.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("file2.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("file3.txt", uploaded_file_bytes, "text/plain")),
        ]
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Verify files exist
        assert (temp_upload_dir / "file1.txt").exists()
        assert (temp_upload_dir / "file2.txt").exists()
        assert (temp_upload_dir / "file3.txt").exists()

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["file1.txt", "file2.txt", "file3.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 3
        assert data["errors"] == []
        assert "Deleted 3 item" in data["message"]

        # Verify all files are deleted
        assert not (temp_upload_dir / "file1.txt").exists()
        assert not (temp_upload_dir / "file2.txt").exists()
        assert not (temp_upload_dir / "file3.txt").exists()

    def test_batch_delete_files_in_subdirectory(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch deleting files in a subdirectory."""
        # Create directory and upload files
        (temp_upload_dir / "subdir").mkdir()
        files = [
            ("files", ("nested1.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("nested2.txt", uploaded_file_bytes, "text/plain")),
        ]
        response = client.post("/upload", files=files, data={"target_dir": "subdir"})
        assert response.status_code == 200

        # Batch delete with full paths
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["subdir/nested1.txt", "subdir/nested2.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 2
        assert data["errors"] == []


class TestBatchDeleteDirectories:
    """Tests for batch deleting directories."""

    def test_batch_delete_empty_directory(
        self, client: TestClient, temp_upload_dir: Path
    ):
        """Test batch deleting an empty directory."""
        # Create empty directory
        empty_dir = temp_upload_dir / "empty_dir"
        empty_dir.mkdir()

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["empty_dir"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 1
        assert data["errors"] == []

        # Verify directory is deleted
        assert not empty_dir.exists()

    def test_batch_delete_non_empty_directory(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch deleting a non-empty directory (force delete)."""
        # Create directory with files
        subdir = temp_upload_dir / "non_empty"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")
        (subdir / "nested").mkdir()
        (subdir / "nested" / "deep.txt").write_text("deep content")

        # Batch delete (should force delete the directory)
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["non_empty"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 1
        assert data["errors"] == []

        # Verify directory is deleted
        assert not subdir.exists()

    def test_batch_delete_multiple_directories(
        self, client: TestClient, temp_upload_dir: Path
    ):
        """Test batch deleting multiple directories."""
        # Create directories
        (temp_upload_dir / "dir1").mkdir()
        (temp_upload_dir / "dir2").mkdir()
        (temp_upload_dir / "dir3").mkdir()

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["dir1", "dir2", "dir3"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 3
        assert data["errors"] == []


class TestBatchDeleteMixed:
    """Tests for batch deleting mixed files and directories."""

    def test_batch_delete_mixed_files_and_directories(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch deleting a mix of files and directories."""
        # Create files and directories
        files = {"files": ("root_file.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        (temp_upload_dir / "mixed_dir").mkdir()
        (temp_upload_dir / "mixed_dir" / "child.txt").write_text("child")

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["root_file.txt", "mixed_dir"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 2
        assert data["errors"] == []

        # Verify both are deleted
        assert not (temp_upload_dir / "root_file.txt").exists()
        assert not (temp_upload_dir / "mixed_dir").exists()


class TestBatchDeleteEmptyPaths:
    """Tests for empty paths array handling."""

    def test_batch_delete_empty_array_returns_error(self, client: TestClient):
        """Test that batch delete with empty paths array returns 400 error."""
        response = client.post(
            "/api/batch-delete",
            json={"paths": []}
        )
        assert response.status_code == 400
        assert "No paths provided" in response.json()["detail"]

    def test_batch_delete_missing_paths_key(self, client: TestClient):
        """Test that batch delete without paths key returns 400 error."""
        response = client.post(
            "/api/batch-delete",
            json={}
        )
        assert response.status_code == 400
        assert "No paths provided" in response.json()["detail"]


class TestBatchDeleteNonExistent:
    """Tests for non-existent path handling."""

    def test_batch_delete_nonexistent_file(self, client: TestClient):
        """Test batch delete with a non-existent file path."""
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["nonexistent_file.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 0
        assert len(data["errors"]) == 1
        assert data["errors"][0]["path"] == "nonexistent_file.txt"
        assert "not found" in data["errors"][0]["error"].lower()

    def test_batch_delete_mixed_existent_and_nonexistent(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch delete with mix of existent and non-existent paths."""
        # Create one file
        files = {"files": ("exists.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Batch delete with mix
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["exists.txt", "does_not_exist.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["path"] == "does_not_exist.txt"

        # Verify the existing file was deleted
        assert not (temp_upload_dir / "exists.txt").exists()


class TestBatchDeletePathTraversal:
    """Tests for path traversal protection."""

    def test_batch_delete_path_traversal_blocked(self, client: TestClient):
        """Test that path traversal attempts are blocked."""
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["../../../etc/passwd"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 0
        assert len(data["errors"]) == 1
        assert "Invalid path" in data["errors"][0]["error"]

    def test_batch_delete_multiple_traversal_attempts(self, client: TestClient):
        """Test that multiple path traversal attempts are all blocked."""
        response = client.post(
            "/api/batch-delete",
            json={
                "paths": [
                    "../secret.txt",
                    "../../etc/shadow",
                    "foo/../../../bar",
                ]
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 0
        # All should have errors (either "Invalid path" or "not found" after sanitization)
        assert len(data["errors"]) == 3

    def test_batch_delete_path_traversal_mixed_with_valid(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test batch delete with mix of valid paths and traversal attempts."""
        # Create a valid file
        files = {"files": ("valid.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Batch delete with mix of valid and invalid
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["valid.txt", "../../../etc/passwd"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["deleted"] == 1  # Only valid file deleted
        assert len(data["errors"]) == 1  # One error for traversal attempt

        # Verify valid file was deleted
        assert not (temp_upload_dir / "valid.txt").exists()


class TestBatchDeleteInvalidRequests:
    """Tests for invalid request handling."""

    def test_batch_delete_invalid_json(self, client: TestClient):
        """Test batch delete with invalid JSON body."""
        response = client.post(
            "/api/batch-delete",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]

    def test_batch_delete_paths_not_list(self, client: TestClient):
        """Test batch delete with paths not being a list."""
        response = client.post(
            "/api/batch-delete",
            json={"paths": "single/path"}
        )
        assert response.status_code == 400
        assert "must be a list" in response.json()["detail"]

    def test_batch_delete_paths_contains_non_strings(
        self, client: TestClient, temp_upload_dir: Path
    ):
        """Test batch delete handles non-string items in paths array."""
        # Create a real file
        (temp_upload_dir / "real.txt").write_text("content")

        response = client.post(
            "/api/batch-delete",
            json={"paths": ["real.txt", 123, None, {"nested": "object"}]}
        )
        assert response.status_code == 200

        data = response.json()
        # The real file should be deleted
        assert data["deleted"] >= 1
        # Non-strings should have errors
        assert len(data["errors"]) >= 3  # 123, None, and the dict

    def test_batch_delete_empty_string_path(self, client: TestClient, temp_upload_dir: Path):
        """Test batch delete with empty string path.

        Empty string path resolves to UPLOAD_ROOT itself, which must NOT be deleted.
        The implementation protects against this by checking for empty paths and
        paths that resolve to UPLOAD_ROOT.
        """
        # Create a file to verify root is NOT deleted
        (temp_upload_dir / "canary.txt").write_text("canary")

        response = client.post(
            "/api/batch-delete",
            json={"paths": [""]}
        )
        assert response.status_code == 200

        data = response.json()
        # Empty path should be rejected, not delete the root
        assert data["deleted"] == 0
        assert len(data["errors"]) == 1
        assert data["errors"][0]["path"] == ""
        assert "Cannot delete root directory" in data["errors"][0]["error"]

        # Verify the upload root and canary file still exist
        assert temp_upload_dir.exists()
        assert (temp_upload_dir / "canary.txt").exists()


class TestBatchDeleteDatabaseIndex:
    """Tests for database index cleanup on batch delete."""

    def test_batch_delete_removes_from_database_index(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test that batch delete removes files from the database index."""
        # Upload files (this indexes them)
        files = [
            ("files", ("indexed1.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("indexed2.txt", uploaded_file_bytes, "text/plain")),
        ]
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Verify files are searchable
        response = client.get("/api/search?q=indexed")
        assert response.status_code == 200
        assert response.json()["count"] == 2

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["indexed1.txt", "indexed2.txt"]}
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 2

        # Verify files are no longer searchable
        response = client.get("/api/search?q=indexed")
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_batch_delete_directory_removes_children_from_index(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test that batch deleting a directory removes child files from index."""
        # Create directory and upload files
        (temp_upload_dir / "indexdir").mkdir()
        files = [
            ("files", ("child1.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("child2.txt", uploaded_file_bytes, "text/plain")),
        ]
        response = client.post("/upload", files=files, data={"target_dir": "indexdir"})
        assert response.status_code == 200

        # Verify files are searchable
        response = client.get("/api/search?q=child")
        assert response.status_code == 200
        assert response.json()["count"] == 2

        # Batch delete the directory
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["indexdir"]}
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 1

        # Verify child files are no longer searchable
        response = client.get("/api/search?q=child")
        assert response.status_code == 200
        assert response.json()["count"] == 0


class TestBatchDeleteResponseFormat:
    """Tests for batch delete response format."""

    def test_batch_delete_response_has_required_fields(
        self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes
    ):
        """Test that batch delete response has all required fields."""
        # Upload a file
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Batch delete
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["test.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        # Verify all required fields are present
        assert "ok" in data
        assert "deleted" in data
        assert "errors" in data
        assert "message" in data

        # Verify field types
        assert isinstance(data["ok"], bool)
        assert isinstance(data["deleted"], int)
        assert isinstance(data["errors"], list)
        assert isinstance(data["message"], str)

    def test_batch_delete_error_format(self, client: TestClient):
        """Test that batch delete errors have the correct format."""
        response = client.post(
            "/api/batch-delete",
            json={"paths": ["nonexistent.txt"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data["errors"]) == 1

        error = data["errors"][0]
        assert "path" in error
        assert "error" in error
        assert error["path"] == "nonexistent.txt"
        assert isinstance(error["error"], str)

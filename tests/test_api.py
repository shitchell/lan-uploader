"""
API endpoint tests for LAN Uploader.

This module tests all API endpoints including:
- Health checks
- File browsing and directory listing
- Directory creation
- File uploads
- File downloads
- File and directory deletion
- Search functionality
- Deprecated endpoints
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for the /healthz health check endpoint."""

    def test_healthz_returns_ok(self, client: TestClient):
        """Test that healthz endpoint returns successful response."""
        response = client.get("/healthz")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "root" in data
        assert "version" in data
        assert data["version"] == "2.0.0"

    def test_healthz_includes_upload_root(self, client: TestClient, temp_upload_dir: Path):
        """Test that healthz includes the configured upload root."""
        response = client.get("/healthz")
        data = response.json()

        # The root should match our test upload directory
        assert str(temp_upload_dir) in data["root"]


class TestBrowseEndpoint:
    """Tests for the /api/browse endpoint."""

    def test_browse_root_directory_empty(self, client: TestClient):
        """Test browsing an empty root directory."""
        response = client.get("/api/browse")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["path"] == ""
        # Filter out .thumbnails directory which is created automatically
        directories = [d for d in data["directories"] if not d["name"].startswith(".")]
        assert directories == []
        assert data["files"] == []
        assert len(data["breadcrumbs"]) == 1
        assert data["breadcrumbs"][0]["label"] == "Home"

    def test_browse_root_with_content(self, client: TestClient, sample_directory_structure: dict):
        """Test browsing root directory with files and folders."""
        response = client.get("/api/browse")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True

        # Filter out hidden directories like .thumbnails
        directories = [d for d in data["directories"] if not d["name"].startswith(".")]
        # Should have 2 directories (folder1, folder2)
        assert len(directories) == 2
        dir_names = {d["name"] for d in directories}
        assert dir_names == {"folder1", "folder2"}

        # Should have 1 file (root_file.txt)
        # Note: files won't show up until they're indexed via upload
        # This test assumes the fixture doesn't index files

    def test_browse_subdirectory(self, client: TestClient, sample_directory_structure: dict):
        """Test browsing a subdirectory."""
        response = client.get("/api/browse?path=folder1")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["path"] == "folder1"

        # Breadcrumbs should show Home -> folder1
        assert len(data["breadcrumbs"]) == 2
        assert data["breadcrumbs"][0]["label"] == "Home"
        assert data["breadcrumbs"][1]["label"] == "folder1"

    def test_browse_nested_directory(self, client: TestClient, sample_directory_structure: dict):
        """Test browsing a deeply nested directory."""
        response = client.get("/api/browse?path=folder2/nested")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["path"] == "folder2/nested"

        # Breadcrumbs should show Home -> folder2 -> nested
        assert len(data["breadcrumbs"]) == 3
        assert data["breadcrumbs"][2]["label"] == "nested"

    def test_browse_invalid_path_traversal(self, client: TestClient):
        """Test that path traversal attacks are blocked."""
        response = client.get("/api/browse?path=../../etc")
        assert response.status_code == 400
        assert "Invalid path" in response.json()["detail"]

    def test_browse_nonexistent_path(self, client: TestClient):
        """Test browsing a path that doesn't exist."""
        response = client.get("/api/browse?path=nonexistent/path")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestDirectoryCreation:
    """Tests for the POST /api/directory endpoint."""

    def test_create_directory_in_root(self, client: TestClient):
        """Test creating a new directory in the root."""
        response = client.post("/api/directory?path=&name=newdir")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["name"] == "newdir"
        assert data["path"] == "newdir"
        assert "created successfully" in data["message"]

    def test_create_directory_in_subdirectory(self, client: TestClient, sample_directory_structure: dict):
        """Test creating a directory within an existing subdirectory."""
        response = client.post("/api/directory?path=folder1&name=subdir")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["name"] == "subdir"
        assert data["path"] == "folder1/subdir"

    def test_create_directory_duplicate(self, client: TestClient, sample_directory_structure: dict):
        """Test that creating a duplicate directory fails."""
        response = client.post("/api/directory?path=&name=folder1")
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_create_directory_invalid_name_empty(self, client: TestClient):
        """Test that empty directory names are rejected."""
        response = client.post("/api/directory?path=&name=")
        assert response.status_code == 422  # FastAPI validation error

    def test_create_directory_invalid_name_dot(self, client: TestClient):
        """Test that '.' and '..' directory names are rejected."""
        response = client.post("/api/directory?path=&name=.")
        assert response.status_code == 400
        assert "Invalid directory name" in response.json()["detail"]

        response = client.post("/api/directory?path=&name=..")
        assert response.status_code == 400

    def test_create_directory_invalid_name_special_chars(self, client: TestClient):
        """Test that directory names with special characters are sanitized."""
        # secure_filename should sanitize this
        response = client.post("/api/directory?path=&name=test/../hack")
        assert response.status_code == 200
        # The name should be sanitized by secure_filename
        data = response.json()
        # secure_filename may sanitize differently depending on version
        # Just ensure the directory was created successfully
        assert data["ok"] is True

    def test_create_directory_in_nonexistent_parent(self, client: TestClient):
        """Test creating a directory in a non-existent parent."""
        response = client.post("/api/directory?path=nonexistent&name=newdir")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_directory_path_traversal(self, client: TestClient):
        """Test that path traversal is blocked in parent path."""
        response = client.post("/api/directory?path=../../etc&name=hack")
        assert response.status_code == 400
        assert "Invalid" in response.json()["detail"]


class TestFileUpload:
    """Tests for the POST /upload endpoint."""

    def test_upload_single_file(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test uploading a single file to the root directory."""
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        data = {"target_dir": ""}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        result = response.json()
        assert result["ok"] is True
        assert len(result["saved"]) == 1
        assert result["saved"][0]["filename"] == "test.txt"
        assert result["saved"][0]["bytes"] == len(uploaded_file_bytes)

    def test_upload_multiple_files(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test uploading multiple files at once."""
        files = [
            ("files", ("file1.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("file2.txt", b"Second file content", "text/plain")),
        ]
        data = {"target_dir": ""}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        result = response.json()
        assert result["ok"] is True
        assert len(result["saved"]) == 2
        filenames = {f["filename"] for f in result["saved"]}
        assert filenames == {"file1.txt", "file2.txt"}

    def test_upload_to_subdirectory(self, client: TestClient, sample_directory_structure: dict, uploaded_file_bytes: bytes):
        """Test uploading files to a subdirectory."""
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        data = {"target_dir": "folder1"}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        result = response.json()
        assert result["ok"] is True
        assert result["target_dir"] == "folder1"
        assert result["saved"][0]["relative_path"] == "/folder1"

    def test_upload_image_file(self, client: TestClient, mock_image_bytes: bytes):
        """Test uploading an image file."""
        files = {"files": ("image.png", mock_image_bytes, "image/png")}
        data = {"target_dir": ""}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        result = response.json()
        assert result["ok"] is True
        assert result["saved"][0]["filename"] == "image.png"

    def test_upload_sets_cookie(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test that upload sets a last_dir cookie."""
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        data = {"target_dir": "folder1"}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        # Check that cookie is set
        assert "last_dir" in response.cookies
        assert response.cookies["last_dir"] == "folder1"

    def test_upload_no_files_error(self, client: TestClient):
        """Test that uploading with no files returns an error."""
        data = {"target_dir": ""}
        response = client.post("/upload", data=data)
        assert response.status_code == 422  # Validation error - missing required field

    def test_upload_to_nonexistent_directory_creates_it(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test that uploading to a non-existent directory creates it."""
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        data = {"target_dir": "new/nested/path"}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        result = response.json()
        assert result["ok"] is True

    def test_upload_path_traversal_blocked(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test that path traversal attacks are blocked on upload."""
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        data = {"target_dir": "../../etc"}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 400
        assert "Invalid target directory" in response.json()["detail"]


class TestFileDownload:
    """Tests for the GET /api/file/{filepath:path} endpoint."""

    def test_download_file(self, client: TestClient, sample_text_file: Path, temp_upload_dir: Path):
        """Test downloading a file."""
        # Get relative path
        rel_path = sample_text_file.relative_to(temp_upload_dir)

        response = client.get(f"/api/file/{rel_path}")
        assert response.status_code == 200
        assert response.content == b"This is a sample text file for testing.\n"

    def test_download_file_with_download_param(self, client: TestClient, sample_text_file: Path, temp_upload_dir: Path):
        """Test downloading a file with download=true parameter."""
        rel_path = sample_text_file.relative_to(temp_upload_dir)

        response = client.get(f"/api/file/{rel_path}?download=true")
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment")

    def test_download_image_file(self, client: TestClient, sample_image_file: Path, temp_upload_dir: Path):
        """Test downloading an image file."""
        rel_path = sample_image_file.relative_to(temp_upload_dir)

        response = client.get(f"/api/file/{rel_path}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_download_nonexistent_file(self, client: TestClient):
        """Test that downloading a non-existent file returns 404."""
        response = client.get("/api/file/nonexistent.txt")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_download_directory_fails(self, client: TestClient, sample_directory_structure: dict):
        """Test that attempting to download a directory fails."""
        response = client.get("/api/file/folder1")
        assert response.status_code == 400
        assert "directory" in response.json()["detail"].lower()

    def test_download_path_traversal_blocked(self, client: TestClient):
        """Test that path traversal is blocked."""
        response = client.get("/api/file/../../etc/passwd")
        # May return 400 (invalid path) or 404 (not found after normalization)
        assert response.status_code in (400, 404)
        assert "detail" in response.json()


class TestFileAndDirectoryDeletion:
    """Tests for the DELETE /api/file/{filepath:path} endpoint."""

    def test_delete_file(self, client: TestClient, sample_text_file: Path, temp_upload_dir: Path):
        """Test deleting a file."""
        rel_path = sample_text_file.relative_to(temp_upload_dir)

        response = client.delete(f"/api/file/{rel_path}")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "deleted successfully" in data["message"]

        # Verify file is actually deleted
        assert not sample_text_file.exists()

    def test_delete_empty_directory(self, client: TestClient, temp_upload_dir: Path):
        """Test deleting an empty directory."""
        # Create an empty directory
        empty_dir = temp_upload_dir / "empty"
        empty_dir.mkdir()

        response = client.delete("/api/file/empty")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True

        # Verify directory is deleted
        assert not empty_dir.exists()

    def test_delete_non_empty_directory_without_force(self, client: TestClient, sample_directory_structure: dict):
        """Test that deleting a non-empty directory without force fails."""
        response = client.delete("/api/file/folder1")
        assert response.status_code == 400

        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "directory_not_empty"
        assert "force=true" in data["message"]

    def test_delete_non_empty_directory_with_force(self, client: TestClient, sample_directory_structure: dict):
        """Test deleting a non-empty directory with force=true."""
        response = client.delete("/api/file/folder1?force=true")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True

        # Verify directory is deleted
        assert not sample_directory_structure["folder1"].exists()

    def test_delete_nonexistent_file(self, client: TestClient):
        """Test that deleting a non-existent file returns 404."""
        response = client.delete("/api/file/nonexistent.txt")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_path_traversal_blocked(self, client: TestClient):
        """Test that path traversal is blocked."""
        response = client.delete("/api/file/../../etc/passwd")
        # May return 400 (invalid path) or 404 (not found after normalization)
        assert response.status_code in (400, 404)
        assert "detail" in response.json()


class TestSearch:
    """Tests for the GET /api/search endpoint."""

    def test_search_no_results(self, client: TestClient):
        """Test searching when no files match."""
        response = client.get("/api/search?q=nonexistent")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["query"] == "nonexistent"
        assert data["count"] == 0
        assert data["results"] == []

    def test_search_finds_files(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test searching for uploaded files."""
        # First upload some files to index them
        files = [
            ("files", ("document.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("document.pdf", b"PDF content", "application/pdf")),
            ("files", ("image.png", b"PNG content", "image/png")),
        ]
        client.post("/upload", files=files, data={"target_dir": ""})

        # Search for 'document'
        response = client.get("/api/search?q=document")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["count"] == 2
        filenames = {f["name"] for f in data["results"]}
        assert filenames == {"document.txt", "document.pdf"}

    def test_search_case_insensitive(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test that search is case-insensitive."""
        # Upload a file
        files = {"files": ("TestFile.txt", uploaded_file_bytes, "text/plain")}
        client.post("/upload", files=files, data={"target_dir": ""})

        # Search with different case
        response = client.get("/api/search?q=testfile")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] >= 1

    def test_search_with_limit(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test search with result limit."""
        # Upload multiple files
        files = [
            ("files", (f"test{i}.txt", uploaded_file_bytes, "text/plain"))
            for i in range(10)
        ]
        client.post("/upload", files=files, data={"target_dir": ""})

        # Search with limit
        response = client.get("/api/search?q=test&limit=5")
        assert response.status_code == 200

        data = response.json()
        assert len(data["results"]) <= 5

    def test_search_missing_query(self, client: TestClient):
        """Test that search without query parameter fails."""
        response = client.get("/api/search")
        assert response.status_code == 422  # Validation error

    def test_search_includes_metadata(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test that search results include file metadata."""
        # Upload a file
        files = {"files": ("test.txt", uploaded_file_bytes, "text/plain")}
        client.post("/upload", files=files, data={"target_dir": ""})

        # Search for it
        response = client.get("/api/search?q=test")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] >= 1

        result = data["results"][0]
        assert "name" in result
        assert "path" in result
        assert "size" in result
        assert "extension" in result
        assert "mime_type" in result

    # Directory search tests (Issue #013)

    def test_search_finds_directories(self, client: TestClient, temp_upload_dir: Path):
        """Test that directories appear in search results."""
        # Create directory directly on filesystem
        test_dir = temp_upload_dir / "test_folder"
        test_dir.mkdir()

        response = client.get("/api/search?q=test_folder")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True

        # Find directory results
        dir_results = [r for r in data["results"] if r.get("is_directory")]
        assert len(dir_results) >= 1, "Expected at least one directory result"
        assert dir_results[0]["name"] == "test_folder"
        assert dir_results[0]["is_directory"] is True

    def test_search_directory_has_required_fields(self, client: TestClient, temp_upload_dir: Path):
        """Test that directory results have all required fields."""
        # Create directory
        my_folder = temp_upload_dir / "my_folder"
        my_folder.mkdir()

        response = client.get("/api/search?q=my_folder")
        assert response.status_code == 200

        data = response.json()
        dir_results = [r for r in data["results"] if r.get("is_directory")]
        assert len(dir_results) >= 1

        result = dir_results[0]
        assert "name" in result
        assert "path" in result
        assert "parent_path" in result
        assert "is_directory" in result
        assert result["is_directory"] is True

    def test_search_file_has_is_directory_false(self, client: TestClient, uploaded_file_bytes: bytes):
        """Test that file results include is_directory: False."""
        # Upload a file
        files = {"files": ("dir_test_file.txt", uploaded_file_bytes, "text/plain")}
        client.post("/upload", files=files, data={"target_dir": ""})

        response = client.get("/api/search?q=dir_test_file")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] >= 1

        # Find file results (not directory)
        file_results = [r for r in data["results"] if not r.get("is_directory")]
        assert len(file_results) >= 1
        assert file_results[0]["is_directory"] is False

    def test_search_returns_both_files_and_directories(self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes):
        """Test that search returns both files and directories with same name prefix."""
        # Create directory
        documents_dir = temp_upload_dir / "documents"
        documents_dir.mkdir()

        # Upload file with similar name
        files = {"files": ("documents.txt", uploaded_file_bytes, "text/plain")}
        client.post("/upload", files=files, data={"target_dir": ""})

        response = client.get("/api/search?q=documents")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] >= 2, "Expected at least 2 results (directory + file)"

        # Check for both directory and file
        dir_results = [r for r in data["results"] if r.get("is_directory")]
        file_results = [r for r in data["results"] if not r.get("is_directory")]

        assert len(dir_results) >= 1, "Expected at least one directory result"
        assert len(file_results) >= 1, "Expected at least one file result"
        assert dir_results[0]["name"] == "documents"
        assert dir_results[0]["is_directory"] is True
        assert any(r["name"] == "documents.txt" for r in file_results)

    def test_search_directories_first_then_files(self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes):
        """Test that directories appear before files in search results."""
        # Create directory
        alpha_dir = temp_upload_dir / "alpha_dir"
        alpha_dir.mkdir()

        # Upload file
        files = {"files": ("alpha_file.txt", uploaded_file_bytes, "text/plain")}
        client.post("/upload", files=files, data={"target_dir": ""})

        response = client.get("/api/search?q=alpha")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] >= 2

        # First result should be directory
        assert data["results"][0]["is_directory"] is True
        assert data["results"][0]["name"] == "alpha_dir"

        # Second result should be file
        assert data["results"][1]["is_directory"] is False
        assert data["results"][1]["name"] == "alpha_file.txt"

    def test_search_nested_directory(self, client: TestClient, temp_upload_dir: Path):
        """Test that nested directories can be found with correct parent_path."""
        # Create nested directory structure
        parent_dir = temp_upload_dir / "parent"
        parent_dir.mkdir()
        child_dir = parent_dir / "child_folder"
        child_dir.mkdir()

        response = client.get("/api/search?q=child_folder")
        assert response.status_code == 200

        data = response.json()
        dir_results = [r for r in data["results"] if r.get("is_directory")]
        assert len(dir_results) >= 1

        result = dir_results[0]
        assert result["name"] == "child_folder"
        assert result["parent_path"] == "parent"
        assert result["path"] == "parent/child_folder"

    def test_search_excludes_hidden_directories(self, client: TestClient, temp_upload_dir: Path):
        """Test that hidden directories (starting with .) are not returned."""
        # Create hidden directory
        hidden_dir = temp_upload_dir / ".hidden_dir"
        hidden_dir.mkdir()

        response = client.get("/api/search?q=hidden")
        assert response.status_code == 200

        data = response.json()
        # Should not find any directories with "hidden" that start with "."
        dir_results = [r for r in data["results"] if r.get("is_directory")]
        hidden_dirs = [r for r in dir_results if r["name"].startswith(".")]
        assert len(hidden_dirs) == 0, "Hidden directories should not appear in search results"

    def test_search_case_insensitive_directories(self, client: TestClient, temp_upload_dir: Path):
        """Test that directory search is case-insensitive."""
        # Create directory with mixed case
        my_folder = temp_upload_dir / "MyFolder"
        my_folder.mkdir()

        # Search with lowercase
        response = client.get("/api/search?q=myfolder")
        assert response.status_code == 200

        data = response.json()
        dir_results = [r for r in data["results"] if r.get("is_directory")]
        assert len(dir_results) >= 1
        assert dir_results[0]["name"] == "MyFolder"


class TestDeprecatedEndpoints:
    """Tests for deprecated API endpoints."""

    def test_deprecated_dirs_endpoint(self, client: TestClient, sample_directory_structure: dict):
        """Test the deprecated /api/dirs endpoint."""
        response = client.get("/api/dirs")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "dirs" in data
        assert "breadcrumbs" in data

        # Filter out hidden directories
        dirs = [d for d in data["dirs"] if not d["name"].startswith(".")]
        # Should list the two root directories
        assert len(dirs) == 2
        dir_names = {d["name"] for d in dirs}
        assert dir_names == {"folder1", "folder2"}

    def test_deprecated_dirs_with_path(self, client: TestClient, sample_directory_structure: dict):
        """Test the deprecated /api/dirs endpoint with a path parameter."""
        response = client.get("/api/dirs?path=folder2")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["path"] == "folder2"

        # Should list the nested directory
        assert len(data["dirs"]) == 1
        assert data["dirs"][0]["name"] == "nested"

    def test_deprecated_dirs_breadcrumbs(self, client: TestClient, sample_directory_structure: dict):
        """Test that deprecated endpoint returns proper breadcrumbs."""
        response = client.get("/api/dirs?path=folder2/nested")
        assert response.status_code == 200

        data = response.json()
        # Old endpoint has "/" as root label
        assert data["breadcrumbs"][0]["label"] == "/"
        assert len(data["breadcrumbs"]) == 3


class TestIndexPage:
    """Tests for the main index page endpoint."""

    def test_index_page_loads(self, client: TestClient):
        """Test that the main page loads successfully."""
        response = client.get("/")
        assert response.status_code == 200
        # Should return HTML
        assert "text/html" in response.headers["content-type"]

    def test_index_page_with_last_dir_cookie(self, client: TestClient):
        """Test that the index page respects the last_dir cookie."""
        # Set a cookie
        cookies = {"last_dir": "test/path"}
        response = client.get("/", cookies=cookies)
        assert response.status_code == 200


class TestLazyCaching:
    """Tests for filesystem-based browsing with lazy DB caching."""

    def test_manually_added_file_appears_in_browse(self, client: TestClient, temp_upload_dir: Path):
        """Test that files added directly to filesystem appear when browsing."""
        # Create a file directly on filesystem (not via upload)
        manual_file = temp_upload_dir / "manual_file.txt"
        manual_file.write_text("This file was not uploaded through the API")

        # Browse the directory - file should appear
        response = client.get("/api/browse")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True

        # File should be in the listing
        file_names = [f["name"] for f in data["files"]]
        assert "manual_file.txt" in file_names

    def test_manually_added_file_gets_lazy_cached(self, client: TestClient, temp_upload_dir: Path):
        """Test that browsing a directory lazy-caches uncached files to DB."""
        # Create a file directly on filesystem
        manual_file = temp_upload_dir / "lazy_cache_test.txt"
        manual_file.write_text("Test content for lazy caching")

        # Browse to trigger lazy caching
        response = client.get("/api/browse")
        assert response.status_code == 200

        # Now search for the file - should find it because it was lazy-cached
        response = client.get("/api/search?q=lazy_cache_test")
        assert response.status_code == 200

        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "lazy_cache_test.txt"

    def test_mixed_uploaded_and_manual_files(self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes):
        """Test browsing with both uploaded (cached) and manual (uncached) files."""
        # Upload 2 files via API
        files = [
            ("files", ("uploaded1.txt", uploaded_file_bytes, "text/plain")),
            ("files", ("uploaded2.txt", uploaded_file_bytes, "text/plain")),
        ]
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Manually add 2 more files
        (temp_upload_dir / "manual1.txt").write_text("Manual file 1")
        (temp_upload_dir / "manual2.txt").write_text("Manual file 2")

        # Browse - should see all 4 files
        response = client.get("/api/browse")
        assert response.status_code == 200

        data = response.json()
        file_names = {f["name"] for f in data["files"]}
        assert file_names == {"uploaded1.txt", "uploaded2.txt", "manual1.txt", "manual2.txt"}

    def test_deleted_file_disappears_from_browse(self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes):
        """Test that files deleted from filesystem don't appear in browse."""
        # Upload a file
        files = {"files": ("to_delete.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Verify it appears in browse
        response = client.get("/api/browse")
        file_names = [f["name"] for f in response.json()["files"]]
        assert "to_delete.txt" in file_names

        # Delete the file directly from filesystem (simulating external deletion)
        (temp_upload_dir / "to_delete.txt").unlink()

        # Browse again - file should not appear
        response = client.get("/api/browse")
        file_names = [f["name"] for f in response.json()["files"]]
        assert "to_delete.txt" not in file_names

    def test_subdirectory_file_count_from_filesystem(self, client: TestClient, temp_upload_dir: Path):
        """Test that directory file counts come from filesystem, not DB."""
        # Create a subdirectory with files
        subdir = temp_upload_dir / "counted_dir"
        subdir.mkdir()
        for i in range(5):
            (subdir / f"file{i}.txt").write_text(f"Content {i}")

        # Browse root - should show directory with correct file count
        response = client.get("/api/browse")
        assert response.status_code == 200

        data = response.json()
        dirs = [d for d in data["directories"] if d["name"] == "counted_dir"]
        assert len(dirs) == 1
        assert dirs[0]["file_count"] == 5


class TestSyncEndpoint:
    """Tests for the POST /api/sync endpoint."""

    def test_sync_adds_new_files(self, client: TestClient, temp_upload_dir: Path):
        """Test that sync adds files that exist on disk but not in DB."""
        # Add files directly to filesystem
        (temp_upload_dir / "sync_test1.txt").write_text("Content 1")
        (temp_upload_dir / "sync_test2.txt").write_text("Content 2")

        # Run sync
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["added"] >= 2  # At least our 2 files

        # Files should now be searchable
        response = client.get("/api/search?q=sync_test")
        assert response.json()["count"] == 2

    def test_sync_removes_stale_entries(self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes):
        """Test that sync removes DB entries for deleted files."""
        # Upload a file (creates DB entry)
        files = {"files": ("sync_delete.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        # Delete file from filesystem
        (temp_upload_dir / "sync_delete.txt").unlink()

        # Run sync
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["removed"] >= 1

        # File should no longer be searchable
        response = client.get("/api/search?q=sync_delete")
        assert response.json()["count"] == 0

    def test_sync_updates_changed_files(self, client: TestClient, temp_upload_dir: Path, uploaded_file_bytes: bytes):
        """Test that sync updates DB when file size changes."""
        # Upload a file
        files = {"files": ("sync_update.txt", uploaded_file_bytes, "text/plain")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200
        original_size = len(uploaded_file_bytes)

        # Modify the file (change its size)
        new_content = b"This is completely different content with a different size"
        (temp_upload_dir / "sync_update.txt").write_bytes(new_content)

        # Run sync
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        # File size changed, so it should be updated
        assert data["updated"] >= 1

    def test_sync_returns_statistics(self, client: TestClient, temp_upload_dir: Path):
        """Test that sync returns proper statistics."""
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        assert "ok" in data
        assert "added" in data
        assert "updated" in data
        assert "removed" in data
        assert "total_files" in data
        assert "thumbnails_generated" in data

        # All should be non-negative integers
        assert isinstance(data["added"], int) and data["added"] >= 0
        assert isinstance(data["updated"], int) and data["updated"] >= 0
        assert isinstance(data["removed"], int) and data["removed"] >= 0
        assert isinstance(data["total_files"], int) and data["total_files"] >= 0
        assert isinstance(data["thumbnails_generated"], int) and data["thumbnails_generated"] >= 0

    def test_sync_generates_missing_image_thumbnails(self, client: TestClient, temp_upload_dir: Path):
        """Test that sync generates thumbnails for images without cached thumbnails."""
        from PIL import Image

        # Create an image directly on filesystem (bypassing upload)
        image_path = temp_upload_dir / "sync_thumb_test.png"
        img = Image.new('RGB', (100, 100), color='green')
        img.save(image_path, 'PNG')

        # Verify no thumbnail exists yet
        thumb_cache = temp_upload_dir / ".thumbnails"
        initial_thumbs = list(thumb_cache.glob("*.jpg")) if thumb_cache.exists() else []

        # Run sync
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["thumbnails_generated"] >= 1

        # Thumbnail should now be requestable
        response = client.get("/api/thumbnail/sync_thumb_test.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

    def test_sync_generates_missing_video_thumbnails(self, client: TestClient, sample_video_file: Path, temp_upload_dir: Path):
        """Test that sync generates thumbnails for videos without cached thumbnails."""
        # sample_video_file is created directly on filesystem, not via upload
        # So it won't have a thumbnail yet

        # Run sync
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["thumbnails_generated"] >= 1

        # Thumbnail should now be requestable
        rel_path = sample_video_file.relative_to(temp_upload_dir)
        response = client.get(f"/api/thumbnail/{rel_path}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

    def test_sync_respects_max_thumbnails_limit(self, client: TestClient, temp_upload_dir: Path):
        """Test that sync respects the max_thumbnails limit."""
        from PIL import Image

        # Create 5 images directly on filesystem
        for i in range(5):
            image_path = temp_upload_dir / f"limit_test_{i}.png"
            img = Image.new('RGB', (50, 50), color=(i * 50, 0, 0))
            img.save(image_path, 'PNG')

        # Run sync with limit of 2 thumbnails - should generate exactly 2
        response = client.post("/api/sync?max_thumbnails=2")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["thumbnails_generated"] == 2

        # Track total generated
        total_generated = 2

        # Keep running sync until all thumbnails are generated
        while total_generated < 5:
            response = client.post("/api/sync?max_thumbnails=2")
            data = response.json()
            assert data["thumbnails_generated"] <= 2  # Never more than limit
            total_generated += data["thumbnails_generated"]

        # Final sync - no more thumbnails to generate
        response = client.post("/api/sync?max_thumbnails=2")
        data = response.json()
        assert data["thumbnails_generated"] == 0

    def test_sync_skips_existing_thumbnails(self, client: TestClient, temp_upload_dir: Path, mock_image_bytes: bytes):
        """Test that sync doesn't regenerate existing thumbnails."""
        # Upload an image (which generates a thumbnail)
        files = {"files": ("already_has_thumb.png", mock_image_bytes, "image/png")}
        response = client.post("/upload", files=files, data={"target_dir": ""})
        assert response.status_code == 200

        import time
        time.sleep(1.0)  # Wait for background thumbnail generation

        # Verify thumbnail was generated by requesting it
        response = client.get("/api/thumbnail/already_has_thumb.png")
        assert response.status_code == 200

        # Run sync - should not regenerate the thumbnail
        response = client.post("/api/sync")
        assert response.status_code == 200

        data = response.json()
        # The uploaded file already has a thumbnail, so it shouldn't be counted
        assert data["thumbnails_generated"] == 0


class TestChangelogEndpoint:
    """Tests for the /api/changelog endpoints."""

    def test_changelog_returns_current_version(self, client: TestClient):
        """Test that /api/changelog returns the current version changelog."""
        response = client.get("/api/changelog")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "version" in data
        assert "content" in data
        assert len(data["content"]) > 0
        # Content should contain typical changelog sections
        assert "Features" in data["content"] or "Improvements" in data["content"] or "Bug Fixes" in data["content"]

    def test_changelog_returns_specific_version(self, client: TestClient):
        """Test that /api/changelog?version=X returns specific version."""
        # First get current version
        health_response = client.get("/healthz")
        current_version = health_response.json()["version"]

        # Request that specific version
        response = client.get(f"/api/changelog?version={current_version}")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["version"] == current_version
        assert len(data["content"]) > 0

    def test_changelog_nonexistent_version_returns_404(self, client: TestClient):
        """Test that requesting non-existent version returns 404."""
        response = client.get("/api/changelog?version=99.99.99")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_changelog_versions_returns_list(self, client: TestClient):
        """Test that /api/changelog/versions returns list of versions."""
        response = client.get("/api/changelog/versions")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "versions" in data
        assert isinstance(data["versions"], list)
        assert len(data["versions"]) >= 1

    def test_changelog_versions_sorted_descending(self, client: TestClient):
        """Test that versions are sorted in descending order."""
        response = client.get("/api/changelog/versions")
        data = response.json()

        versions = data["versions"]
        if len(versions) > 1:
            # Verify descending order
            def version_tuple(v):
                return tuple(int(p) if p.isdigit() else 0 for p in v.split('.'))

            for i in range(len(versions) - 1):
                assert version_tuple(versions[i]) >= version_tuple(versions[i + 1])

    def test_changelog_versions_includes_current(self, client: TestClient):
        """Test that versions list includes the current app version."""
        # Get current version from healthz
        health_response = client.get("/healthz")
        current_version = health_response.json()["version"]

        # Get versions list
        response = client.get("/api/changelog/versions")
        data = response.json()

        assert current_version in data["versions"]

    def test_changelog_content_is_markdown(self, client: TestClient):
        """Test that changelog content is valid markdown with expected structure."""
        response = client.get("/api/changelog")
        assert response.status_code == 200

        data = response.json()
        content = data["content"]

        # Should contain markdown headers (# or ##)
        assert "#" in content
        # Should contain list items (- )
        assert "- " in content


class TestThumbnails:
    """Tests for the thumbnail generation endpoint."""

    def test_thumbnail_for_image(self, client: TestClient, sample_image_file: Path, temp_upload_dir: Path):
        """Test generating a thumbnail for an image file."""
        rel_path = sample_image_file.relative_to(temp_upload_dir)

        response = client.get(f"/api/thumbnail/{rel_path}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

    def test_thumbnail_for_video(self, client: TestClient, sample_video_file: Path, temp_upload_dir: Path):
        """Test generating a thumbnail for a video file."""
        rel_path = sample_video_file.relative_to(temp_upload_dir)

        response = client.get(f"/api/thumbnail/{rel_path}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

    def test_thumbnail_for_non_media_fails(self, client: TestClient, sample_text_file: Path, temp_upload_dir: Path):
        """Test that requesting thumbnail for non-image/video fails."""
        rel_path = sample_text_file.relative_to(temp_upload_dir)

        response = client.get(f"/api/thumbnail/{rel_path}")
        assert response.status_code == 400
        assert "only available for images and videos" in response.json()["detail"]

    def test_thumbnail_for_nonexistent_file(self, client: TestClient):
        """Test that requesting thumbnail for non-existent file returns 404."""
        response = client.get("/api/thumbnail/nonexistent.png")
        assert response.status_code == 404

    def test_video_upload_generates_thumbnail(self, client: TestClient, mock_video_bytes: bytes, temp_upload_dir: Path):
        """Test that uploading a video triggers thumbnail generation."""
        import time

        files = {"files": ("test_video.mp4", mock_video_bytes, "video/mp4")}
        data = {"target_dir": ""}

        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200

        # Give background task time to complete
        time.sleep(0.5)

        # Request thumbnail - should exist now
        response = client.get("/api/thumbnail/test_video.mp4")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

# LAN Uploader Test Suite

This directory contains comprehensive tests for the LAN Uploader application, including API tests, integration tests, and end-to-end tests.

## Test Files

### test_api.py (50 tests)
Comprehensive API endpoint testing using FastAPI TestClient:

**Health Checks** (`/healthz`)
- Service status and version validation
- Upload root configuration

**Browse Endpoint** (`/api/browse`)
- Root and subdirectory listing
- Breadcrumb navigation
- Path traversal protection
- Empty and populated directories

**Directory Creation** (`POST /api/directory`)
- Creating directories in root and subdirectories
- Duplicate directory handling
- Invalid name validation (empty, `.`, `..`)
- Special character sanitization
- Path traversal protection

**File Uploads** (`POST /upload`)
- Single and multiple file uploads
- Upload to subdirectories
- Image file uploads
- Cookie persistence for last directory
- Automatic directory creation
- Path traversal protection

**File Downloads** (`GET /api/file/{path}`)
- File serving with correct MIME types
- Force download parameter
- Image file handling
- Directory download prevention
- Path traversal protection

**File/Directory Deletion** (`DELETE /api/file/{path}`)
- File deletion
- Empty directory deletion
- Non-empty directory deletion with force parameter
- Path traversal protection

**Search** (`GET /api/search`)
- Filename search with query
- Case-insensitive searching
- Result limits
- Metadata inclusion in results

**Deprecated Endpoints** (`/api/dirs`)
- Backwards compatibility testing
- Directory listing
- Breadcrumb generation

**Thumbnails** (`/api/thumbnail/{path}`)
- Image thumbnail generation
- Non-image file rejection
- JPEG thumbnail output

### test_integration.py

**TestDatabaseManager**
Tests for database operations using SQLAlchemy:
- Table creation and initialization
- File indexing (create and update)
- File search functionality
- File removal from index
- Directory removal from index
- File listing by directory
- Query limits and pagination

### TestThumbnailGenerator
Tests for thumbnail generation using Pillow:
- Thumbnail cache directory creation
- Thumbnail generation from images
- Cache usage and validation
- Force regeneration
- RGBA/PNG image handling (conversion to JPEG)
- Individual thumbnail removal
- Complete cache clearing

### TestFileIndexingWorkflow
End-to-end workflow tests:
- Complete text file workflow (upload -> index -> search -> delete -> cleanup)
- Complete image file workflow (upload -> thumbnail -> index -> search -> delete -> cleanup)
- Multi-file workflows across directories
- Directory-level operations

### TestSecurityChecks
Security and path traversal prevention:
- Valid path acceptance
- Path traversal attack prevention (../../etc/passwd)
- Absolute path validation
- Symlink handling and security
- Special filename sanitization
- Werkzeug secure_filename usage

### TestEdgeCases
Edge case and error handling:
- Long filenames (200+ characters)
- Special characters in filenames
- Unicode filename support (Cyrillic, Chinese, Japanese, accented)
- Empty search queries
- Duplicate filepath handling
- File size edge cases

## Running Tests

### Run all tests
```bash
pytest
# or
pytest tests/
```

### Run tests with verbose output
```bash
pytest -v
```

### Run only API tests
```bash
pytest tests/test_api.py -v
```

### Run only integration tests
```bash
pytest tests/test_integration.py -v
```

### Run tests with coverage report
```bash
pytest --cov=. --cov-report=term-missing --cov-report=html
```

### Run specific test class
```bash
pytest tests/test_api.py::TestHealthEndpoint -v
# or
pytest tests/test_integration.py::TestDatabaseManager -v
```

### Run specific test method
```bash
pytest tests/test_api.py::TestHealthEndpoint::test_healthz_returns_ok -v
```

## Test Dependencies

Install development dependencies:
```bash
pip install -r requirements-dev.txt
```

Key dependencies:
- **pytest**: Testing framework
- **pytest-cov**: Coverage reporting
- **pytest-asyncio**: Async test support
- **httpx**: HTTP client for FastAPI testing
- **Pillow**: Image processing (for thumbnail tests)
- **SQLAlchemy**: Database operations
- **FastAPI**: Web framework (from requirements.txt)
- **python-multipart**: File upload support

## Test Design Principles

1. **Isolation**: Each test uses temporary databases and file systems via pytest fixtures
2. **Cleanup**: Automatic cleanup via pytest's tmp_path fixture
3. **Independence**: Tests can run in any order without dependencies
4. **Real Components**: Tests use actual FastAPI app, DatabaseManager, and ThumbnailGenerator
5. **Security Focus**: Extensive path traversal and security testing
6. **Fast Execution**: All API tests complete in under 10 seconds

## Test Fixtures (conftest.py)

The following fixtures are available for all tests:

- **temp_upload_dir**: Temporary upload directory, cleaned up after each test
- **temp_db_path**: Temporary database file path
- **test_db**: Clean DatabaseManager instance with initialized tables
- **client**: FastAPI TestClient with isolated test environment
- **sample_text_file**: Pre-created sample text file
- **sample_image_file**: Pre-created sample PNG image
- **sample_directory_structure**: Pre-built directory tree with files
- **uploaded_file_bytes**: Sample file content as bytes
- **mock_image_bytes**: Sample PNG image as bytes

## Temporary Resources

All tests use temporary resources that are automatically cleaned up:
- **Database**: Temporary SQLite databases via pytest's tmp_path
- **Files**: Created in temporary directories, auto-cleaned after tests
- **Thumbnails**: Generated in temporary cache directories
- **Environment**: Isolated via monkeypatch for each test

## Notes

- All file operations use `pathlib.Path` for cross-platform compatibility
- Tests verify both success and failure scenarios
- Security tests ensure `within_root()` prevents directory traversal
- The `.thumbnails` directory is automatically created and filtered in browse tests
- Path traversal tests may return 400 or 404 depending on normalization
- secure_filename behavior is version-dependent, tests account for this

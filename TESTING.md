# LAN Uploader Testing Guide

## Overview

Comprehensive integration tests have been set up for the LAN Uploader application, focusing on database operations, file system operations, thumbnail generation, and security features.

## Test Structure

### Integration Tests (`tests/test_integration.py`)

A comprehensive suite of 30 integration tests covering:

#### 1. DatabaseManager Operations (9 tests)
- `test_init_db_creates_tables` - Database initialization
- `test_index_file_creates_new_record` - File indexing
- `test_index_file_updates_existing_record` - File updates
- `test_search_files_finds_matches` - Search functionality
- `test_search_files_respects_limit` - Query limits
- `test_remove_file_deletes_record` - File deletion
- `test_remove_file_returns_false_for_nonexistent` - Error handling
- `test_remove_directory_deletes_all_files` - Directory deletion
- `test_list_files_returns_files_in_directory` - File listing

#### 2. ThumbnailGenerator Operations (8 tests)
- `test_cache_dir_created` - Cache directory creation
- `test_generate_creates_thumbnail` - Thumbnail generation
- `test_generate_uses_cache` - Cache usage
- `test_generate_with_force_regenerate` - Force regeneration
- `test_generate_returns_none_for_nonexistent_file` - Error handling
- `test_generate_handles_rgba_images` - RGBA/PNG to JPEG conversion
- `test_remove_thumbnail_deletes_cache` - Thumbnail deletion
- `test_clear_cache_removes_all_thumbnails` - Cache clearing

#### 3. File Indexing Workflow (3 tests)
- `test_complete_workflow_text_file` - End-to-end text file workflow
- `test_complete_workflow_image_file` - End-to-end image file workflow
- `test_workflow_with_multiple_files` - Multi-file operations

#### 4. Security Checks (5 tests)
- `test_within_root_accepts_valid_paths` - Valid path acceptance
- `test_within_root_rejects_traversal_attempts` - Path traversal prevention
- `test_within_root_rejects_absolute_paths_outside_root` - Absolute path security
- `test_within_root_handles_symlinks_safely` - Symlink security
- `test_special_filenames` - Filename sanitization

#### 5. Edge Cases (5 tests)
- `test_large_filename` - Long filename handling
- `test_special_characters_in_filename` - Special character handling
- `test_unicode_filename` - Unicode support (Cyrillic, Chinese, Japanese)
- `test_empty_filename_search` - Empty query handling
- `test_duplicate_filepath_handling` - Duplicate prevention

## Running Tests

### Quick Start

```bash
# Install development dependencies
make install-dev

# Run all integration tests
make test-integration

# Run all tests with verbose output
make test-verbose

# Run tests with coverage
make test-cov
```

### Detailed Commands

```bash
# Run all tests
python -m pytest tests/

# Run only integration tests
python -m pytest tests/test_integration.py -v

# Run specific test class
python -m pytest tests/test_integration.py::TestDatabaseManager -v

# Run specific test
python -m pytest tests/test_integration.py::TestDatabaseManager::test_search_files_finds_matches -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html

# View HTML coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Test Features

### Isolation
- Each test uses temporary databases (in-memory SQLite)
- Each test uses temporary file systems (via `tempfile.mkdtemp()`)
- Tests clean up after themselves automatically
- Tests can run in any order

### Real Components
- Tests use actual `DatabaseManager` and `ThumbnailGenerator` classes
- No mocking - real database and file operations
- Real image processing with Pillow
- Real SQLAlchemy sessions

### Security Testing
- Extensive path traversal attack testing
- Validates `within_root()` function prevents escaping upload directory
- Tests symlink handling
- Validates filename sanitization with `secure_filename()`

### Edge Case Coverage
- Unicode filenames (international characters)
- Long filenames (200+ characters)
- Special characters in filenames
- Empty and null values
- Duplicate handling
- Large file operations

## Dependencies

The following dependencies are required for testing (defined in `requirements-dev.txt`):

```
pytest>=7.4.0              # Testing framework
pytest-cov>=4.1.0          # Coverage reporting
pytest-asyncio>=0.21.0     # Async test support
httpx>=0.24.0              # HTTP client for API testing
playwright>=1.40.0         # E2E browser testing
pytest-playwright>=0.4.0   # Playwright integration
black>=23.0.0              # Code formatting
flake8>=6.0.0              # Linting
mypy>=1.5.0                # Type checking
```

## CI/CD Integration

To integrate with CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Install dependencies
  run: |
    pip install -r requirements-dev.txt

- name: Run tests
  run: |
    pytest tests/ --cov=. --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

## Test Output Example

```
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-7.4.3
collected 30 items

tests/test_integration.py::TestDatabaseManager::test_index_file_creates_new_record PASSED [  3%]
tests/test_integration.py::TestDatabaseManager::test_index_file_updates_existing_record PASSED [  6%]
tests/test_integration.py::TestDatabaseManager::test_init_db_creates_tables PASSED [ 10%]
...
tests/test_integration.py::TestEdgeCases::test_unicode_filename PASSED [100%]

============================== 30 passed in 1.93s ===============================
```

## Coverage Goals

Current coverage focuses on:
- ✓ Database operations (models.py)
- ✓ Thumbnail generation (thumbnails.py)
- ✓ Security functions (within_root)
- ✓ File indexing workflow
- ✓ Error handling and edge cases

Future coverage goals:
- API endpoint testing (tests/test_api.py already exists)
- E2E browser testing (tests/test_e2e.py already exists)
- Performance testing
- Load testing

## Troubleshooting

### Common Issues

1. **SQLAlchemy DetachedInstanceError**
   - Ensure objects are queried within an active session
   - Use `session.merge()` or query within context manager

2. **File Permission Errors**
   - Ensure temporary directories have write permissions
   - Clean up test artifacts with `make clean`

3. **Image Processing Errors**
   - Ensure Pillow is installed: `pip install Pillow`
   - Check that test images are valid formats

### Cleanup

```bash
# Clean all test artifacts
make clean

# Manual cleanup
rm -rf .pytest_cache htmlcov .coverage
find . -name "*.pyc" -delete
find . -name "__pycache__" -delete
```

## Contributing

When adding new features:
1. Write integration tests first (TDD)
2. Ensure all existing tests pass
3. Add tests for edge cases and error conditions
4. Update test documentation
5. Maintain test coverage above 80%

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [SQLAlchemy testing](https://docs.sqlalchemy.org/en/20/core/testing.html)
- [Pillow documentation](https://pillow.readthedocs.io/)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)

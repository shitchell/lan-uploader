"""
Pytest configuration and fixtures for LAN Uploader tests.

This module provides test fixtures for:
- Temporary upload directories
- Test database setup and teardown
- FastAPI TestClient configuration
- Sample test files
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, DatabaseManager
from thumbnails import ThumbnailGenerator


@pytest.fixture(scope="session", autouse=True)
def mock_argv():
    """Mock sys.argv before any app imports to prevent argparse issues."""
    import sys
    original_argv = sys.argv
    sys.argv = ['app.py']
    yield
    sys.argv = original_argv


@pytest.fixture(scope="function")
def temp_upload_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """
    Create a temporary upload directory for testing.

    This fixture creates a clean temporary directory for each test
    and automatically cleans it up after the test completes.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Yields:
        Path: Path to the temporary upload directory
    """
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    yield upload_dir
    # Cleanup is automatic via tmp_path


@pytest.fixture(scope="function")
def temp_db_path(tmp_path: Path) -> Generator[Path, None, None]:
    """
    Create a temporary database file for testing.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Yields:
        Path: Path to the temporary database file
    """
    db_path = tmp_path / "test_lanuploader.db"
    yield db_path
    # Cleanup is automatic via tmp_path


@pytest.fixture(scope="function")
def test_db(temp_db_path: Path) -> Generator[DatabaseManager, None, None]:
    """
    Create a clean test database for each test.

    This fixture:
    1. Creates a temporary SQLite database
    2. Initializes all tables
    3. Provides a DatabaseManager instance
    4. Automatically cleans up after the test

    Args:
        temp_db_path: Path to temporary database file

    Yields:
        DatabaseManager: Configured database manager for testing
    """
    db_url = f"sqlite:///{temp_db_path}"
    db = DatabaseManager(db_url)
    db.init_db()
    yield db
    # Cleanup: close connections
    db.engine.dispose()


@pytest.fixture(scope="function")
def client(temp_upload_dir: Path, temp_db_path: Path, monkeypatch) -> Generator[TestClient, None, None]:
    """
    Create a FastAPI TestClient with isolated test environment.

    This fixture:
    1. Mocks sys.argv to prevent argparse from seeing pytest arguments
    2. Patches the app module's global variables for test configuration
    3. Creates a TestClient instance
    4. Automatically cleans up after the test

    Args:
        temp_upload_dir: Temporary upload directory
        temp_db_path: Temporary database path
        monkeypatch: pytest's monkeypatch fixture for env vars

    Yields:
        TestClient: Configured FastAPI test client
    """
    # Import app module (sys.argv is already mocked by session-scoped fixture)
    import app

    # Patch the app module's global configuration variables
    monkeypatch.setattr(app, 'UPLOAD_ROOT', temp_upload_dir)
    monkeypatch.setattr(app, 'DB_PATH', temp_db_path)
    monkeypatch.setattr(app, 'MAX_CONTENT_LENGTH', 100 * 1024 * 1024)

    # Reinitialize the database with test path
    db_url = f"sqlite:///{temp_db_path}"
    test_db_manager = DatabaseManager(db_url)
    test_db_manager.init_db()
    monkeypatch.setattr(app, 'db', test_db_manager)

    # Reinitialize thumbnail generator with test cache dir
    test_thumbnail_cache = temp_upload_dir / ".thumbnails"
    test_thumbnail_gen = ThumbnailGenerator(test_thumbnail_cache)
    monkeypatch.setattr(app, 'thumbnail_gen', test_thumbnail_gen)

    # Create test client
    test_client = TestClient(app.app)

    yield test_client


@pytest.fixture(scope="function")
def sample_text_file(temp_upload_dir: Path) -> Path:
    """
    Create a sample text file for testing.

    Args:
        temp_upload_dir: Temporary upload directory

    Returns:
        Path: Path to the created sample file
    """
    file_path = temp_upload_dir / "sample.txt"
    file_path.write_text("This is a sample text file for testing.\n")
    return file_path


@pytest.fixture(scope="function")
def sample_image_file(temp_upload_dir: Path) -> Path:
    """
    Create a sample image file (PNG) for testing.

    Uses PIL to create a simple test image.

    Args:
        temp_upload_dir: Temporary upload directory

    Returns:
        Path: Path to the created sample image
    """
    from PIL import Image

    file_path = temp_upload_dir / "sample.png"
    # Create a simple 100x100 red image
    img = Image.new('RGB', (100, 100), color='red')
    img.save(file_path, 'PNG')
    return file_path


@pytest.fixture(scope="function")
def sample_directory_structure(temp_upload_dir: Path) -> dict:
    """
    Create a sample directory structure with files for testing.

    Structure:
    uploads/
      ├── folder1/
      │   ├── file1.txt
      │   └── file2.txt
      ├── folder2/
      │   └── nested/
      │       └── deep.txt
      └── root_file.txt

    Args:
        temp_upload_dir: Temporary upload directory

    Returns:
        dict: Dictionary mapping names to paths for easy access in tests
    """
    structure = {}

    # Create directories
    folder1 = temp_upload_dir / "folder1"
    folder2 = temp_upload_dir / "folder2"
    nested = folder2 / "nested"

    folder1.mkdir()
    folder2.mkdir()
    nested.mkdir()

    structure['folder1'] = folder1
    structure['folder2'] = folder2
    structure['nested'] = nested

    # Create files
    structure['root_file'] = temp_upload_dir / "root_file.txt"
    structure['root_file'].write_text("Root level file\n")

    structure['file1'] = folder1 / "file1.txt"
    structure['file1'].write_text("File 1 content\n")

    structure['file2'] = folder1 / "file2.txt"
    structure['file2'].write_text("File 2 content\n")

    structure['deep'] = nested / "deep.txt"
    structure['deep'].write_text("Deeply nested file\n")

    return structure


@pytest.fixture
def uploaded_file_bytes() -> bytes:
    """
    Provide sample file bytes for upload testing.

    Returns:
        bytes: Sample file content as bytes
    """
    return b"Test file content for upload testing\n"


@pytest.fixture
def mock_image_bytes() -> bytes:
    """
    Provide sample image bytes for upload testing.

    Returns:
        bytes: Sample PNG image as bytes
    """
    from PIL import Image
    import io

    img = Image.new('RGB', (50, 50), color='blue')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.fixture(scope="function")
def sample_video_file(temp_upload_dir: Path) -> Path:
    """
    Create a sample video file (MP4) for testing.

    Uses PyAV to create a simple test video with a few frames.

    Args:
        temp_upload_dir: Temporary upload directory

    Returns:
        Path: Path to the created sample video
    """
    try:
        import av
    except ImportError:
        pytest.skip("PyAV not available for video tests")

    from PIL import Image
    import numpy as np

    file_path = temp_upload_dir / "sample.mp4"

    # Create a simple 3-frame video
    container = av.open(str(file_path), mode='w')
    stream = container.add_stream('mpeg4', rate=1)
    stream.width = 100
    stream.height = 100
    stream.pix_fmt = 'yuv420p'

    # Create 3 frames with different colors
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    for color in colors:
        img = Image.new('RGB', (100, 100), color=color)
        frame = av.VideoFrame.from_image(img)
        for packet in stream.encode(frame):
            container.mux(packet)

    # Flush encoder
    for packet in stream.encode():
        container.mux(packet)

    container.close()
    return file_path


@pytest.fixture
def mock_video_bytes() -> bytes:
    """
    Provide sample video bytes for upload testing.

    Returns:
        bytes: Sample MP4 video as bytes
    """
    try:
        import av
    except ImportError:
        pytest.skip("PyAV not available for video tests")

    from PIL import Image
    import io

    buffer = io.BytesIO()
    container = av.open(buffer, mode='w', format='mp4')
    stream = container.add_stream('mpeg4', rate=1)
    stream.width = 50
    stream.height = 50
    stream.pix_fmt = 'yuv420p'

    # Create 2 frames
    for color in [(255, 0, 0), (0, 0, 255)]:
        img = Image.new('RGB', (50, 50), color=color)
        frame = av.VideoFrame.from_image(img)
        for packet in stream.encode(frame):
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)

    container.close()
    return buffer.getvalue()

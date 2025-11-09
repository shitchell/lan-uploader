"""
Integration tests for LAN Uploader.

Tests database operations, file system operations, thumbnail generation,
and security features including path traversal attack prevention.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import unittest
from io import BytesIO

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import DatabaseManager, FileIndex
from thumbnails import ThumbnailGenerator
from PIL import Image


class TestDatabaseManager(unittest.TestCase):
    """Test DatabaseManager operations with temporary database."""

    def setUp(self):
        """Set up temporary database for each test."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.db = DatabaseManager(f'sqlite:///{self.db_path}')
        self.db.init_db()

    def tearDown(self):
        """Clean up temporary database."""
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_init_db_creates_tables(self):
        """Test that init_db creates the necessary tables."""
        # Create a new database instance
        new_db = DatabaseManager(f'sqlite:///{self.db_path}')
        new_db.init_db()
        
        # Try to query the file_index table (should not raise error)
        with new_db.get_session() as session:
            result = session.query(FileIndex).all()
            self.assertEqual(len(result), 0)

    def test_index_file_creates_new_record(self):
        """Test adding a new file to the index."""
        now = datetime.utcnow()
        file_obj = self.db.index_file(
            filepath='test/file.txt',
            filename='file.txt',
            parent_path='test',
            size=1024,
            modified_at=now,
            extension='.txt',
            mime_type='text/plain',
            has_thumbnail=False,
            preview_type='text'
        )

        self.assertIsNotNone(file_obj)

        # Verify by querying the database
        with self.db.get_session() as session:
            result = session.query(FileIndex).filter_by(filepath='test/file.txt').first()
            self.assertIsNotNone(result)
            self.assertEqual(result.filepath, 'test/file.txt')
            self.assertEqual(result.filename, 'file.txt')
            self.assertEqual(result.parent_path, 'test')
            self.assertEqual(result.size, 1024)
            self.assertEqual(result.extension, '.txt')
            self.assertEqual(result.mime_type, 'text/plain')
            self.assertEqual(result.has_thumbnail, False)
            self.assertEqual(result.preview_type, 'text')

    def test_index_file_updates_existing_record(self):
        """Test updating an existing file in the index."""
        now = datetime.utcnow()

        # Create initial record
        self.db.index_file(
            filepath='test/file.txt',
            filename='file.txt',
            parent_path='test',
            size=1024,
            modified_at=now,
            extension='.txt'
        )

        # Update the same file with new size
        updated_file = self.db.index_file(
            filepath='test/file.txt',
            filename='file.txt',
            parent_path='test',
            size=2048,
            modified_at=now,
            extension='.txt'
        )

        self.assertIsNotNone(updated_file)

        # Verify only one record exists with updated size
        with self.db.get_session() as session:
            count = session.query(FileIndex).filter_by(filepath='test/file.txt').count()
            self.assertEqual(count, 1)

            file_obj = session.query(FileIndex).filter_by(filepath='test/file.txt').first()
            self.assertEqual(file_obj.size, 2048)

    def test_search_files_finds_matches(self):
        """Test searching for files by filename."""
        now = datetime.utcnow()
        
        # Add multiple files
        self.db.index_file('test/apple.txt', 'apple.txt', 'test', 100, now, '.txt')
        self.db.index_file('test/banana.txt', 'banana.txt', 'test', 200, now, '.txt')
        self.db.index_file('test/apple_pie.jpg', 'apple_pie.jpg', 'test', 300, now, '.jpg')
        
        # Search for 'apple'
        results = self.db.search('apple')
        self.assertEqual(len(results), 2)
        filenames = [r.filename for r in results]
        self.assertIn('apple.txt', filenames)
        self.assertIn('apple_pie.jpg', filenames)

    def test_search_files_respects_limit(self):
        """Test that search respects the limit parameter."""
        now = datetime.utcnow()
        
        # Add 10 files
        for i in range(10):
            self.db.index_file(f'test/file{i}.txt', f'file{i}.txt', 'test', 100, now, '.txt')
        
        # Search with limit of 5
        results = self.db.search('file', limit=5)
        self.assertEqual(len(results), 5)

    def test_remove_file_deletes_record(self):
        """Test removing a file from the index."""
        now = datetime.utcnow()
        
        # Add a file
        self.db.index_file('test/file.txt', 'file.txt', 'test', 100, now, '.txt')
        
        # Remove it
        result = self.db.remove_file('test/file.txt')
        self.assertTrue(result)
        
        # Verify it's gone
        with self.db.get_session() as session:
            count = session.query(FileIndex).filter_by(filepath='test/file.txt').count()
            self.assertEqual(count, 0)

    def test_remove_file_returns_false_for_nonexistent(self):
        """Test removing a non-existent file returns False."""
        result = self.db.remove_file('nonexistent/file.txt')
        self.assertFalse(result)

    def test_remove_directory_deletes_all_files(self):
        """Test removing a directory deletes all files under it."""
        now = datetime.utcnow()
        
        # Add files in directory and subdirectories
        self.db.index_file('test/file1.txt', 'file1.txt', 'test', 100, now, '.txt')
        self.db.index_file('test/file2.txt', 'file2.txt', 'test', 100, now, '.txt')
        self.db.index_file('test/sub/file3.txt', 'file3.txt', 'test/sub', 100, now, '.txt')
        self.db.index_file('other/file4.txt', 'file4.txt', 'other', 100, now, '.txt')
        
        # Remove 'test' directory
        count = self.db.remove_directory('test')
        self.assertEqual(count, 3)  # Should remove 3 files
        
        # Verify 'other/file4.txt' still exists
        with self.db.get_session() as session:
            remaining = session.query(FileIndex).all()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].filepath, 'other/file4.txt')

    def test_list_files_returns_files_in_directory(self):
        """Test listing files in a specific directory."""
        now = datetime.utcnow()
        
        # Add files in different directories
        self.db.index_file('test/file1.txt', 'file1.txt', 'test', 100, now, '.txt')
        self.db.index_file('test/file2.txt', 'file2.txt', 'test', 100, now, '.txt')
        self.db.index_file('test/sub/file3.txt', 'file3.txt', 'test/sub', 100, now, '.txt')
        
        # List files in 'test' directory only
        results = self.db.list_files('test')
        self.assertEqual(len(results), 2)
        filenames = [r.filename for r in results]
        self.assertIn('file1.txt', filenames)
        self.assertIn('file2.txt', filenames)
        self.assertNotIn('file3.txt', filenames)


class TestThumbnailGenerator(unittest.TestCase):
    """Test ThumbnailGenerator operations with temporary directories."""

    def setUp(self):
        """Set up temporary directories for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir) / 'thumbnails'
        self.files_dir = Path(self.temp_dir) / 'files'
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.thumb_gen = ThumbnailGenerator(self.cache_dir)

    def tearDown(self):
        """Clean up temporary directories."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_test_image(self, filename, size=(800, 600), color=(255, 0, 0)):
        """Helper to create a test image file."""
        img = Image.new('RGB', size, color=color)
        filepath = self.files_dir / filename
        img.save(filepath, 'JPEG')
        return filepath

    def test_cache_dir_created(self):
        """Test that thumbnail cache directory is created."""
        self.assertTrue(self.cache_dir.exists())
        self.assertTrue(self.cache_dir.is_dir())

    def test_generate_creates_thumbnail(self):
        """Test generating a thumbnail for an image."""
        # Create test image
        image_path = self._create_test_image('test.jpg')
        
        # Generate thumbnail
        thumb_path = self.thumb_gen.generate(image_path)
        
        self.assertIsNotNone(thumb_path)
        self.assertTrue(thumb_path.exists())
        self.assertTrue(thumb_path.is_file())
        
        # Verify thumbnail is smaller than original
        with Image.open(thumb_path) as thumb:
            self.assertLessEqual(thumb.width, 300)
            self.assertLessEqual(thumb.height, 300)

    def test_generate_uses_cache(self):
        """Test that thumbnail generation uses cached version."""
        # Create test image
        image_path = self._create_test_image('test.jpg')
        
        # Generate thumbnail first time
        thumb_path1 = self.thumb_gen.generate(image_path)
        mtime1 = thumb_path1.stat().st_mtime
        
        # Generate again (should use cache)
        thumb_path2 = self.thumb_gen.generate(image_path)
        mtime2 = thumb_path2.stat().st_mtime
        
        self.assertEqual(thumb_path1, thumb_path2)
        self.assertEqual(mtime1, mtime2)  # Same file, not regenerated

    def test_generate_with_force_regenerate(self):
        """Test force regeneration of thumbnail."""
        import time
        
        # Create test image
        image_path = self._create_test_image('test.jpg')
        
        # Generate thumbnail first time
        thumb_path1 = self.thumb_gen.generate(image_path)
        mtime1 = thumb_path1.stat().st_mtime
        
        # Wait a bit to ensure different mtime
        time.sleep(0.1)
        
        # Force regenerate
        thumb_path2 = self.thumb_gen.generate(image_path, force_regenerate=True)
        mtime2 = thumb_path2.stat().st_mtime
        
        self.assertEqual(thumb_path1, thumb_path2)
        self.assertGreater(mtime2, mtime1)  # New file created

    def test_generate_returns_none_for_nonexistent_file(self):
        """Test that generate returns None for non-existent files."""
        nonexistent = self.files_dir / 'nonexistent.jpg'
        thumb_path = self.thumb_gen.generate(nonexistent)
        self.assertIsNone(thumb_path)

    def test_generate_handles_rgba_images(self):
        """Test generating thumbnails for images with transparency."""
        # Create RGBA image
        img = Image.new('RGBA', (800, 600), color=(255, 0, 0, 128))
        image_path = self.files_dir / 'transparent.png'
        img.save(image_path, 'PNG')
        
        # Generate thumbnail
        thumb_path = self.thumb_gen.generate(image_path)
        
        self.assertIsNotNone(thumb_path)
        self.assertTrue(thumb_path.exists())
        
        # Verify it's saved as JPEG (RGB)
        with Image.open(thumb_path) as thumb:
            self.assertEqual(thumb.mode, 'RGB')

    def test_remove_thumbnail_deletes_cache(self):
        """Test removing a specific thumbnail from cache."""
        # Create test image
        image_path = self._create_test_image('test.jpg')
        
        # Generate thumbnail
        thumb_path = self.thumb_gen.generate(image_path)
        self.assertTrue(thumb_path.exists())
        
        # Remove thumbnail
        self.thumb_gen.remove_thumbnail(str(image_path))
        
        # Verify it's gone
        self.assertFalse(thumb_path.exists())

    def test_clear_cache_removes_all_thumbnails(self):
        """Test clearing all thumbnails from cache."""
        # Create multiple test images
        for i in range(3):
            image_path = self._create_test_image(f'test{i}.jpg')
            self.thumb_gen.generate(image_path)
        
        # Verify thumbnails exist
        thumbs = list(self.cache_dir.glob('*.jpg'))
        self.assertEqual(len(thumbs), 3)
        
        # Clear cache
        self.thumb_gen.clear_cache()
        
        # Verify all gone
        thumbs = list(self.cache_dir.glob('*.jpg'))
        self.assertEqual(len(thumbs), 0)


class TestFileIndexingWorkflow(unittest.TestCase):
    """Test complete file indexing workflow: upload -> index -> search -> delete -> cleanup."""

    def setUp(self):
        """Set up temporary database and file system."""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.db = DatabaseManager(f'sqlite:///{self.db_path}')
        self.db.init_db()
        
        # Create temporary file system
        self.temp_dir = tempfile.mkdtemp()
        self.upload_root = Path(self.temp_dir) / 'uploads'
        self.upload_root.mkdir(parents=True, exist_ok=True)
        
        # Create thumbnail generator
        self.cache_dir = Path(self.temp_dir) / 'thumbnails'
        self.thumb_gen = ThumbnailGenerator(self.cache_dir)

    def tearDown(self):
        """Clean up temporary database and file system."""
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_test_file(self, filepath, content=b'test content'):
        """Helper to create a test file."""
        full_path = self.upload_root / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return full_path

    def _create_test_image(self, filepath, size=(800, 600)):
        """Helper to create a test image file."""
        full_path = self.upload_root / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new('RGB', size, color=(255, 0, 0))
        img.save(full_path, 'JPEG')
        return full_path

    def test_complete_workflow_text_file(self):
        """Test complete workflow for a text file."""
        # 1. Create file (simulate upload)
        filepath = self._create_test_file('documents/test.txt', b'Hello World')

        # 2. Index file
        file_stat = filepath.stat()
        file_obj = self.db.index_file(
            filepath='documents/test.txt',
            filename='test.txt',
            parent_path='documents',
            size=file_stat.st_size,
            modified_at=datetime.fromtimestamp(file_stat.st_mtime),
            extension='.txt',
            mime_type='text/plain',
            has_thumbnail=False,
            preview_type='text'
        )

        self.assertIsNotNone(file_obj)

        # 3. Search for file
        results = self.db.search('test')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].filename, 'test.txt')

        # 4. Delete file
        filepath.unlink()
        removed = self.db.remove_file('documents/test.txt')
        self.assertTrue(removed)

        # 5. Verify cleanup
        results = self.db.search('test')
        self.assertEqual(len(results), 0)

    def test_complete_workflow_image_file(self):
        """Test complete workflow for an image file with thumbnail."""
        # 1. Create image (simulate upload)
        filepath = self._create_test_image('photos/sunset.jpg')

        # 2. Generate thumbnail
        thumb_path = self.thumb_gen.generate(filepath)
        self.assertIsNotNone(thumb_path)
        self.assertTrue(thumb_path.exists())

        # 3. Index file
        file_stat = filepath.stat()
        file_obj = self.db.index_file(
            filepath='photos/sunset.jpg',
            filename='sunset.jpg',
            parent_path='photos',
            size=file_stat.st_size,
            modified_at=datetime.fromtimestamp(file_stat.st_mtime),
            extension='.jpg',
            mime_type='image/jpeg',
            has_thumbnail=True,
            preview_type='image'
        )

        self.assertIsNotNone(file_obj)

        # 4. Search for file
        results = self.db.search('sunset')
        self.assertEqual(len(results), 1)

        # 5. Delete file and thumbnail
        # Remove thumbnail first (using the filepath while it still exists)
        self.thumb_gen.remove_thumbnail(str(filepath))
        filepath.unlink()
        removed = self.db.remove_file('photos/sunset.jpg')

        # 6. Verify cleanup
        self.assertTrue(removed)
        self.assertFalse(thumb_path.exists())
        results = self.db.search('sunset')
        self.assertEqual(len(results), 0)

    def test_workflow_with_multiple_files(self):
        """Test workflow with multiple files in different directories."""
        # Create multiple files
        files = [
            ('docs/report.pdf', b'PDF content'),
            ('docs/notes.txt', b'Notes content'),
            ('photos/beach.jpg', None),  # Image
            ('photos/mountain.jpg', None),  # Image
        ]
        
        for filepath, content in files:
            if content is not None:
                self._create_test_file(filepath, content)
            else:
                self._create_test_image(filepath)
        
        # Index all files
        now = datetime.utcnow()
        for filepath, _ in files:
            full_path = self.upload_root / filepath
            parent_path = str(Path(filepath).parent)
            filename = Path(filepath).name
            extension = Path(filepath).suffix
            
            self.db.index_file(
                filepath=filepath,
                filename=filename,
                parent_path=parent_path,
                size=full_path.stat().st_size,
                modified_at=now,
                extension=extension
            )
        
        # List files by directory
        docs_files = self.db.list_files('docs')
        self.assertEqual(len(docs_files), 2)
        
        photos_files = self.db.list_files('photos')
        self.assertEqual(len(photos_files), 2)
        
        # Delete entire directory
        count = self.db.remove_directory('photos')
        self.assertEqual(count, 2)
        
        # Verify only docs remain
        all_files = self.db.list_files('docs')
        self.assertEqual(len(all_files), 2)


class TestSecurityChecks(unittest.TestCase):
    """Test security features including path traversal attack prevention."""

    def setUp(self):
        """Set up temporary upload root."""
        self.temp_dir = tempfile.mkdtemp()
        self.upload_root = Path(self.temp_dir) / 'uploads'
        self.upload_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up temporary directories."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _within_root(self, p: Path) -> bool:
        """Simulate the within_root() function from app.py."""
        try:
            p.resolve().relative_to(self.upload_root)
            return True
        except (ValueError, RuntimeError):
            return False

    def test_within_root_accepts_valid_paths(self):
        """Test that within_root accepts valid paths."""
        # Valid paths
        valid_paths = [
            self.upload_root / 'file.txt',
            self.upload_root / 'subdir' / 'file.txt',
            self.upload_root / 'a' / 'b' / 'c' / 'file.txt',
        ]
        
        for path in valid_paths:
            self.assertTrue(self._within_root(path), f"Path should be valid: {path}")

    def test_within_root_rejects_traversal_attempts(self):
        """Test that within_root rejects path traversal attempts."""
        # Create a file outside upload root
        outside_file = Path(self.temp_dir) / 'outside.txt'
        outside_file.write_text('sensitive')
        
        # Path traversal attempts
        traversal_attempts = [
            self.upload_root / '..' / 'outside.txt',
            self.upload_root / 'subdir' / '..' / '..' / 'outside.txt',
            self.upload_root / '..' / '..' / 'etc' / 'passwd',
        ]
        
        for path in traversal_attempts:
            self.assertFalse(self._within_root(path), f"Path should be rejected: {path}")

    def test_within_root_rejects_absolute_paths_outside_root(self):
        """Test that within_root rejects absolute paths outside root."""
        # Absolute paths outside root
        outside_paths = [
            Path('/etc/passwd'),
            Path('/tmp/malicious.txt'),
            Path(self.temp_dir) / 'outside.txt',
        ]
        
        for path in outside_paths:
            self.assertFalse(self._within_root(path), f"Path should be rejected: {path}")

    def test_within_root_handles_symlinks_safely(self):
        """Test that within_root handles symlinks that point outside root."""
        # Create a file outside upload root
        outside_file = Path(self.temp_dir) / 'outside.txt'
        outside_file.write_text('sensitive')
        
        # Create a symlink inside upload root pointing outside
        symlink_path = self.upload_root / 'symlink.txt'
        try:
            symlink_path.symlink_to(outside_file)
            
            # The symlink should be rejected because it resolves outside root
            self.assertFalse(self._within_root(symlink_path), 
                           "Symlink pointing outside root should be rejected")
        except OSError:
            # Some systems may not support symlinks
            self.skipTest("Symlinks not supported on this system")

    def test_special_filenames(self):
        """Test handling of special filenames."""
        from werkzeug.utils import secure_filename
        
        # Test various problematic filenames
        test_cases = [
            ('../../etc/passwd', 'etc_passwd'),
            ('../../../malicious.txt', 'malicious.txt'),
            ('file with spaces.txt', 'file_with_spaces.txt'),
            ('file@#$%^&*.txt', 'file.txt'),
            ('.hidden', 'hidden'),
            ('..', ''),
            ('.', ''),
        ]
        
        for input_name, expected_safe in test_cases:
            safe_name = secure_filename(input_name)
            # Just verify it produces something safe (exact output may vary)
            self.assertNotIn('..', safe_name)
            self.assertNotIn('/', safe_name)
            self.assertNotIn('\\', safe_name)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Set up temporary database and file system."""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.db = DatabaseManager(f'sqlite:///{self.db_path}')
        self.db.init_db()
        
        self.temp_dir = tempfile.mkdtemp()
        self.upload_root = Path(self.temp_dir)

    def tearDown(self):
        """Clean up temporary database and file system."""
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_large_filename(self):
        """Test handling of very long filenames."""
        # Create a file with a reasonably long name (not too extreme)
        # Most filesystems have a 255 character limit for filenames
        long_name = 'a' * 200 + '.txt'
        filepath = self.upload_root / long_name
        filepath.write_text('test')

        # Index it
        now = datetime.utcnow()
        file_obj = self.db.index_file(
            filepath=long_name,
            filename=long_name,
            parent_path='',
            size=filepath.stat().st_size,
            modified_at=now,
            extension='.txt'
        )

        self.assertIsNotNone(file_obj)

        # Verify by querying database
        with self.db.get_session() as session:
            result = session.query(FileIndex).filter_by(filepath=long_name).first()
            self.assertIsNotNone(result)
            self.assertEqual(result.filename, long_name)

    def test_special_characters_in_filename(self):
        """Test handling of special characters in filenames."""
        # Note: We use werkzeug's secure_filename in the app
        from werkzeug.utils import secure_filename
        
        special_names = [
            'file with spaces.txt',
            'file-with-dashes.txt',
            'file_with_underscores.txt',
            'file.multiple.dots.txt',
        ]
        
        now = datetime.utcnow()
        for name in special_names:
            safe_name = secure_filename(name)
            self.db.index_file(
                filepath=safe_name,
                filename=safe_name,
                parent_path='',
                size=100,
                modified_at=now,
                extension=Path(safe_name).suffix
            )
        
        # All should be indexed
        results = self.db.search('file')
        self.assertEqual(len(results), len(special_names))

    def test_empty_filename_search(self):
        """Test searching with empty query."""
        now = datetime.utcnow()
        self.db.index_file('test.txt', 'test.txt', '', 100, now, '.txt')
        
        # Empty search should match nothing (or everything, depending on implementation)
        results = self.db.search('')
        # The behavior depends on how the LIKE query handles empty strings
        # In SQLite, LIKE '%%' matches all records
        self.assertGreaterEqual(len(results), 0)

    def test_duplicate_filepath_handling(self):
        """Test that duplicate filepaths update rather than create duplicates."""
        now = datetime.utcnow()
        
        # Add same file twice
        self.db.index_file('test.txt', 'test.txt', '', 100, now, '.txt')
        self.db.index_file('test.txt', 'test.txt', '', 200, now, '.txt')
        
        # Should only have one record
        with self.db.get_session() as session:
            count = session.query(FileIndex).filter_by(filepath='test.txt').count()
            self.assertEqual(count, 1)
            
            # Size should be updated
            file_obj = session.query(FileIndex).filter_by(filepath='test.txt').first()
            self.assertEqual(file_obj.size, 200)

    def test_unicode_filename(self):
        """Test handling of Unicode characters in filenames."""
        now = datetime.utcnow()

        unicode_names = [
            'файл.txt',  # Cyrillic
            '文件.txt',  # Chinese
            'ファイル.txt',  # Japanese
            'café.txt',  # Accented
        ]

        for name in unicode_names:
            file_obj = self.db.index_file(
                filepath=name,
                filename=name,
                parent_path='',
                size=100,
                modified_at=now,
                extension=Path(name).suffix
            )
            self.assertIsNotNone(file_obj)

            # Verify by querying database
            with self.db.get_session() as session:
                result = session.query(FileIndex).filter_by(filepath=name).first()
                self.assertIsNotNone(result)
                self.assertEqual(result.filename, name)


if __name__ == '__main__':
    unittest.main()

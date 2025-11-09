"""
Database models for LAN Uploader file indexing and search.
"""

from datetime import datetime
from typing import Optional, Callable, Dict, Any
from sqlalchemy import String, Integer, DateTime, Boolean, Index, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class FileIndex(Base):
    """
    Represents an indexed file in the upload directory.
    Supports full-text search and metadata tracking.
    """
    __tablename__ = 'file_index'

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # File identification
    filepath: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False, index=True)
    parent_path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    extension: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # File metadata
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Preview/thumbnail support
    has_thumbnail: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preview_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Create composite index for common queries
    __table_args__ = (
        Index('idx_parent_filename', 'parent_path', 'filename'),
        Index('idx_search', 'filename', 'extension'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary for API responses"""
        return {
            'id': self.id,
            'filepath': self.filepath,
            'filename': self.filename,
            'parent_path': self.parent_path,
            'extension': self.extension,
            'size': self.size,
            'mime_type': self.mime_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'modified_at': self.modified_at.isoformat() if self.modified_at else None,
            'has_thumbnail': self.has_thumbnail,
            'preview_type': self.preview_type,
        }

    def __repr__(self) -> str:
        return f"<FileIndex(id={self.id}, filepath='{self.filepath}')>"


class DatabaseManager:
    """
    Manages database connections and provides helper methods for file indexing.
    Designed to be easily swappable with other backends in the future.
    """

    def __init__(self, db_url: str = 'sqlite:///lanuploader.db'):
        """
        Initialize database connection.

        Args:
            db_url: SQLAlchemy database URL (default: SQLite in current directory)
        """
        self.engine = create_engine(db_url, echo=False)
        self.db_url = db_url

    def init_db(self) -> None:
        """Create all tables if they don't exist"""
        Base.metadata.create_all(self.engine)

    def get_session(self) -> Session:
        """Get a new database session"""
        return Session(self.engine)

    def index_file(self, filepath: str, filename: str, parent_path: str,
                   size: int, modified_at: datetime, extension: str = '',
                   mime_type: Optional[str] = None, has_thumbnail: bool = False,
                   preview_type: Optional[str] = None) -> FileIndex:
        """
        Add or update a file in the index.

        Args:
            filepath: Relative path from upload root
            filename: Just the filename
            parent_path: Parent directory path
            size: File size in bytes
            modified_at: Last modified timestamp
            extension: File extension (with dot)
            mime_type: MIME type of the file
            has_thumbnail: Whether a thumbnail exists
            preview_type: Type of preview (image/video/text/etc)

        Returns:
            The FileIndex object (new or updated)
        """
        with self.get_session() as session:
            # Check if file already exists
            existing = session.query(FileIndex).filter_by(filepath=filepath).first()

            if existing:
                # Update existing record
                existing.filename = filename
                existing.parent_path = parent_path
                existing.size = size
                existing.modified_at = modified_at
                existing.extension = extension
                existing.mime_type = mime_type
                existing.has_thumbnail = has_thumbnail
                existing.preview_type = preview_type
                session.commit()
                return existing
            else:
                # Create new record
                new_file = FileIndex(
                    filepath=filepath,
                    filename=filename,
                    parent_path=parent_path,
                    size=size,
                    modified_at=modified_at,
                    extension=extension,
                    mime_type=mime_type,
                    has_thumbnail=has_thumbnail,
                    preview_type=preview_type,
                )
                session.add(new_file)
                session.commit()
                return new_file

    def remove_file(self, filepath: str) -> bool:
        """
        Remove a file from the index.

        Args:
            filepath: Relative path from upload root

        Returns:
            True if file was found and removed, False otherwise
        """
        with self.get_session() as session:
            file_obj = session.query(FileIndex).filter_by(filepath=filepath).first()
            if file_obj:
                session.delete(file_obj)
                session.commit()
                return True
            return False

    def remove_directory(self, dir_path: str) -> int:
        """
        Remove all files under a directory from the index.

        Args:
            dir_path: Directory path (relative to upload root)

        Returns:
            Number of files removed
        """
        # Ensure path ends with separator for proper prefix matching
        if not dir_path.endswith('/'):
            dir_path += '/'

        with self.get_session() as session:
            count = session.query(FileIndex).filter(
                FileIndex.filepath.startswith(dir_path)
            ).delete(synchronize_session=False)
            session.commit()
            return count

    def search(self, query: str, limit: int = 100) -> list[FileIndex]:
        """
        Search for files by filename.

        Args:
            query: Search query (searches filename)
            limit: Maximum number of results

        Returns:
            List of FileIndex objects matching the query
        """
        with self.get_session() as session:
            results = session.query(FileIndex).filter(
                FileIndex.filename.like(f'%{query}%')
            ).limit(limit).all()
            # Detach from session
            return [session.merge(r) for r in results]

    def list_files(self, parent_path: str = '') -> list[FileIndex]:
        """
        List all files in a specific directory (non-recursive).

        Args:
            parent_path: Directory path (relative to upload root)

        Returns:
            List of FileIndex objects in the directory
        """
        with self.get_session() as session:
            results = session.query(FileIndex).filter_by(
                parent_path=parent_path
            ).order_by(FileIndex.filename).all()
            return [session.merge(r) for r in results]

    def reindex_all(self, root_dir: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> None:
        """
        Rebuild entire index by scanning the filesystem.

        Args:
            root_dir: Root directory to scan
            progress_callback: Optional callback(current, total) for progress updates
        """
        import os
        import mimetypes
        from pathlib import Path

        # Clear existing index
        with self.get_session() as session:
            session.query(FileIndex).delete()
            session.commit()

        # Scan filesystem
        files_to_index = []
        for root, dirs, files in os.walk(root_dir):
            for filename in files:
                filepath_abs = os.path.join(root, filename)
                filepath_rel = os.path.relpath(filepath_abs, root_dir)
                files_to_index.append((filepath_abs, filepath_rel))

        # Index each file
        total = len(files_to_index)
        for i, (filepath_abs, filepath_rel) in enumerate(files_to_index):
            try:
                stat = os.stat(filepath_abs)
                filename = os.path.basename(filepath_rel)
                parent_path = os.path.dirname(filepath_rel)
                extension = Path(filepath_abs).suffix.lower()
                mime_type, _ = mimetypes.guess_type(filepath_abs)

                self.index_file(
                    filepath=filepath_rel,
                    filename=filename,
                    parent_path=parent_path,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    extension=extension,
                    mime_type=mime_type,
                )

                if progress_callback:
                    progress_callback(i + 1, total)
            except Exception as e:
                print(f"Error indexing {filepath_rel}: {e}")
                continue

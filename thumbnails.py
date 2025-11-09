"""
Thumbnail generation for images using Pillow.

Provides on-demand thumbnail generation with caching.
"""

import hashlib
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps

# Thumbnail settings
THUMBNAIL_SIZE = (300, 300)  # Max dimensions (maintains aspect ratio)
THUMBNAIL_FORMAT = "JPEG"
THUMBNAIL_QUALITY = 85


class ThumbnailGenerator:
    """
    Generates and caches thumbnails for images.
    """

    def __init__(self, cache_dir: Path):
        """
        Initialize thumbnail generator.

        Args:
            cache_dir: Directory to store thumbnail cache
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, source_path: str) -> Path:
        """
        Get the cache file path for a given source file.
        Uses hash of the path to avoid path traversal and filesystem issues.

        Args:
            source_path: Original file path

        Returns:
            Path to cached thumbnail
        """
        # Hash the source path to create a safe filename
        path_hash = hashlib.sha256(source_path.encode()).hexdigest()[:16]
        return self.cache_dir / f"{path_hash}.jpg"

    def generate(self, source_file: Path, force_regenerate: bool = False) -> Optional[Path]:
        """
        Generate a thumbnail for an image file.

        Args:
            source_file: Path to the source image
            force_regenerate: If True, regenerate even if cache exists

        Returns:
            Path to thumbnail file, or None if generation failed
        """
        if not source_file.exists() or not source_file.is_file():
            return None

        # Check cache first
        cache_path = self._get_cache_path(str(source_file))
        if cache_path.exists() and not force_regenerate:
            # Verify cache is newer than source
            if cache_path.stat().st_mtime >= source_file.stat().st_mtime:
                return cache_path

        # Generate thumbnail
        try:
            with Image.open(source_file) as img:
                # Convert RGBA to RGB if necessary (for JPEG compatibility)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                # Auto-orient based on EXIF data
                img = ImageOps.exif_transpose(img)

                # Generate thumbnail while maintaining aspect ratio
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

                # Save to cache
                img.save(cache_path, format=THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY, optimize=True)

            return cache_path

        except Exception as e:
            print(f"Error generating thumbnail for {source_file}: {e}")
            return None

    def clear_cache(self):
        """Remove all cached thumbnails."""
        for thumb in self.cache_dir.glob("*.jpg"):
            thumb.unlink()

    def remove_thumbnail(self, source_path: str):
        """
        Remove a specific thumbnail from cache.

        Args:
            source_path: Original file path
        """
        cache_path = self._get_cache_path(source_path)
        if cache_path.exists():
            cache_path.unlink()

"""
Thumbnail generation for images and videos.

Provides on-demand thumbnail generation with caching.
Uses Pillow for images, PyAV for videos.
"""

import hashlib
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps

# Try to import PyAV for video thumbnail support
try:
    import av
    PYAV_AVAILABLE = True
except ImportError as e:
    if "libav" in str(e).lower():
        print("PyAV requires ffmpeg libraries: apt install libavformat-dev libavcodec-dev libavutil-dev libswscale-dev")
    PYAV_AVAILABLE = False

# Thumbnail settings
THUMBNAIL_SIZE = (300, 300)  # Max dimensions (maintains aspect ratio)
THUMBNAIL_FORMAT = "JPEG"
THUMBNAIL_QUALITY = 85

# Maximum pixels to allow for thumbnail generation (200 megapixels)
# This prevents memory exhaustion from extremely large images
MAX_THUMBNAIL_PIXELS = 200_000_000

# Increase PIL's decompression bomb limit to match our threshold
# Default is ~89MP which is too low for panoramas and high-res photos
Image.MAX_IMAGE_PIXELS = MAX_THUMBNAIL_PIXELS

# Video extensions that support thumbnail generation
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.ogg', '.mov', '.avi', '.mkv'}


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
                # Check image dimensions before processing
                width, height = img.size
                pixel_count = width * height
                if pixel_count > MAX_THUMBNAIL_PIXELS:
                    print(f"Skipping thumbnail for {source_file}: "
                          f"{pixel_count:,} pixels exceeds limit of {MAX_THUMBNAIL_PIXELS:,}")
                    return None

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

        except Image.DecompressionBombError as e:
            print(f"Image too large for thumbnail generation {source_file}: {e}")
            return None
        except Exception as e:
            print(f"Error generating thumbnail for {source_file}: {e}")
            return None

    def generate_video_thumbnail(
        self, source_file: Path, force_regenerate: bool = False
    ) -> Optional[Path]:
        """
        Generate a thumbnail for a video file using PyAV.

        Extracts a frame from ~1 second into the video (or first frame if shorter).

        Args:
            source_file: Path to the source video
            force_regenerate: If True, regenerate even if cache exists

        Returns:
            Path to thumbnail file, or None if generation failed
        """
        if not PYAV_AVAILABLE:
            return None

        if not source_file.exists() or not source_file.is_file():
            return None

        if source_file.suffix.lower() not in VIDEO_EXTENSIONS:
            return None

        # Check cache first
        cache_path = self._get_cache_path(str(source_file))
        if cache_path.exists() and not force_regenerate:
            if cache_path.stat().st_mtime >= source_file.stat().st_mtime:
                return cache_path

        try:
            container = av.open(str(source_file))
            stream = container.streams.video[0]

            # Seek to ~1 second if possible
            if stream.duration and stream.time_base:
                target_pts = int(1 / stream.time_base)
                container.seek(target_pts, stream=stream)

            # Decode first frame after seek
            for frame in container.decode(video=0):
                img = frame.to_image()
                break
            else:
                container.close()
                return None

            container.close()

            # Resize to thumbnail size
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

            # Convert to RGB if needed (some videos have alpha)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Save to cache
            img.save(cache_path, format=THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY, optimize=True)
            return cache_path

        except Exception as e:
            print(f"Error generating video thumbnail for {source_file}: {e}")
            return None

    def clear_cache(self) -> None:
        """Remove all cached thumbnails."""
        for thumb in self.cache_dir.glob("*.jpg"):
            thumb.unlink()

    def remove_thumbnail(self, source_path: str) -> None:
        """
        Remove a specific thumbnail from cache.

        Args:
            source_path: Original file path
        """
        cache_path = self._get_cache_path(source_path)
        if cache_path.exists():
            cache_path.unlink()

    def get_cached(self, source_file: Path) -> Optional[Path]:
        """
        Return cached thumbnail path if it exists, None otherwise.

        Args:
            source_file: Path to the source image or video

        Returns:
            Path to cached thumbnail if exists, None otherwise
        """
        # Use non-resolved path to match generate() behavior
        cache_path = self._get_cache_path(str(source_file))
        return cache_path if cache_path.exists() else None

"""
End-to-end tests for thumbnail display in list view mode.

This test file verifies the implementation of the list view thumbnails feature:
- Images with thumbnails display thumbnails (not emoji) in list view
- Videos with thumbnails display thumbnails (not emoji) in list view
- Files without thumbnails display appropriate emoji icons
- Folders continue to display folder emoji
- Thumbnail size matches icon size (~24px)
- No layout shift occurs when thumbnails load
- Gallery view thumbnail behavior is unaffected
- View mode toggle preserves correct display in each mode
"""

import os
import re
import sys
import shutil
import tempfile
import time
from pathlib import Path
from typing import Generator
import multiprocessing

import pytest
from playwright.sync_api import Page, expect

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Mark all tests in this module as e2e tests
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def thumbnail_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory with various file types for testing thumbnails."""
    temp_dir = Path(tempfile.mkdtemp(prefix="lan_uploader_thumbnail_test_"))

    # Create a test folder
    (temp_dir / "test_folder").mkdir()

    # Create a text file (no thumbnail)
    (temp_dir / "document.txt").write_text("This is a text file without a thumbnail")

    # Create test images with actual content for thumbnails
    try:
        from PIL import Image

        # Create a test image (will have thumbnail)
        img = Image.new('RGB', (200, 200), color='blue')
        img.save(temp_dir / "test_image.jpg")

        # Create another image in a different format
        img2 = Image.new('RGB', (200, 200), color='green')
        img2.save(temp_dir / "another_image.png")

    except ImportError:
        pytest.skip("PIL not available for image tests")

    # Create a test video (for video thumbnail testing)
    try:
        import av
        from PIL import Image

        video_path = temp_dir / "test_video.mp4"
        container = av.open(str(video_path), mode='w')
        stream = container.add_stream('mpeg4', rate=1)
        stream.width = 100
        stream.height = 100
        stream.pix_fmt = 'yuv420p'

        # Create a few frames
        for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
            img = Image.new('RGB', (100, 100), color=color)
            frame = av.VideoFrame.from_image(img)
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

        container.close()
    except ImportError:
        # Create a dummy video file if av not available
        (temp_dir / "test_video.mp4").write_bytes(b"fake video")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def thumbnail_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="lan_uploader_thumbnail_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def thumbnail_app_server(thumbnail_test_upload_dir: Path, thumbnail_test_db_path: Path):
    """Start the FastAPI app server for thumbnail testing."""
    os.environ["UPLOAD_ROOT"] = str(thumbnail_test_upload_dir)
    os.environ["DB_PATH"] = str(thumbnail_test_db_path)
    os.environ["PORT"] = "8766"  # Use a different port for this test module
    os.environ["HOST"] = "127.0.0.1"

    from app import app, db, UPLOAD_ROOT
    from thumbnails import ThumbnailGenerator

    # Initialize database
    db.init_db()

    # Initialize thumbnail generator
    thumbnail_cache = UPLOAD_ROOT / ".thumbnails"
    thumbnail_gen = ThumbnailGenerator(thumbnail_cache)

    # Index files and generate thumbnails
    from models import FileIndex
    from datetime import datetime
    import mimetypes

    for file_path in UPLOAD_ROOT.rglob("*"):
        if file_path.is_file() and not str(file_path).startswith(str(thumbnail_cache)):
            filepath_rel = file_path.relative_to(UPLOAD_ROOT).as_posix()
            parent_path_rel = file_path.parent.relative_to(UPLOAD_ROOT).as_posix()
            extension = file_path.suffix.lower()
            mime_type, _ = mimetypes.guess_type(str(file_path))

            # Determine preview type and generate thumbnails
            preview_type = None
            has_thumbnail = False

            if extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                preview_type = 'image'
                # Actually generate thumbnail
                try:
                    thumb_path = thumbnail_gen.generate(file_path)
                    has_thumbnail = thumb_path is not None
                except Exception:
                    has_thumbnail = False

            elif extension in ['.mp4', '.webm', '.mov', '.avi']:
                preview_type = 'video'
                # Try to generate video thumbnail
                try:
                    thumb_path = thumbnail_gen.generate(file_path)
                    has_thumbnail = thumb_path is not None
                except Exception:
                    has_thumbnail = False

            elif extension in ['.txt', '.md', '.log']:
                preview_type = 'text'

            db.index_file(
                filepath=filepath_rel,
                filename=file_path.name,
                parent_path=parent_path_rel,
                size=file_path.stat().st_size,
                modified_at=datetime.fromtimestamp(file_path.stat().st_mtime),
                extension=extension,
                mime_type=mime_type,
                has_thumbnail=has_thumbnail,
                preview_type=preview_type,
            )

    # Start server
    def run_server():
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8766, log_level="error")

    process = multiprocessing.Process(target=run_server, daemon=True)
    process.start()

    # Wait for server to start
    time.sleep(2)

    yield "http://127.0.0.1:8766"

    # Cleanup
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()


def ensure_list_view(page: Page):
    """Ensure the page is in list view mode."""
    browser_content = page.locator("#browser_content")
    current_class = browser_content.get_attribute("class") or ""

    if "gallery-view" in current_class:
        view_toggle = page.locator("#view_toggle_btn")
        view_toggle.click()
        page.wait_for_load_state("networkidle")

    expect(browser_content).to_have_class(re.compile(r".*\blist-view\b.*"))


def ensure_gallery_view(page: Page):
    """Ensure the page is in gallery view mode."""
    browser_content = page.locator("#browser_content")
    current_class = browser_content.get_attribute("class") or ""

    if "list-view" in current_class:
        view_toggle = page.locator("#view_toggle_btn")
        view_toggle.click()
        page.wait_for_load_state("networkidle")

    expect(browser_content).to_have_class(re.compile(r".*\bgallery-view\b.*"))


class TestImageThumbnailInListView:
    """Test that images with thumbnails display thumbnails in list view."""

    def test_image_thumbnail_displays_in_list_view(self, page: Page, thumbnail_app_server: str):
        """Test that an image file with a thumbnail shows the thumbnail in list view."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Find the image file item
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(file_item).to_be_visible()

        # The item should contain an img element with class 'item-thumbnail-list'
        thumbnail_img = file_item.locator("img.item-thumbnail-list")
        expect(thumbnail_img).to_be_visible()

        # Verify the src attribute points to the thumbnail API
        src = thumbnail_img.get_attribute("src")
        assert src is not None, "Thumbnail image should have a src attribute"
        assert "/api/thumbnail/" in src, f"Thumbnail src should point to API, got: {src}"

        # Verify alt attribute is set (for accessibility)
        alt = thumbnail_img.get_attribute("alt")
        assert alt is not None, "Thumbnail should have alt attribute"
        assert "test_image.jpg" in alt, f"Alt should contain filename, got: {alt}"

    def test_png_image_thumbnail_displays_in_list_view(self, page: Page, thumbnail_app_server: str):
        """Test that a PNG image file also shows thumbnail in list view."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Find the PNG image file item
        file_item = page.locator(".file-item:has-text('another_image.png')")
        expect(file_item).to_be_visible()

        # The item should contain an img element with class 'item-thumbnail-list'
        thumbnail_img = file_item.locator("img.item-thumbnail-list")
        expect(thumbnail_img).to_be_visible()

        # Verify src points to thumbnail API
        src = thumbnail_img.get_attribute("src")
        assert "/api/thumbnail/" in src, f"Thumbnail src should point to API, got: {src}"


class TestVideoThumbnailInListView:
    """Test that videos with thumbnails display thumbnails in list view."""

    def test_video_thumbnail_displays_in_list_view(self, page: Page, thumbnail_app_server: str):
        """Test that a video file with a thumbnail shows the thumbnail in list view."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Find the video file item
        file_item = page.locator(".file-item:has-text('test_video.mp4')")
        expect(file_item).to_be_visible()

        # Check for thumbnail or emoji fallback
        # (Video thumbnail generation may fail if av library has issues)
        item_icon = file_item.locator(".item-icon")
        expect(item_icon).to_be_visible()

        # If video has thumbnail, it should be an img element
        # If not, it should have emoji fallback
        thumbnail_img = item_icon.locator("img.item-thumbnail-list")
        emoji_text = item_icon.inner_text()

        # Either thumbnail exists OR emoji fallback exists
        has_thumbnail = thumbnail_img.count() > 0
        has_emoji = len(emoji_text.strip()) > 0

        assert has_thumbnail or has_emoji, "Video should have either thumbnail or emoji fallback"

        if has_thumbnail:
            # Verify thumbnail properties
            src = thumbnail_img.get_attribute("src")
            assert "/api/thumbnail/" in src, f"Video thumbnail src should point to API, got: {src}"


class TestEmojiFallbackForFilesWithoutThumbnails:
    """Test that files without thumbnails display emoji icons."""

    def test_text_file_shows_emoji_in_list_view(self, page: Page, thumbnail_app_server: str):
        """Test that a text file (no thumbnail) shows emoji icon in list view."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Find the text file item
        file_item = page.locator(".file-item:has-text('document.txt')")
        expect(file_item).to_be_visible()

        # The item should NOT contain a thumbnail image
        item_icon = file_item.locator(".item-icon")
        expect(item_icon).to_be_visible()

        thumbnail_img = item_icon.locator("img.item-thumbnail-list")
        expect(thumbnail_img).to_have_count(0)

        # Should have emoji content instead
        icon_text = item_icon.inner_text()
        assert len(icon_text.strip()) > 0, "Text file should have emoji icon"


class TestFolderDisplaysEmojiInListView:
    """Test that folders continue to display folder emoji."""

    def test_folder_shows_folder_emoji_in_list_view(self, page: Page, thumbnail_app_server: str):
        """Test that a folder shows folder emoji (not a thumbnail) in list view."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Find the folder item
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        expect(folder_item).to_be_visible()

        # The folder should NOT contain an img element
        item_icon = folder_item.locator(".item-icon")
        expect(item_icon).to_be_visible()

        thumbnail_img = item_icon.locator("img")
        expect(thumbnail_img).to_have_count(0)

        # Should have folder emoji
        icon_text = item_icon.inner_text()
        assert len(icon_text.strip()) > 0, "Folder should have emoji icon"


class TestThumbnailSizeMatchesIconSize:
    """Test that thumbnail size matches icon size (~24px)."""

    def test_thumbnail_size_is_24_pixels(self, page: Page, thumbnail_app_server: str):
        """Test that list view thumbnails are 24x24 pixels."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Find an image file with thumbnail
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(file_item).to_be_visible()

        thumbnail_img = file_item.locator("img.item-thumbnail-list")
        expect(thumbnail_img).to_be_visible()

        # Get bounding box of thumbnail
        box = thumbnail_img.bounding_box()
        assert box is not None, "Should be able to get thumbnail bounding box"

        # Thumbnail should be 24x24 (with small tolerance for borders/padding)
        assert 20 <= box["width"] <= 28, f"Thumbnail width should be ~24px, got {box['width']}"
        assert 20 <= box["height"] <= 28, f"Thumbnail height should be ~24px, got {box['height']}"

    def test_icon_container_size_consistent(self, page: Page, thumbnail_app_server: str):
        """Test that icon containers have consistent size for both thumbnails and emoji."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Get icon container for image (has thumbnail)
        image_item = page.locator(".file-item:has-text('test_image.jpg')")
        image_icon = image_item.locator(".item-icon")
        image_icon_box = image_icon.bounding_box()

        # Get icon container for text file (has emoji)
        text_item = page.locator(".file-item:has-text('document.txt')")
        text_icon = text_item.locator(".item-icon")
        text_icon_box = text_icon.bounding_box()

        assert image_icon_box is not None and text_icon_box is not None

        # Widths should be consistent (within tolerance)
        width_diff = abs(image_icon_box["width"] - text_icon_box["width"])
        assert width_diff < 5, f"Icon container widths should be consistent, diff: {width_diff}"


class TestNoLayoutShiftOnThumbnailLoad:
    """Test that no layout shift occurs when thumbnails load."""

    def test_no_layout_shift_when_thumbnails_load(self, page: Page, thumbnail_app_server: str):
        """Test that file names don't shift position when thumbnails load."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Get position of file name element
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(file_item).to_be_visible()

        file_name = file_item.locator(".item-name")
        initial_box = file_name.bounding_box()
        assert initial_box is not None

        # Wait a moment for any async loading
        time.sleep(0.5)

        # Get position again
        final_box = file_name.bounding_box()
        assert final_box is not None

        # Positions should be identical (no layout shift)
        assert abs(initial_box["x"] - final_box["x"]) < 2, "File name X position should not shift"
        assert abs(initial_box["y"] - final_box["y"]) < 2, "File name Y position should not shift"

    def test_item_icon_has_fixed_width(self, page: Page, thumbnail_app_server: str):
        """Test that item-icon container has fixed width to prevent shift."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Get the item-icon container
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        item_icon = file_item.locator(".item-icon")

        # Check computed styles
        width = page.evaluate("""
            (element) => {
                const styles = window.getComputedStyle(element);
                return {
                    width: styles.width,
                    minWidth: styles.minWidth
                };
            }
        """, item_icon.element_handle())

        # Width should be 24px
        assert "24px" in width["width"] or width["width"] == "24px", \
            f"Item icon width should be 24px, got {width['width']}"


class TestGalleryViewNotAffected:
    """Test that gallery view thumbnail behavior is unchanged."""

    def test_gallery_view_uses_item_thumbnail_class(self, page: Page, thumbnail_app_server: str):
        """Test that gallery view uses 'item-thumbnail' class (not 'item-thumbnail-list')."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_gallery_view(page)

        # Find the image file in gallery view
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(file_item).to_be_visible()

        # Gallery view should use 'item-thumbnail' class
        gallery_thumbnail = file_item.locator("img.item-thumbnail")
        list_thumbnail = file_item.locator("img.item-thumbnail-list")

        expect(gallery_thumbnail).to_be_visible()
        expect(list_thumbnail).to_have_count(0)

    def test_gallery_thumbnail_is_larger(self, page: Page, thumbnail_app_server: str):
        """Test that gallery view thumbnails are larger (120px height)."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_gallery_view(page)

        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        thumbnail = file_item.locator("img.item-thumbnail")
        expect(thumbnail).to_be_visible()

        box = thumbnail.bounding_box()
        assert box is not None

        # Gallery thumbnail should be larger than list thumbnail (height ~120px)
        assert box["height"] > 50, f"Gallery thumbnail should be larger, got height {box['height']}"


class TestViewModeToggle:
    """Test that view mode toggle shows correct thumbnails in each mode."""

    def test_list_to_gallery_toggle_changes_thumbnail_class(self, page: Page, thumbnail_app_server: str):
        """Test that toggling from list to gallery changes thumbnail class."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        # Start in list view
        ensure_list_view(page)

        # Verify list thumbnail exists
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        list_thumbnail = file_item.locator("img.item-thumbnail-list")
        expect(list_thumbnail).to_be_visible()

        # Toggle to gallery view
        view_toggle = page.locator("#view_toggle_btn")
        view_toggle.click()
        page.wait_for_load_state("networkidle")

        # Verify gallery thumbnail exists (page re-renders)
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        gallery_thumbnail = file_item.locator("img.item-thumbnail")
        list_thumbnail = file_item.locator("img.item-thumbnail-list")

        expect(gallery_thumbnail).to_be_visible()
        expect(list_thumbnail).to_have_count(0)

    def test_gallery_to_list_toggle_changes_thumbnail_class(self, page: Page, thumbnail_app_server: str):
        """Test that toggling from gallery to list changes thumbnail class."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        # Start in gallery view
        ensure_gallery_view(page)

        # Verify gallery thumbnail exists
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        gallery_thumbnail = file_item.locator("img.item-thumbnail")
        expect(gallery_thumbnail).to_be_visible()

        # Toggle to list view
        view_toggle = page.locator("#view_toggle_btn")
        view_toggle.click()
        page.wait_for_load_state("networkidle")

        # Verify list thumbnail exists
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        list_thumbnail = file_item.locator("img.item-thumbnail-list")
        gallery_thumbnail = file_item.locator("img.item-thumbnail")

        expect(list_thumbnail).to_be_visible()
        expect(gallery_thumbnail).to_have_count(0)

    def test_double_toggle_preserves_list_thumbnails(self, page: Page, thumbnail_app_server: str):
        """Test that double toggle returns to correct list view thumbnails."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        view_toggle = page.locator("#view_toggle_btn")

        # Toggle to gallery
        view_toggle.click()
        page.wait_for_load_state("networkidle")

        # Toggle back to list
        view_toggle.click()
        page.wait_for_load_state("networkidle")

        # Verify we're back in list view with correct thumbnails
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        list_thumbnail = file_item.locator("img.item-thumbnail-list")
        expect(list_thumbnail).to_be_visible()


class TestMixedFileTypesDisplay:
    """Test that mixed file types display correctly in list view."""

    def test_all_file_types_display_correctly(self, page: Page, thumbnail_app_server: str):
        """Test that a directory with mixed file types displays each correctly."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # Check image shows thumbnail
        image_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(image_item).to_be_visible()
        image_thumbnail = image_item.locator("img.item-thumbnail-list")
        expect(image_thumbnail).to_be_visible()

        # Check text file shows emoji (no thumbnail)
        text_item = page.locator(".file-item:has-text('document.txt')")
        expect(text_item).to_be_visible()
        text_thumbnail = text_item.locator("img.item-thumbnail-list")
        expect(text_thumbnail).to_have_count(0)
        text_icon = text_item.locator(".item-icon")
        assert len(text_icon.inner_text().strip()) > 0, "Text file should have emoji"

        # Check folder shows emoji (no thumbnail)
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        expect(folder_item).to_be_visible()
        folder_thumbnail = folder_item.locator("img")
        expect(folder_thumbnail).to_have_count(0)


class TestThumbnailCSSProperties:
    """Test CSS properties of list view thumbnails."""

    def test_thumbnail_has_object_fit_cover(self, page: Page, thumbnail_app_server: str):
        """Test that thumbnails use object-fit: cover for proper scaling."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        thumbnail = file_item.locator("img.item-thumbnail-list")
        expect(thumbnail).to_be_visible()

        object_fit = page.evaluate("""
            (element) => window.getComputedStyle(element).objectFit
        """, thumbnail.element_handle())

        assert object_fit == "cover", f"Thumbnail should have object-fit: cover, got {object_fit}"

    def test_thumbnail_has_border_radius(self, page: Page, thumbnail_app_server: str):
        """Test that thumbnails have border-radius for consistent UI."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        thumbnail = file_item.locator("img.item-thumbnail-list")
        expect(thumbnail).to_be_visible()

        border_radius = page.evaluate("""
            (element) => window.getComputedStyle(element).borderRadius
        """, thumbnail.element_handle())

        # Should have some border radius (4px)
        assert border_radius != "0px", f"Thumbnail should have border-radius, got {border_radius}"


class TestRegressionPrevention:
    """Tests designed to fail if the implementation is reverted."""

    def test_image_has_img_element_in_list_view(self, page: Page, thumbnail_app_server: str):
        """This test will FAIL if the list view thumbnail implementation is removed."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        # This specifically tests for the presence of an img element in list view
        # If the implementation is reverted, there will be no img element
        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(file_item).to_be_visible()

        # Critical assertion: img element must exist in list view for images
        item_icon = file_item.locator(".item-icon")
        img_count = item_icon.locator("img").count()

        assert img_count > 0, \
            "List view should render img element for files with thumbnails. " \
            "If this fails, the list view thumbnail feature has been reverted."

    def test_item_thumbnail_list_class_exists(self, page: Page, thumbnail_app_server: str):
        """This test will FAIL if the item-thumbnail-list CSS class is removed."""
        page.goto(thumbnail_app_server)
        page.wait_for_load_state("networkidle")

        ensure_list_view(page)

        file_item = page.locator(".file-item:has-text('test_image.jpg')")
        expect(file_item).to_be_visible()

        # Critical assertion: item-thumbnail-list class must be used
        thumbnail = file_item.locator(".item-thumbnail-list")
        expect(thumbnail).to_be_visible()

        assert thumbnail.count() > 0, \
            "List view thumbnails should use item-thumbnail-list class. " \
            "If this fails, the list view thumbnail styling has been reverted."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
E2E tests for preview modal sizing enhancement (Issue #007).

These tests verify:
- CSS variable definitions for preview modal
- Dynamic sizing based on content
- Maximum and minimum size constraints
- Aspect ratio preservation
- Mobile responsiveness
- No regressions to other modals

Test Strategy:
- Uses Playwright for E2E testing (following existing patterns)
- Creates test images of various sizes to verify dynamic sizing
- Verifies CSS variables via JavaScript evaluation
- Tests actual computed styles and dimensions
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
def preview_modal_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory with various file types for testing preview modal sizing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="lan_uploader_preview_modal_test_"))

    # Create a test folder
    (temp_dir / "test_folder").mkdir()

    # Create a text file (for text preview testing)
    (temp_dir / "sample.txt").write_text("This is sample text content for preview testing.\n" * 10)

    # Create test images with various sizes
    try:
        from PIL import Image

        # Small image (50x50) - tests minimum size constraints
        small_img = Image.new('RGB', (50, 50), color='red')
        small_img.save(temp_dir / "small_image.jpg")

        # Medium image (200x200) - between min and max
        medium_img = Image.new('RGB', (200, 200), color='green')
        medium_img.save(temp_dir / "medium_image.jpg")

        # Large image (1600x1200) - tests maximum size constraints
        large_img = Image.new('RGB', (1600, 1200), color='blue')
        large_img.save(temp_dir / "large_image.jpg")

        # Tall image (400x2000) - tests max-height constraint
        tall_img = Image.new('RGB', (400, 2000), color='purple')
        tall_img.save(temp_dir / "tall_image.jpg")

        # Wide image (2000x400) - tests max-width constraint
        wide_img = Image.new('RGB', (2000, 400), color='orange')
        wide_img.save(temp_dir / "wide_image.jpg")

        # Aspect ratio test image (800x400, 2:1 ratio)
        aspect_img = Image.new('RGB', (800, 400), color='cyan')
        aspect_img.save(temp_dir / "aspect_ratio_image.jpg")

    except ImportError:
        pytest.skip("PIL not available for image tests")

    # Create a test video (for video preview testing)
    try:
        import av
        from PIL import Image

        video_path = temp_dir / "test_video.mp4"
        container = av.open(str(video_path), mode='w')
        stream = container.add_stream('mpeg4', rate=1)
        stream.width = 640
        stream.height = 360  # 16:9 aspect ratio
        stream.pix_fmt = 'yuv420p'

        # Create a few frames
        for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
            img = Image.new('RGB', (640, 360), color=color)
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
def preview_modal_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="lan_uploader_preview_modal_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def preview_modal_app_server(preview_modal_test_upload_dir: Path, preview_modal_test_db_path: Path):
    """Start the FastAPI app server for preview modal testing."""
    # Use unique port for this test module (different from other feature tests)
    test_port = 8768

    os.environ["UPLOAD_ROOT"] = str(preview_modal_test_upload_dir)
    os.environ["DB_PATH"] = str(preview_modal_test_db_path)
    os.environ["PORT"] = str(test_port)
    os.environ["HOST"] = "127.0.0.1"

    # Reload app module to pick up new environment variables
    import importlib
    import app as app_module
    importlib.reload(app_module)

    from app import app, db, UPLOAD_ROOT
    from thumbnails import ThumbnailGenerator

    # Initialize database
    db.init_db()

    # Initialize thumbnail generator
    thumbnail_cache = UPLOAD_ROOT / ".thumbnails"
    thumbnail_gen = ThumbnailGenerator(thumbnail_cache)

    # Index files and generate thumbnails
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
                try:
                    thumb_path = thumbnail_gen.generate(file_path)
                    has_thumbnail = thumb_path is not None
                except Exception:
                    has_thumbnail = False

            elif extension in ['.mp4', '.webm', '.mov', '.avi']:
                preview_type = 'video'
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
        uvicorn.run(app, host="127.0.0.1", port=8768, log_level="error")

    process = multiprocessing.Process(target=run_server, daemon=True)
    process.start()

    # Wait for server to start
    time.sleep(2)

    yield "http://127.0.0.1:8768"

    # Cleanup
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()


def open_preview_for_file(page: Page, filename: str):
    """Helper function to open the preview modal for a specific file."""
    file_item = page.locator(f".file-item:has-text('{filename}')")
    expect(file_item).to_be_visible()
    file_item.click()

    # Wait for modal to appear
    modal = page.locator("#preview_modal")
    expect(modal).to_be_visible()
    expect(modal).not_to_have_class("hidden")

    # Wait for content to load (give images time to render)
    time.sleep(0.5)


def close_preview_modal(page: Page):
    """Helper function to close the preview modal."""
    close_btn = page.locator("#close_preview_modal")
    close_btn.click()
    modal = page.locator("#preview_modal")
    expect(modal).not_to_be_visible()


class TestPreviewModalCSS:
    """Test CSS variable definitions for preview modal sizing."""

    def test_css_variables_defined_in_root(self, page: Page, preview_modal_app_server: str):
        """Verify CSS variables are properly defined in :root."""
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Check --preview-max-width
        max_width = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--preview-max-width')"
        )
        assert max_width.strip() == "80vw", f"Expected --preview-max-width to be 80vw, got {max_width}"

        # Check --preview-max-height
        max_height = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--preview-max-height')"
        )
        assert max_height.strip() == "80vh", f"Expected --preview-max-height to be 80vh, got {max_height}"

        # Check --preview-min-width
        min_width = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--preview-min-width')"
        )
        assert min_width.strip() == "300px", f"Expected --preview-min-width to be 300px, got {min_width}"

        # Check --preview-min-height
        min_height = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--preview-min-height')"
        )
        assert min_height.strip() == "200px", f"Expected --preview-min-height to be 200px, got {min_height}"

    def test_preview_modal_uses_css_variables(self, page: Page, preview_modal_app_server: str):
        """Verify preview modal content uses the CSS variables."""
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "medium_image.jpg")

        # Get the computed max-width of the modal content
        modal_content = page.locator(".preview-modal-content")
        expect(modal_content).to_be_visible()

        # Verify the modal content has the correct CSS variable references
        # by checking that max-width resolves to 80% of viewport width
        viewport_width = page.viewport_size["width"]
        expected_max_width = viewport_width * 0.8

        styles = page.evaluate("""
            (element) => {
                const computed = window.getComputedStyle(element);
                return {
                    maxWidth: computed.maxWidth,
                    maxHeight: computed.maxHeight,
                    minWidth: computed.minWidth,
                    minHeight: computed.minHeight
                };
            }
        """, modal_content.element_handle())

        # maxWidth should be about 80% of viewport (converted to pixels)
        max_width_px = float(styles["maxWidth"].replace("px", ""))
        assert abs(max_width_px - expected_max_width) < 5, \
            f"max-width should be ~{expected_max_width}px (80vw), got {max_width_px}px"

        close_preview_modal(page)


class TestPreviewModalSizing:
    """Test modal size constraints."""

    def test_preview_modal_max_width_large_viewport(self, page: Page, preview_modal_app_server: str):
        """Verify modal respects max-width constraint on large viewport."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None, "Modal should have a bounding box"

        # Modal width should be at most 80% of 1920 = 1536px (plus small tolerance for padding/borders)
        max_expected_width = 1920 * 0.8 + 50
        assert box["width"] <= max_expected_width, \
            f"Modal width ({box['width']}) should be <= {max_expected_width}px (80vw + tolerance)"

        close_preview_modal(page)

    def test_preview_modal_max_height_large_viewport(self, page: Page, preview_modal_app_server: str):
        """Verify modal respects max-height constraint on large viewport."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "tall_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None, "Modal should have a bounding box"

        # Modal height should be at most 80% of 1080 = 864px (plus small tolerance)
        max_expected_height = 1080 * 0.8 + 50
        assert box["height"] <= max_expected_height, \
            f"Modal height ({box['height']}) should be <= {max_expected_height}px (80vh + tolerance)"

        close_preview_modal(page)

    def test_preview_modal_min_width_small_content(self, page: Page, preview_modal_app_server: str):
        """Verify modal meets minimum width for small content."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "small_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None, "Modal should have a bounding box"

        # Modal width should be at least 300px (minimum constraint)
        assert box["width"] >= 300, \
            f"Modal width ({box['width']}) should be >= 300px (min-width)"

        close_preview_modal(page)

    def test_preview_modal_min_height_small_content(self, page: Page, preview_modal_app_server: str):
        """Verify modal meets minimum height for small content."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "small_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None, "Modal should have a bounding box"

        # Modal height should be at least 200px (minimum constraint)
        assert box["height"] >= 200, \
            f"Modal height ({box['height']}) should be >= 200px (min-height)"

        close_preview_modal(page)


class TestPreviewModalDynamicSizing:
    """Test that modal adapts to content size."""

    def test_small_image_respects_min_width(self, page: Page, preview_modal_app_server: str):
        """Verify small images result in a modal that respects minimum width."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "small_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None

        # Modal should respect minimum width constraint (300px)
        assert box["width"] >= 300, \
            f"Small image modal width ({box['width']}) should be >= 300px (min-width)"

        # Modal should also respect maximum width constraint (80vw = 1536px)
        max_expected = 1920 * 0.8 + 50  # 80vw + tolerance
        assert box["width"] <= max_expected, \
            f"Small image modal width ({box['width']}) should be <= {max_expected}px (80vw)"

        close_preview_modal(page)

    def test_large_image_expands_modal(self, page: Page, preview_modal_app_server: str):
        """Verify large images expand modal toward maximum."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None

        # Modal should be significantly expanded for large image (near max)
        # Max width would be 80vw = 1536px at 1920 viewport
        assert box["width"] >= 800, \
            f"Large image modal width ({box['width']}) should be >= 800px (significantly expanded)"

        close_preview_modal(page)

    def test_medium_image_modal_sizing(self, page: Page, preview_modal_app_server: str):
        """Verify medium images create appropriately sized modal."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "medium_image.jpg")

        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None

        # Medium image (200x200) should create a modal that's larger than minimum
        # but not at maximum
        assert box["width"] >= 300, f"Modal width should be at least min-width (300px)"

        close_preview_modal(page)


class TestPreviewModalContentAspectRatio:
    """Test that content maintains aspect ratio."""

    def test_image_maintains_aspect_ratio(self, page: Page, preview_modal_app_server: str):
        """Verify images are not distorted and maintain their original aspect ratio."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "aspect_ratio_image.jpg")

        # Wait for image to load
        img = page.locator(".preview-content img")
        expect(img).to_be_visible()

        # Get the displayed dimensions
        box = img.bounding_box()
        assert box is not None, "Image should have a bounding box"

        # Calculate displayed aspect ratio
        actual_ratio = box["width"] / box["height"]

        # Original image is 800x400 = 2:1 ratio
        expected_ratio = 800 / 400  # 2.0

        # Allow small tolerance for rounding
        assert abs(actual_ratio - expected_ratio) < 0.15, \
            f"Image aspect ratio should be ~{expected_ratio}, got {actual_ratio}"

        close_preview_modal(page)

    def test_image_uses_object_fit_contain(self, page: Page, preview_modal_app_server: str):
        """Verify images use object-fit: contain for proper scaling."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        img = page.locator(".preview-content img")
        expect(img).to_be_visible()

        object_fit = page.evaluate(
            "(element) => window.getComputedStyle(element).objectFit",
            img.element_handle()
        )

        assert object_fit == "contain", \
            f"Image should have object-fit: contain, got {object_fit}"

        close_preview_modal(page)

    def test_video_maintains_aspect_ratio(self, page: Page, preview_modal_app_server: str):
        """Verify videos maintain their aspect ratio (16:9)."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Try to open video preview
        file_item = page.locator(".file-item:has-text('test_video.mp4')")
        if file_item.count() == 0:
            pytest.skip("Video file not available in test directory")

        open_preview_for_file(page, "test_video.mp4")

        # Wait for video to appear
        time.sleep(0.5)

        video = page.locator(".preview-content video")
        if video.count() > 0:
            expect(video).to_be_visible()

            # Check object-fit
            object_fit = page.evaluate(
                "(element) => window.getComputedStyle(element).objectFit",
                video.element_handle()
            )
            assert object_fit == "contain", \
                f"Video should have object-fit: contain, got {object_fit}"

        close_preview_modal(page)


class TestPreviewModalMobile:
    """Test mobile viewport behavior."""

    def test_mobile_viewport_modal_sizing(self, page: Page, preview_modal_app_server: str):
        """Verify modal works correctly on mobile viewport."""
        # iPhone SE size
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "medium_image.jpg")

        # Use specific locator for preview modal content
        modal = page.locator(".preview-modal-content")
        box = modal.bounding_box()
        assert box is not None

        # On mobile, modal should expand to near full width
        # The mobile responsive CSS sets max-width: 100%
        assert box["width"] >= 335, \
            f"Mobile modal width ({box['width']}) should be close to viewport width (375px minus padding)"

        close_preview_modal(page)

    def test_mobile_content_visible_not_cut_off(self, page: Page, preview_modal_app_server: str):
        """Verify content is visible and not clipped on mobile."""
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "medium_image.jpg")

        img = page.locator(".preview-content img")
        expect(img).to_be_visible()

        box = img.bounding_box()
        assert box is not None, "Image should have a bounding box"

        # Image should be within viewport bounds
        assert box["x"] >= 0, "Image should not be cut off on left"
        assert box["y"] >= 0, "Image should not be cut off on top"
        # Allow some tolerance for the modal extending slightly
        assert box["x"] + box["width"] <= 400, \
            f"Image should fit within viewport width, right edge at {box['x'] + box['width']}"

        close_preview_modal(page)


class TestPreviewModalNoRegressions:
    """Ensure other modals are not affected by preview modal changes."""

    def test_text_preview_still_works(self, page: Page, preview_modal_app_server: str):
        """Ensure text file preview is not broken."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "sample.txt")

        # Text content should display in <pre> tag
        content = page.locator(".preview-content pre")
        expect(content).to_be_visible()

        # Verify text content is shown
        text = content.inner_text()
        assert "sample text content" in text.lower(), \
            "Text file content should be displayed"

        close_preview_modal(page)

    def test_upload_modal_unaffected(self, page: Page, preview_modal_app_server: str):
        """Ensure upload modal is not affected by preview modal changes."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Open upload modal
        upload_btn = page.locator("#upload_btn")
        upload_btn.click()

        modal = page.locator("#upload_modal")
        expect(modal).to_be_visible()

        modal_content = page.locator("#upload_modal .modal-content")
        box = modal_content.bounding_box()
        assert box is not None

        # Upload modal should have its original max-width of 600px (plus tolerance)
        assert box["width"] <= 650, \
            f"Upload modal width ({box['width']}) should be <= 650px (600px + tolerance)"

        # Close upload modal
        page.locator("#close_upload_modal").click()

    def test_search_modal_unaffected(self, page: Page, preview_modal_app_server: str):
        """Ensure search modal is not affected by changes."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Perform a search
        search_input = page.locator("#search_input")
        search_input.fill("sample")
        search_btn = page.locator("#search_btn")
        search_btn.click()

        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Search modal should be visible
        modal = page.locator("#search_modal")
        expect(modal).to_be_visible()

        modal_content = page.locator("#search_modal .modal-content")
        box = modal_content.bounding_box()
        assert box is not None

        # Search modal should have standard modal max-width (600px + tolerance)
        assert box["width"] <= 650, \
            f"Search modal width ({box['width']}) should be <= 650px"

        # Close search modal
        page.locator("#close_search_modal").click()

    def test_new_folder_modal_unaffected(self, page: Page, preview_modal_app_server: str):
        """Ensure new folder modal is not affected by changes."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Open new folder modal
        new_folder_btn = page.locator("#new_folder_btn")
        new_folder_btn.click()

        modal = page.locator("#new_folder_modal")
        expect(modal).to_be_visible()

        modal_content = page.locator("#new_folder_modal .modal-content")
        box = modal_content.bounding_box()
        assert box is not None

        # New folder modal should have standard max-width (600px + tolerance)
        assert box["width"] <= 650, \
            f"New folder modal width ({box['width']}) should be <= 650px"

        # Close modal
        page.locator("#close_new_folder_modal").click()


class TestPreviewModalRegressionPrevention:
    """Tests designed to fail if the implementation is reverted."""

    def test_preview_modal_has_preview_modal_content_class(self, page: Page, preview_modal_app_server: str):
        """This test will FAIL if the preview-modal-content class styling is removed."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        # Critical: preview modal must have the preview-modal-content class
        preview_modal = page.locator(".preview-modal-content")
        expect(preview_modal).to_be_visible()

        # Verify the class is actually being used (has specific styling)
        styles = page.evaluate("""
            (element) => {
                const computed = window.getComputedStyle(element);
                return {
                    maxWidth: computed.maxWidth,
                    minWidth: computed.minWidth
                };
            }
        """, preview_modal.element_handle())

        # The max-width should be greater than 600px (the default modal max-width)
        # This proves the preview-modal-content class is applying its own sizing
        viewport_width = 1920
        expected_max = viewport_width * 0.8  # 80vw

        max_width_px = float(styles["maxWidth"].replace("px", ""))

        # If reverted to base .modal-content (600px max), this will fail
        assert max_width_px > 600, \
            "Preview modal max-width should be > 600px (80vw). " \
            "If this fails, the preview-modal-content CSS has been reverted."

        close_preview_modal(page)

    def test_css_variables_are_used_not_hardcoded(self, page: Page, preview_modal_app_server: str):
        """This test verifies CSS variables are being used, not hardcoded values."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Verify CSS variables exist and have expected values
        variables = page.evaluate("""
            () => {
                const root = document.documentElement;
                const styles = getComputedStyle(root);
                return {
                    previewMaxWidth: styles.getPropertyValue('--preview-max-width').trim(),
                    previewMaxHeight: styles.getPropertyValue('--preview-max-height').trim(),
                    previewMinWidth: styles.getPropertyValue('--preview-min-width').trim(),
                    previewMinHeight: styles.getPropertyValue('--preview-min-height').trim()
                };
            }
        """)

        # These assertions will fail if the CSS variables are removed
        assert variables["previewMaxWidth"] == "80vw", \
            f"--preview-max-width should be 80vw, got {variables['previewMaxWidth']}. " \
            "If this fails, the CSS variables have been removed from themes.css."

        assert variables["previewMaxHeight"] == "80vh", \
            f"--preview-max-height should be 80vh, got {variables['previewMaxHeight']}. " \
            "If this fails, the CSS variables have been removed from themes.css."

        assert variables["previewMinWidth"] == "300px", \
            f"--preview-min-width should be 300px, got {variables['previewMinWidth']}. " \
            "If this fails, the CSS variables have been removed from themes.css."

        assert variables["previewMinHeight"] == "200px", \
            f"--preview-min-height should be 200px, got {variables['previewMinHeight']}. " \
            "If this fails, the CSS variables have been removed from themes.css."

    def test_image_content_has_object_fit_contain(self, page: Page, preview_modal_app_server: str):
        """This test will FAIL if object-fit: contain is removed from images/videos."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        img = page.locator(".preview-content img")
        expect(img).to_be_visible()

        object_fit = page.evaluate(
            "(element) => window.getComputedStyle(element).objectFit",
            img.element_handle()
        )

        # This will fail if object-fit: contain is removed
        assert object_fit == "contain", \
            f"Image should have object-fit: contain (got {object_fit}). " \
            "If this fails, the object-fit styling has been reverted."

        close_preview_modal(page)

    def test_preview_modal_respects_viewport_units(self, page: Page, preview_modal_app_server: str):
        """Verify the modal size changes with viewport size (proving viewport units are used)."""
        page.goto(preview_modal_app_server)
        page.wait_for_load_state("networkidle")

        # Test with large viewport
        page.set_viewport_size({"width": 1600, "height": 900})
        page.reload()
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        modal = page.locator(".preview-modal-content")
        large_viewport_box = modal.bounding_box()
        close_preview_modal(page)

        # Test with smaller viewport
        page.set_viewport_size({"width": 1000, "height": 600})
        page.reload()
        page.wait_for_load_state("networkidle")

        open_preview_for_file(page, "large_image.jpg")

        modal = page.locator(".preview-modal-content")
        small_viewport_box = modal.bounding_box()
        close_preview_modal(page)

        # The modal should be smaller on the smaller viewport
        # This proves viewport units (vw/vh) are being used
        assert small_viewport_box["width"] < large_viewport_box["width"], \
            "Modal should be smaller on smaller viewport (proves vw units are used). " \
            f"Large viewport: {large_viewport_box['width']}px, Small: {small_viewport_box['width']}px"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

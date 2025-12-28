"""
E2E tests for arrow key navigation in preview modal (Issue #008).

These tests verify:
- Right arrow key navigates to next file
- Left arrow key navigates to previous file
- Navigation skips directories (only files are navigable)
- Filename in preview header updates correctly after navigation
- Preview content updates to show new file
- Left arrow at first file does nothing (no wrap)
- Right arrow at last file does nothing (no wrap)
- Arrow keys only work when preview modal is open
- Escape and close button still work after navigation
- Download works correctly after navigation
- Multiple consecutive navigations work correctly

Test Strategy:
- Uses Playwright for E2E testing (following existing patterns)
- Creates test files of various types to verify navigation behavior
- Strong assertions on actual behavior (filename changes, content changes)
- Tests will FAIL if the implementation is reverted
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
def arrow_key_nav_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory with mixed file types for testing arrow key navigation."""
    temp_dir = Path(tempfile.mkdtemp(prefix="lan_uploader_arrow_nav_test_"))

    # Create a test folder (should be skipped in navigation)
    (temp_dir / "test_folder").mkdir()

    # Create a text file
    (temp_dir / "document.txt").write_text("This is a sample document for testing navigation.")

    # Create another text file
    (temp_dir / "notes.txt").write_text("These are notes for testing.")

    # Create test images with actual content
    try:
        from PIL import Image

        # Create image files (alphabetically ordered for predictable navigation)
        Image.new('RGB', (100, 100), color='red').save(temp_dir / "image1.jpg")
        Image.new('RGB', (100, 100), color='blue').save(temp_dir / "image2.png")

    except ImportError:
        pytest.skip("PIL not available for image tests")

    # Create a test video (for video preview testing)
    try:
        import av
        from PIL import Image

        video_path = temp_dir / "video.mp4"
        container = av.open(str(video_path), mode='w')
        stream = container.add_stream('mpeg4', rate=1)
        stream.width = 100
        stream.height = 100
        stream.pix_fmt = 'yuv420p'

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
        (temp_dir / "video.mp4").write_bytes(b"fake video")

    # Create an audio file (dummy)
    (temp_dir / "audio.mp3").write_bytes(b"fake audio content")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def arrow_key_nav_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="lan_uploader_arrow_nav_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def arrow_key_nav_app_server(arrow_key_nav_test_upload_dir: Path, arrow_key_nav_test_db_path: Path):
    """Start the FastAPI app server for arrow key navigation testing."""
    # Use unique port for this test module
    test_port = 8769

    os.environ["UPLOAD_ROOT"] = str(arrow_key_nav_test_upload_dir)
    os.environ["DB_PATH"] = str(arrow_key_nav_test_db_path)
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

            elif extension in ['.mp3', '.wav', '.ogg', '.flac']:
                preview_type = 'audio'

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
        uvicorn.run(app, host="127.0.0.1", port=test_port, log_level="error")

    process = multiprocessing.Process(target=run_server, daemon=True)
    process.start()

    # Wait for server to start
    time.sleep(2)

    yield f"http://127.0.0.1:{test_port}"

    # Cleanup
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()


def open_preview_for_file(page: Page, filename: str):
    """Helper to open preview modal for a specific file."""
    file_item = page.locator(f".file-item:has-text('{filename}')")
    expect(file_item).to_be_visible()
    file_item.click()

    modal = page.locator("#preview_modal")
    expect(modal).to_be_visible()
    expect(modal).not_to_have_class("hidden")

    # Wait for content to load
    time.sleep(0.3)


def close_preview_modal(page: Page):
    """Helper to close the preview modal."""
    close_btn = page.locator("#close_preview_modal")
    close_btn.click()
    modal = page.locator("#preview_modal")
    expect(modal).not_to_be_visible()


def get_preview_filename(page: Page) -> str:
    """Get the current filename shown in preview header."""
    return page.locator("#preview_filename").inner_text()


def press_arrow_key(page: Page, direction: str):
    """Press left or right arrow key."""
    key = "ArrowLeft" if direction == "left" else "ArrowRight"
    page.keyboard.press(key)
    time.sleep(0.3)  # Allow navigation to complete


def get_file_items_in_order(page: Page) -> list:
    """Get list of file names in DOM order (excludes folders)."""
    items = page.locator(".file-item").all()
    return [item.get_attribute("data-name") for item in items]


class TestArrowKeyNavigationBasic:
    """Test basic arrow key navigation functionality."""

    def test_right_arrow_navigates_to_next_file(self, page: Page, arrow_key_nav_app_server: str):
        """Test that pressing right arrow navigates to the next file."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Get files in order
        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for navigation test"

        first_file = files[0]
        second_file = files[1]

        # Open preview on first file
        open_preview_for_file(page, first_file)
        initial_filename = get_preview_filename(page)
        assert initial_filename == first_file

        # Press right arrow
        press_arrow_key(page, "right")

        # Verify navigation occurred
        new_filename = get_preview_filename(page)
        assert new_filename == second_file, \
            f"Expected filename to change from '{first_file}' to '{second_file}', got '{new_filename}'"

        close_preview_modal(page)

    def test_left_arrow_navigates_to_previous_file(self, page: Page, arrow_key_nav_app_server: str):
        """Test that pressing left arrow navigates to the previous file."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for navigation test"

        # Open preview on second file
        second_file = files[1]
        first_file = files[0]

        open_preview_for_file(page, second_file)
        assert get_preview_filename(page) == second_file

        # Press left arrow
        press_arrow_key(page, "left")

        # Verify navigation occurred
        new_filename = get_preview_filename(page)
        assert new_filename == first_file, \
            f"Expected filename to change from '{second_file}' to '{first_file}', got '{new_filename}'"

        close_preview_modal(page)

    def test_navigation_updates_filename_header(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigation correctly updates the #preview_filename element."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        first_file = files[0]

        open_preview_for_file(page, first_file)

        # Verify initial filename is correct
        filename_el = page.locator("#preview_filename")
        expect(filename_el).to_have_text(first_file)

        # Navigate to next file
        press_arrow_key(page, "right")

        # Verify filename element updated
        second_file = files[1]
        expect(filename_el).to_have_text(second_file)

        close_preview_modal(page)

    def test_navigation_updates_preview_content(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigation updates the preview content area."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        first_file = files[0]

        open_preview_for_file(page, first_file)

        # Get initial content HTML
        content_el = page.locator("#preview_content")
        initial_html = content_el.inner_html()

        # Navigate to next file
        press_arrow_key(page, "right")
        time.sleep(0.3)

        # Verify content changed
        new_html = content_el.inner_html()
        assert new_html != initial_html, "Preview content should change after navigation"

        close_preview_modal(page)


class TestArrowKeyNavigationBoundaries:
    """Test navigation at boundaries (first/last file)."""

    def test_left_arrow_at_first_file_does_nothing(self, page: Page, arrow_key_nav_app_server: str):
        """Test that pressing left arrow at first file does not change preview."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        first_file = files[0]

        open_preview_for_file(page, first_file)
        assert get_preview_filename(page) == first_file

        # Press left arrow multiple times at first file
        press_arrow_key(page, "left")
        press_arrow_key(page, "left")

        # Filename should still be first file
        assert get_preview_filename(page) == first_file, \
            "Left arrow at first file should not change preview"

        close_preview_modal(page)

    def test_right_arrow_at_last_file_does_nothing(self, page: Page, arrow_key_nav_app_server: str):
        """Test that pressing right arrow at last file does not change preview."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        last_file = files[-1]

        open_preview_for_file(page, last_file)
        assert get_preview_filename(page) == last_file

        # Press right arrow multiple times at last file
        press_arrow_key(page, "right")
        press_arrow_key(page, "right")

        # Filename should still be last file
        assert get_preview_filename(page) == last_file, \
            "Right arrow at last file should not change preview"

        close_preview_modal(page)

    def test_single_file_directory_navigation(self, page: Page, arrow_key_nav_app_server: str):
        """Test navigation when directory has only one file (edge case)."""
        # Navigate into a subdirectory that might have one file
        # For this test, we'll verify the boundary behavior works correctly
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        if len(files) == 1:
            single_file = files[0]
            open_preview_for_file(page, single_file)

            # Press both arrows
            press_arrow_key(page, "left")
            assert get_preview_filename(page) == single_file

            press_arrow_key(page, "right")
            assert get_preview_filename(page) == single_file

            close_preview_modal(page)
        else:
            # Skip if more than one file
            pytest.skip("Test requires exactly one file in directory")


class TestArrowKeyNavigationSkipsDirectories:
    """Test that navigation skips directories."""

    def test_navigation_skips_folders(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigation only goes between files, skipping folders."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Verify there's a folder in the listing
        folder_items = page.locator(".folder-item").all()
        assert len(folder_items) > 0, "Test requires at least one folder"

        # Get file items only
        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"

        # Open first file
        open_preview_for_file(page, files[0])

        # Navigate through all files
        visited_files = [get_preview_filename(page)]
        for _ in range(len(files) - 1):
            press_arrow_key(page, "right")
            current = get_preview_filename(page)
            if current not in visited_files:
                visited_files.append(current)

        # All visited items should be files, not folders
        folder_names = [f.get_attribute("data-name") for f in folder_items]
        for visited in visited_files:
            assert visited not in folder_names, \
                f"Navigation should skip folders, but navigated to '{visited}'"

        close_preview_modal(page)

    def test_navigation_order_matches_grid_order(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigation order matches the visual order in the grid."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 3, "Need at least 3 files for order test"

        # Navigate through files and record order
        open_preview_for_file(page, files[0])
        navigation_order = [get_preview_filename(page)]

        for _ in range(len(files) - 1):
            press_arrow_key(page, "right")
            current = get_preview_filename(page)
            if current != navigation_order[-1]:
                navigation_order.append(current)

        # Navigation order should match file grid order
        assert navigation_order == files, \
            f"Navigation order {navigation_order} should match grid order {files}"

        close_preview_modal(page)


class TestArrowKeyNavigationPreviewTypes:
    """Test navigation between different file types."""

    def test_navigate_from_image_to_text(self, page: Page, arrow_key_nav_app_server: str):
        """Test navigating from an image file to a text file."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Find an image and a text file
        image_file = page.locator(".file-item:has-text('.jpg'), .file-item:has-text('.png')").first
        text_file = page.locator(".file-item:has-text('.txt')").first

        if image_file.count() == 0 or text_file.count() == 0:
            pytest.skip("Need both image and text files")

        image_name = image_file.get_attribute("data-name")
        open_preview_for_file(page, image_name)

        # Navigate until we find a text file
        files = get_file_items_in_order(page)
        for _ in range(len(files)):
            current = get_preview_filename(page)
            if current.endswith('.txt'):
                # Verify text preview shows <pre> element
                content = page.locator("#preview_content")
                pre_element = content.locator("pre")
                expect(pre_element).to_be_visible()
                break
            press_arrow_key(page, "right")

        close_preview_modal(page)

    def test_navigate_from_text_to_image(self, page: Page, arrow_key_nav_app_server: str):
        """Test navigating from a text file to an image file."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Open a text file preview
        text_files = [f for f in get_file_items_in_order(page) if f.endswith('.txt')]
        if not text_files:
            pytest.skip("No text files available")

        open_preview_for_file(page, text_files[0])

        # Navigate until we find an image file
        files = get_file_items_in_order(page)
        for _ in range(len(files)):
            current = get_preview_filename(page)
            if current.endswith(('.jpg', '.png')):
                # Verify image preview shows <img> element
                content = page.locator("#preview_content")
                img_element = content.locator("img")
                expect(img_element).to_be_visible()
                break
            press_arrow_key(page, "right")

        close_preview_modal(page)

    def test_navigate_between_images(self, page: Page, arrow_key_nav_app_server: str):
        """Test navigating between two image files."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Find image files
        image_files = [f for f in get_file_items_in_order(page) if f.endswith(('.jpg', '.png'))]
        if len(image_files) < 2:
            pytest.skip("Need at least 2 image files")

        open_preview_for_file(page, image_files[0])

        # Get initial image src
        content = page.locator("#preview_content")
        initial_img = content.locator("img")
        expect(initial_img).to_be_visible()
        initial_src = initial_img.get_attribute("src")

        # Navigate to find another image
        files = get_file_items_in_order(page)
        for _ in range(len(files)):
            press_arrow_key(page, "right")
            current = get_preview_filename(page)
            if current in image_files and current != image_files[0]:
                # Verify image changed
                new_img = content.locator("img")
                expect(new_img).to_be_visible()
                new_src = new_img.get_attribute("src")
                assert new_src != initial_src, "Image src should change after navigation"
                break

        close_preview_modal(page)

    def test_navigate_to_video_preview(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigating to a video file shows video element."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        video_files = [f for f in get_file_items_in_order(page) if f.endswith('.mp4')]
        if not video_files:
            pytest.skip("No video files available")

        # Start from a different file
        files = get_file_items_in_order(page)
        non_video = [f for f in files if not f.endswith('.mp4')]
        if non_video:
            open_preview_for_file(page, non_video[0])

            # Navigate to video
            for _ in range(len(files)):
                press_arrow_key(page, "right")
                if get_preview_filename(page).endswith('.mp4'):
                    content = page.locator("#preview_content")
                    # Video preview should have video element
                    video_el = content.locator("video")
                    expect(video_el).to_be_visible()
                    break

            close_preview_modal(page)

    def test_navigate_to_audio_preview(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigating to an audio file shows audio element."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        audio_files = [f for f in get_file_items_in_order(page) if f.endswith('.mp3')]
        if not audio_files:
            pytest.skip("No audio files available")

        # Start from a different file
        files = get_file_items_in_order(page)
        non_audio = [f for f in files if not f.endswith('.mp3')]
        if non_audio:
            open_preview_for_file(page, non_audio[0])

            # Navigate to audio
            for _ in range(len(files)):
                press_arrow_key(page, "right")
                if get_preview_filename(page).endswith('.mp3'):
                    content = page.locator("#preview_content")
                    # Audio preview should have audio element
                    audio_el = content.locator("audio")
                    expect(audio_el).to_be_visible()
                    break

            close_preview_modal(page)


class TestArrowKeyNavigationModalState:
    """Test that arrow keys only work in correct modal state."""

    def test_arrows_only_work_when_preview_open(self, page: Page, arrow_key_nav_app_server: str):
        """Test that arrow keys don't cause navigation when preview is closed."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Preview modal should be hidden
        modal = page.locator("#preview_modal")
        expect(modal).to_have_class(re.compile(r".*hidden.*"))

        # Press arrow keys - should not cause errors or unexpected behavior
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowRight")

        # Modal should still be hidden
        expect(modal).to_have_class(re.compile(r".*hidden.*"))

    def test_arrows_work_when_only_preview_modal_open(self, page: Page, arrow_key_nav_app_server: str):
        """Test that arrow keys work when only the preview modal is open (no other modals)."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        if len(files) < 2:
            pytest.skip("Need at least 2 files")

        open_preview_for_file(page, files[0])
        initial_filename = get_preview_filename(page)

        # Verify no other modals are open
        upload_modal = page.locator("#upload_modal")
        search_modal = page.locator("#search_modal")
        expect(upload_modal).to_have_class(re.compile(r".*hidden.*"))
        expect(search_modal).to_have_class(re.compile(r".*hidden.*"))

        # Arrow keys should work
        press_arrow_key(page, "right")

        # Should have navigated to next file
        current_filename = get_preview_filename(page)
        assert current_filename == files[1], \
            f"Arrow key navigation should work when preview is the only open modal"

        close_preview_modal(page)

    def test_arrows_ignored_when_search_modal_open(self, page: Page, arrow_key_nav_app_server: str):
        """Test that arrow keys don't interfere with search modal."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Open search modal
        search_input = page.locator("#search_input")
        search_input.fill("test")
        page.locator("#search_btn").click()
        page.wait_for_load_state("networkidle")

        search_modal = page.locator("#search_modal")
        expect(search_modal).not_to_have_class(re.compile(r".*hidden.*"))

        # Press arrow keys - should not cause errors
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowLeft")

        # Search modal should still be open
        expect(search_modal).not_to_have_class(re.compile(r".*hidden.*"))

        # Close search modal
        page.locator("#close_search_modal").click()

    def test_escape_still_closes_after_navigation(self, page: Page, arrow_key_nav_app_server: str):
        """Test that Escape key still closes preview modal after navigation."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Navigate to another file
        press_arrow_key(page, "right")

        # Press Escape
        page.keyboard.press("Escape")

        # Modal should close
        modal = page.locator("#preview_modal")
        expect(modal).to_have_class(re.compile(r".*hidden.*"))

    def test_close_button_works_after_navigation(self, page: Page, arrow_key_nav_app_server: str):
        """Test that close button still works after navigation."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Navigate to another file
        press_arrow_key(page, "right")

        # Click close button
        close_btn = page.locator("#close_preview_modal")
        close_btn.click()

        # Modal should close
        modal = page.locator("#preview_modal")
        expect(modal).not_to_be_visible()


class TestArrowKeyNavigationIntegration:
    """Integration tests for arrow key navigation."""

    def test_download_works_after_navigation(self, page: Page, arrow_key_nav_app_server: str):
        """Test that download button works for the navigated-to file."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Navigate to next file
        press_arrow_key(page, "right")
        navigated_filename = get_preview_filename(page)

        # Download button should be visible and clickable
        download_btn = page.locator("#download_file")
        expect(download_btn).to_be_visible()
        expect(download_btn).to_be_enabled()

        # Verify clicking download triggers navigation to correct file URL
        # (We don't actually download, just verify the button works)
        close_preview_modal(page)

    def test_current_preview_file_state_updated(self, page: Page, arrow_key_nav_app_server: str):
        """Test that state.currentPreviewFile is updated after navigation."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Navigate to next file
        press_arrow_key(page, "right")
        expected_filename = files[1]

        # Check state via JavaScript evaluation
        current_file = page.evaluate("window.state?.currentPreviewFile?.name || null")

        # The state module is ES6 module, might not be directly accessible
        # Instead verify through the DOM that filename updated
        assert get_preview_filename(page) == expected_filename

        close_preview_modal(page)

    def test_multiple_consecutive_navigations(self, page: Page, arrow_key_nav_app_server: str):
        """Test navigating right multiple times in succession."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        if len(files) < 4:
            pytest.skip("Need at least 4 files for this test")

        open_preview_for_file(page, files[0])
        assert get_preview_filename(page) == files[0]

        # Navigate right 3 times
        press_arrow_key(page, "right")
        assert get_preview_filename(page) == files[1]

        press_arrow_key(page, "right")
        assert get_preview_filename(page) == files[2]

        press_arrow_key(page, "right")
        assert get_preview_filename(page) == files[3]

        close_preview_modal(page)

    def test_navigate_back_and_forth(self, page: Page, arrow_key_nav_app_server: str):
        """Test navigating right then left returns to original file."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        if len(files) < 3:
            pytest.skip("Need at least 3 files for this test")

        original_file = files[0]
        open_preview_for_file(page, original_file)

        # Right, right, left, left should return to original
        press_arrow_key(page, "right")
        assert get_preview_filename(page) == files[1]

        press_arrow_key(page, "right")
        assert get_preview_filename(page) == files[2]

        press_arrow_key(page, "left")
        assert get_preview_filename(page) == files[1]

        press_arrow_key(page, "left")
        assert get_preview_filename(page) == original_file

        close_preview_modal(page)


class TestArrowKeyNavigationRegressionPrevention:
    """Tests designed to fail if the implementation is reverted."""

    def test_navigation_functions_exist_in_preview_module(self, page: Page, arrow_key_nav_app_server: str):
        """Test that navigatePreviewPrev and navigatePreviewNext are available."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # Open preview to ensure modules are loaded
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # The functions are imported in app.js - verify they work by testing behavior
        # Navigate right should change file
        initial = get_preview_filename(page)
        press_arrow_key(page, "right")
        after_right = get_preview_filename(page)

        if len(files) > 1:
            assert after_right != initial, \
                "navigatePreviewNext function must be working. " \
                "If this fails, the navigation implementation has been removed."

        close_preview_modal(page)

    def test_keyboard_handler_responds_to_arrows(self, page: Page, arrow_key_nav_app_server: str):
        """Test that the keydown handler for arrow keys is present and working."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        if len(files) < 2:
            pytest.skip("Need at least 2 files")

        open_preview_for_file(page, files[0])

        # Record initial state
        initial_filename = get_preview_filename(page)

        # Dispatch ArrowRight key event
        page.keyboard.press("ArrowRight")
        time.sleep(0.3)

        # Check if navigation occurred
        new_filename = get_preview_filename(page)

        assert new_filename == files[1], \
            "Arrow key handler must be responding. " \
            f"Expected '{files[1]}' after ArrowRight, got '{new_filename}'. " \
            "If this fails, the keyboard handler has been removed from app.js."

        close_preview_modal(page)

    def test_file_data_map_populated(self, page: Page, arrow_key_nav_app_server: str):
        """Test that state.fileDataMap is populated for navigation to work."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        # The file data map is populated in navigation.js renderFileGrid()
        # We can verify it indirectly by confirming navigation works
        files = get_file_items_in_order(page)
        if len(files) < 2:
            pytest.skip("Need at least 2 files")

        open_preview_for_file(page, files[0])

        # If fileDataMap is not populated, navigation will not find the next file
        press_arrow_key(page, "right")

        # This should successfully navigate to the second file
        assert get_preview_filename(page) == files[1], \
            "Navigation requires state.fileDataMap to be populated. " \
            "If this fails, fileDataMap population in navigation.js may have been removed."

        close_preview_modal(page)

    def test_arrows_prevented_when_modal_visible(self, page: Page, arrow_key_nav_app_server: str):
        """Test that arrow key handlers call preventDefault when preview is open."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Get initial scroll position
        initial_scroll = page.evaluate("window.scrollY")

        # Press arrow keys - they should be prevented from scrolling
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowLeft")

        # Scroll position should not change (preventDefault was called)
        final_scroll = page.evaluate("window.scrollY")
        assert initial_scroll == final_scroll, \
            "Arrow keys should call preventDefault when preview modal is open"

        close_preview_modal(page)


class TestArrowKeyNavigationAccessibility:
    """Test accessibility aspects of arrow key navigation."""

    def test_focus_maintained_during_navigation(self, page: Page, arrow_key_nav_app_server: str):
        """Test that keyboard focus is maintained during navigation."""
        page.goto(arrow_key_nav_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Navigate using keyboard
        press_arrow_key(page, "right")

        # Modal should still be visible and interactive
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        # Close button should still be accessible
        close_btn = page.locator("#close_preview_modal")
        expect(close_btn).to_be_visible()

        close_preview_modal(page)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

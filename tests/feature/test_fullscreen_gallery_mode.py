"""
E2E tests for Fullscreen Gallery Mode (Issue #019).

These tests verify the fullscreen gallery mode feature:
- Fullscreen button exists in preview modal footer
- F key toggles fullscreen mode on/off
- Fullscreen gallery displays content correctly
- Navigation works in fullscreen mode (arrows, buttons, index display)
- Multiple exit methods work (Escape, F key, close button)
- Both images and videos display correctly in fullscreen
- Text files display with proper styling

Test Strategy:
- Uses Playwright for E2E testing (following existing patterns)
- Creates test files of various types to verify fullscreen behavior
- Strong assertions on actual behavior (not just element existence)
- Tests will FAIL if the implementation is reverted

References:
- Commit: 75c5f97d57b75f62c4c098398a957ed2e9577c4c (developer implementation)
- Feature: Fullscreen gallery mode with F key toggle and navigation
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
def fullscreen_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory with mixed file types for fullscreen testing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="fullscreen_test_"))

    # Create a test folder (should be skipped in navigation)
    (temp_dir / "test_folder").mkdir()

    # Create text files (prefixed with letters for predictable sort order)
    (temp_dir / "a_document.txt").write_text("Document A content for testing fullscreen.")
    (temp_dir / "b_notes.txt").write_text("Notes B content for testing.")

    # Create test images with actual content
    try:
        from PIL import Image

        # Create image files (alphabetically ordered for predictable navigation)
        Image.new('RGB', (200, 200), color='red').save(temp_dir / "c_image1.jpg")
        Image.new('RGB', (200, 200), color='blue').save(temp_dir / "d_image2.png")
        Image.new('RGB', (200, 200), color='green').save(temp_dir / "e_image3.jpg")

    except ImportError:
        pytest.skip("PIL not available for image tests")

    # Create a test video
    try:
        import av
        from PIL import Image

        video_path = temp_dir / "f_video.mp4"
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
        (temp_dir / "f_video.mp4").write_bytes(b"fake video")

    # Create an audio file (dummy)
    (temp_dir / "g_audio.mp3").write_bytes(b"fake audio content")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def fullscreen_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="fullscreen_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def fullscreen_app_server(fullscreen_test_upload_dir: Path, fullscreen_test_db_path: Path):
    """Start the FastAPI app server for fullscreen gallery testing."""
    # Use unique port for this test module (8774 as specified in test-plan.md)
    test_port = 8774

    os.environ["UPLOAD_ROOT"] = str(fullscreen_test_upload_dir)
    os.environ["DB_PATH"] = str(fullscreen_test_db_path)
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


# ===== Helper Functions =====

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


def enter_fullscreen_via_button(page: Page):
    """Enter fullscreen mode by clicking the Fullscreen button."""
    fullscreen_btn = page.locator("#fullscreen_btn")
    fullscreen_btn.click()
    time.sleep(0.5)  # Wait for fullscreen transition


def enter_fullscreen_via_key(page: Page):
    """Enter fullscreen mode by pressing F key."""
    page.keyboard.press("f")
    time.sleep(0.5)


def exit_fullscreen_via_escape(page: Page):
    """Exit fullscreen mode by pressing Escape."""
    page.keyboard.press("Escape")
    time.sleep(0.3)


def exit_fullscreen_via_key(page: Page):
    """Exit fullscreen mode by pressing F key again."""
    page.keyboard.press("f")
    time.sleep(0.3)


def exit_fullscreen_via_button(page: Page):
    """Exit fullscreen mode by clicking close button."""
    close_btn = page.locator("#fullscreen_close")
    close_btn.click()
    time.sleep(0.3)


def is_fullscreen_gallery_visible(page: Page) -> bool:
    """Check if fullscreen gallery is visible."""
    gallery = page.locator("#fullscreen_gallery")
    return not gallery.evaluate("el => el.classList.contains('hidden')")


def get_fullscreen_nav_index(page: Page) -> str:
    """Get the navigation index text in fullscreen mode."""
    return page.locator("#fullscreen_nav_index").inner_text()


def get_file_items_in_order(page: Page) -> list:
    """Get list of file names in DOM order (excludes folders)."""
    items = page.locator(".file-item").all()
    return [item.get_attribute("data-name") for item in items]


def get_preview_filename(page: Page) -> str:
    """Get the current filename shown in preview header."""
    return page.locator("#preview_filename").inner_text()


# ===== Test Classes =====

class TestFullscreenButtonElement:
    """Test that Fullscreen button exists and is properly configured."""

    def test_fullscreen_button_visible_in_preview_modal(self, page: Page, fullscreen_app_server: str):
        """Test that Fullscreen button is visible when preview opens."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        fullscreen_btn = page.locator("#fullscreen_btn")
        expect(fullscreen_btn).to_be_visible()
        close_preview_modal(page)

    def test_fullscreen_button_has_correct_text(self, page: Page, fullscreen_app_server: str):
        """Test that button displays 'Fullscreen' text."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        fullscreen_btn = page.locator("#fullscreen_btn")
        expect(fullscreen_btn).to_have_text("Fullscreen")
        close_preview_modal(page)

    def test_fullscreen_button_has_title_attribute(self, page: Page, fullscreen_app_server: str):
        """Test that button has title with keyboard shortcut hint."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        fullscreen_btn = page.locator("#fullscreen_btn")
        expect(fullscreen_btn).to_have_attribute("title", re.compile(r".*F.*"))
        close_preview_modal(page)

    def test_fullscreen_button_position_before_download(self, page: Page, fullscreen_app_server: str):
        """Test that Fullscreen button appears before Download button."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Verify DOM order: fullscreen_btn comes before download_file
        buttons = page.locator(".modal-footer button").all()
        button_ids = [btn.get_attribute("id") for btn in buttons]

        fullscreen_idx = button_ids.index("fullscreen_btn")
        download_idx = button_ids.index("download_file")
        assert fullscreen_idx < download_idx, \
            "Fullscreen button should appear before Download button"

        close_preview_modal(page)


class TestFullscreenEntry:
    """Test entering fullscreen gallery mode."""

    def test_click_button_shows_fullscreen_gallery(self, page: Page, fullscreen_app_server: str):
        """Test that clicking Fullscreen button shows the gallery container."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        enter_fullscreen_via_button(page)

        assert is_fullscreen_gallery_visible(page), \
            "Fullscreen gallery should be visible after clicking button"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_f_key_shows_fullscreen_gallery(self, page: Page, fullscreen_app_server: str):
        """Test that pressing F key shows the gallery container."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        enter_fullscreen_via_key(page)

        assert is_fullscreen_gallery_visible(page), \
            "Fullscreen gallery should be visible after pressing F key"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_fullscreen_shows_content(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen mode displays the file content."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")

        # Open an image file
        image_files = [f for f in get_file_items_in_order(page) if f.endswith(('.jpg', '.png'))]
        open_preview_for_file(page, image_files[0])
        enter_fullscreen_via_button(page)

        # Check that content is displayed
        content = page.locator("#fullscreen_content")
        img = content.locator("img")
        expect(img).to_be_visible()

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_fullscreen_has_dark_background(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen gallery has dark/black background."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        gallery = page.locator("#fullscreen_gallery")
        bg_color = gallery.evaluate("el => window.getComputedStyle(el).backgroundColor")
        # Should be black or very dark (rgb(0, 0, 0))
        assert "0, 0, 0" in bg_color or "rgb(0" in bg_color, \
            f"Expected black background, got {bg_color}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_uppercase_f_key_works(self, page: Page, fullscreen_app_server: str):
        """Test that Shift+F (uppercase F) also toggles fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        page.keyboard.press("F")  # Uppercase
        time.sleep(0.5)

        assert is_fullscreen_gallery_visible(page), \
            "Uppercase F should also toggle fullscreen"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


class TestFullscreenExit:
    """Test exiting fullscreen gallery mode."""

    def test_escape_exits_fullscreen(self, page: Page, fullscreen_app_server: str):
        """Test that pressing Escape exits fullscreen mode."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        assert is_fullscreen_gallery_visible(page)

        exit_fullscreen_via_escape(page)

        assert not is_fullscreen_gallery_visible(page), \
            "Fullscreen gallery should be hidden after pressing Escape"

        # Preview modal should still be open
        modal = page.locator("#preview_modal")
        expect(modal).not_to_have_class("hidden")

        close_preview_modal(page)

    def test_f_key_toggles_off(self, page: Page, fullscreen_app_server: str):
        """Test that pressing F key again exits fullscreen (toggle behavior)."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_key(page)

        assert is_fullscreen_gallery_visible(page)

        exit_fullscreen_via_key(page)

        assert not is_fullscreen_gallery_visible(page), \
            "F key should toggle fullscreen off"

        close_preview_modal(page)

    def test_close_button_exits_fullscreen(self, page: Page, fullscreen_app_server: str):
        """Test that clicking the close button exits fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        assert is_fullscreen_gallery_visible(page)

        exit_fullscreen_via_button(page)

        assert not is_fullscreen_gallery_visible(page), \
            "Close button should exit fullscreen"

        close_preview_modal(page)

    def test_returns_to_preview_modal_after_exit(self, page: Page, fullscreen_app_server: str):
        """Test that exiting fullscreen returns to normal preview modal."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        original_filename = page.locator("#preview_filename").inner_text()

        enter_fullscreen_via_button(page)
        exit_fullscreen_via_escape(page)

        # Preview modal should still be visible with same file
        modal = page.locator("#preview_modal")
        expect(modal).not_to_have_class("hidden")

        current_filename = page.locator("#preview_filename").inner_text()
        assert current_filename == original_filename, \
            "Should return to same file after exiting fullscreen"

        close_preview_modal(page)


class TestFullscreenNavigation:
    """Test navigation controls in fullscreen mode."""

    def test_navigation_controls_visible(self, page: Page, fullscreen_app_server: str):
        """Test that navigation controls are visible in fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        nav_prev = page.locator("#fullscreen_nav_prev")
        nav_next = page.locator("#fullscreen_nav_next")
        nav_index = page.locator("#fullscreen_nav_index")

        expect(nav_prev).to_be_visible()
        expect(nav_next).to_be_visible()
        expect(nav_index).to_be_visible()

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_navigation_index_shows_correct_position(self, page: Page, fullscreen_app_server: str):
        """Test that index display shows correct position."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        index_text = get_fullscreen_nav_index(page)
        assert index_text == f"1/{total}", \
            f"Expected '1/{total}', got '{index_text}'"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_arrow_right_navigates_to_next(self, page: Page, fullscreen_app_server: str):
        """Test that ArrowRight navigates to next file in fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Navigate to next
        page.keyboard.press("ArrowRight")
        time.sleep(0.4)

        index_text = get_fullscreen_nav_index(page)
        assert index_text == f"2/{total}", \
            f"After ArrowRight, expected '2/{total}', got '{index_text}'"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_arrow_left_navigates_to_previous(self, page: Page, fullscreen_app_server: str):
        """Test that ArrowLeft navigates to previous file in fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        assert len(files) >= 2, "Need at least 2 files for this test"
        open_preview_for_file(page, files[1])  # Start at second file
        enter_fullscreen_via_button(page)

        # Navigate to previous
        page.keyboard.press("ArrowLeft")
        time.sleep(0.4)

        index_text = get_fullscreen_nav_index(page)
        assert index_text == f"1/{total}", \
            f"After ArrowLeft, expected '1/{total}', got '{index_text}'"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_click_next_button_navigates(self, page: Page, fullscreen_app_server: str):
        """Test clicking the next button navigates to next file."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Click next button
        page.locator("#fullscreen_nav_next").click()
        time.sleep(0.4)

        index_text = get_fullscreen_nav_index(page)
        assert index_text == f"2/{total}", \
            f"After clicking next, expected '2/{total}', got '{index_text}'"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_click_prev_button_navigates(self, page: Page, fullscreen_app_server: str):
        """Test clicking the prev button navigates to previous file."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        assert len(files) >= 2, "Need at least 2 files for this test"
        open_preview_for_file(page, files[1])  # Start at second
        enter_fullscreen_via_button(page)

        # Click prev button
        page.locator("#fullscreen_nav_prev").click()
        time.sleep(0.4)

        index_text = get_fullscreen_nav_index(page)
        assert index_text == f"1/{total}", \
            f"After clicking prev, expected '1/{total}', got '{index_text}'"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_prev_disabled_at_first_file(self, page: Page, fullscreen_app_server: str):
        """Test that prev button is disabled at first file."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        prev_btn = page.locator("#fullscreen_nav_prev")
        expect(prev_btn).to_be_disabled()

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_next_disabled_at_last_file(self, page: Page, fullscreen_app_server: str):
        """Test that next button is disabled at last file."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[-1])
        enter_fullscreen_via_button(page)

        next_btn = page.locator("#fullscreen_nav_next")
        expect(next_btn).to_be_disabled()

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_navigation_syncs_with_preview_modal(self, page: Page, fullscreen_app_server: str):
        """Test that navigation state syncs between fullscreen and preview modal.

        When navigating in fullscreen mode, the state.currentPreviewFile is updated.
        When exiting fullscreen, re-entering fullscreen should start from the
        correct file (the one we navigated to).
        """
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        assert len(files) >= 3, "Need at least 3 files for this test"
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Navigate to third file
        page.keyboard.press("ArrowRight")
        time.sleep(0.4)
        page.keyboard.press("ArrowRight")
        time.sleep(0.4)

        # Verify we're at third file in fullscreen
        assert get_fullscreen_nav_index(page) == f"3/{total}"

        exit_fullscreen_via_escape(page)

        # Preview modal navigation index should show third file
        # (as the preview navigation UI is updated during fullscreen navigation)
        preview_index = page.locator("#preview_nav_index").inner_text()
        assert preview_index == f"3/{total}", \
            f"Preview modal navigation should show '3/{total}', got '{preview_index}'"

        close_preview_modal(page)


class TestFullscreenContentTypes:
    """Test fullscreen mode with different file types."""

    def test_image_displayed_correctly(self, page: Page, fullscreen_app_server: str):
        """Test that images are displayed correctly in fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        image_files = [f for f in get_file_items_in_order(page) if f.endswith(('.jpg', '.png'))]
        open_preview_for_file(page, image_files[0])
        enter_fullscreen_via_button(page)

        content = page.locator("#fullscreen_content")
        img = content.locator("img")
        expect(img).to_be_visible()

        # Check image has correct styling
        max_width = img.evaluate("el => window.getComputedStyle(el).maxWidth")
        assert "100%" in max_width, f"Image should have max-width: 100%, got {max_width}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_video_displayed_with_controls(self, page: Page, fullscreen_app_server: str):
        """Test that videos are displayed with controls in fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        video_files = [f for f in get_file_items_in_order(page) if f.endswith('.mp4')]
        if not video_files:
            pytest.skip("No video files in test directory")

        open_preview_for_file(page, video_files[0])
        enter_fullscreen_via_button(page)

        content = page.locator("#fullscreen_content")
        video = content.locator("video")
        expect(video).to_be_visible()
        expect(video).to_have_attribute("controls", "")

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_text_file_displayed_in_pre(self, page: Page, fullscreen_app_server: str):
        """Test that text files are displayed in pre element in fullscreen."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        text_files = [f for f in get_file_items_in_order(page) if f.endswith('.txt')]
        open_preview_for_file(page, text_files[0])
        enter_fullscreen_via_button(page)

        content = page.locator("#fullscreen_content")
        pre = content.locator("pre")
        expect(pre).to_be_visible()

        # Check text is light colored on dark background
        color = pre.evaluate("el => window.getComputedStyle(el).color")
        # Should have light text (high RGB values) - typically rgb(255, 255, 255)
        assert "255" in color or "fff" in color.lower() or "rgb(2" in color, \
            f"Text should be light colored, got {color}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


class TestFullscreenAccessibility:
    """Test accessibility features of fullscreen mode."""

    def test_close_button_has_title(self, page: Page, fullscreen_app_server: str):
        """Test that close button has descriptive title."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        close_btn = page.locator("#fullscreen_close")
        expect(close_btn).to_have_attribute("title", re.compile(r".+"))

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_nav_buttons_have_titles(self, page: Page, fullscreen_app_server: str):
        """Test that navigation buttons have descriptive titles."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        prev_btn = page.locator("#fullscreen_nav_prev")
        next_btn = page.locator("#fullscreen_nav_next")
        expect(prev_btn).to_have_attribute("title", re.compile(r".+"))
        expect(next_btn).to_have_attribute("title", re.compile(r".+"))

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_disabled_buttons_have_reduced_opacity(self, page: Page, fullscreen_app_server: str):
        """Test that disabled buttons are visually distinct."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])  # First file
        enter_fullscreen_via_button(page)

        prev_btn = page.locator("#fullscreen_nav_prev")
        opacity = prev_btn.evaluate("el => parseFloat(window.getComputedStyle(el).opacity)")
        assert opacity < 1.0, \
            f"Disabled button should have reduced opacity, got {opacity}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


class TestFullscreenRegressionPrevention:
    """Regression prevention tests for fullscreen gallery mode."""

    def test_fullscreen_button_exists(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen button element exists (regression detection)."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        fullscreen_btn = page.locator("#fullscreen_btn")
        expect(fullscreen_btn).to_be_visible()

        close_preview_modal(page)

    def test_fullscreen_gallery_container_exists(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen gallery container exists (regression detection)."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")

        gallery = page.locator("#fullscreen_gallery")
        # Should exist but be hidden
        expect(gallery).to_have_class(re.compile(r"fullscreen-gallery.*hidden"))

    def test_f_key_handler_functional(self, page: Page, fullscreen_app_server: str):
        """Test that F key handler is wired up (regression detection)."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        page.keyboard.press("f")
        time.sleep(0.5)

        assert is_fullscreen_gallery_visible(page), \
            "F key handler MUST be functional. " \
            "If this fails, the keyboard handler has been removed from app.js."

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_fullscreen_navigation_functions_work(self, page: Page, fullscreen_app_server: str):
        """Test that navigation in fullscreen works (regression detection)."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Verify initial state
        assert get_fullscreen_nav_index(page) == f"1/{total}"

        # Navigate and verify
        page.keyboard.press("ArrowRight")
        time.sleep(0.4)

        assert get_fullscreen_nav_index(page) == f"2/{total}", \
            "Fullscreen navigation MUST update index. " \
            "If this fails, navigateFullscreenNext has been removed from preview.js."

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


class TestFullscreenContentTransition:
    """Test smooth content transitions in fullscreen mode."""

    def test_content_has_opacity_transition(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen content has CSS opacity transition."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        content = page.locator("#fullscreen_content")
        style = content.evaluate("""
            el => {
                const style = window.getComputedStyle(el);
                return {
                    transition: style.transition,
                    transitionProperty: style.transitionProperty
                };
            }
        """)

        transition_str = (style['transition'] + ' ' + style['transitionProperty']).lower()
        has_opacity = 'opacity' in transition_str or 'all' in transition_str

        assert has_opacity, \
            f"Fullscreen content should have opacity transition. Got: {style['transition']}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_content_opacity_returns_to_full_after_navigation(self, page: Page, fullscreen_app_server: str):
        """Test that content opacity returns to 1 after navigation completes."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Navigate to next file
        page.keyboard.press("ArrowRight")
        time.sleep(0.5)  # Wait for full transition

        content = page.locator("#fullscreen_content")
        opacity = content.evaluate("el => parseFloat(window.getComputedStyle(el).opacity)")

        assert opacity == 1.0, \
            f"After navigation transition, opacity should be 1.0, got {opacity}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


class TestFullscreenMultipleTransitions:
    """Test multiple navigation transitions in fullscreen mode."""

    def test_navigate_through_multiple_files(self, page: Page, fullscreen_app_server: str):
        """Test navigating through multiple files in fullscreen mode."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        total = len(files)
        assert len(files) >= 4, "Need at least 4 files"
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Navigate forward through files
        for i in range(3):
            page.keyboard.press("ArrowRight")
            time.sleep(0.4)

        # Should be at 4th file
        assert get_fullscreen_nav_index(page) == f"4/{total}"

        # Navigate backward
        for i in range(3):
            page.keyboard.press("ArrowLeft")
            time.sleep(0.4)

        # Should be back at 1st file
        assert get_fullscreen_nav_index(page) == f"1/{total}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_rapid_navigation_works_correctly(self, page: Page, fullscreen_app_server: str):
        """Test that rapid navigation in fullscreen works without breaking."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        assert len(files) >= 4, "Need at least 4 files"
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        # Rapidly press right arrow 3 times
        for _ in range(3):
            page.keyboard.press("ArrowRight")
            time.sleep(0.1)  # Short delay between presses

        # Wait for transitions to complete
        time.sleep(0.5)

        # Verify we ended up on the correct file
        total = len(files)
        assert get_fullscreen_nav_index(page) == f"4/{total}", \
            "Rapid navigation should end at correct file"

        # Verify gallery is still stable
        assert is_fullscreen_gallery_visible(page)

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


class TestFullscreenGalleryStructure:
    """Test the structure and layout of fullscreen gallery."""

    def test_fullscreen_gallery_has_correct_z_index(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen gallery has high z-index to overlay everything."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        gallery = page.locator("#fullscreen_gallery")
        z_index = gallery.evaluate("el => parseInt(window.getComputedStyle(el).zIndex)")

        # Should be higher than modal (which is typically 1000)
        assert z_index >= 2000, \
            f"Fullscreen gallery z-index should be >= 2000 to overlay modal, got {z_index}"

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)

    def test_fullscreen_gallery_covers_viewport(self, page: Page, fullscreen_app_server: str):
        """Test that fullscreen gallery covers the entire viewport."""
        page.goto(fullscreen_app_server)
        page.wait_for_load_state("networkidle")
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])
        enter_fullscreen_via_button(page)

        gallery = page.locator("#fullscreen_gallery")
        position = gallery.evaluate("el => window.getComputedStyle(el).position")
        assert position == "fixed", f"Gallery should have position: fixed, got {position}"

        # Check dimensions
        dimensions = gallery.evaluate("""
            el => {
                const style = window.getComputedStyle(el);
                return {
                    width: style.width,
                    height: style.height,
                    top: style.top,
                    left: style.left
                };
            }
        """)

        # Should cover full viewport
        assert dimensions['top'] == '0px'
        assert dimensions['left'] == '0px'

        exit_fullscreen_via_escape(page)
        close_preview_modal(page)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

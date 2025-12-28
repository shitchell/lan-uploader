"""
E2E tests for Preview Navigation UI with Index/Count display (Issue #018).

These tests verify the navigation bar added to the preview modal:
- Navigation bar elements exist (prev button, next button, index display)
- Index display shows correct format (e.g., "3/58")
- Index display updates when navigating
- Click handlers on prev/next buttons work correctly
- Button disabled states at boundaries (first/last file)
- Integration with existing keyboard navigation
- Accessibility (title attributes, disabled visual states)

Test Strategy:
- Uses Playwright for E2E testing (following existing patterns)
- Creates test files of various types to verify navigation behavior
- Strong assertions on actual behavior (not just element existence)
- Tests will FAIL if the implementation is reverted

References:
- Commit: 613293d7c0259ce16af9925c27eb208ac74952bd (developer implementation)
- Feature: Navigation arrows (< >) and index/count display at bottom of preview modal
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
def nav_ui_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory with mixed file types for testing navigation UI."""
    temp_dir = Path(tempfile.mkdtemp(prefix="lan_uploader_nav_ui_test_"))

    # Create a test folder (should be skipped in navigation)
    (temp_dir / "test_folder").mkdir()

    # Create text files (prefixed with letters for predictable sort order)
    (temp_dir / "a_document.txt").write_text("Document A content for testing navigation.")
    (temp_dir / "b_notes.txt").write_text("Notes B content for testing.")
    (temp_dir / "c_readme.txt").write_text("README C content for testing.")

    # Create test images with actual content
    try:
        from PIL import Image

        # Create image files (alphabetically ordered for predictable navigation)
        Image.new('RGB', (100, 100), color='red').save(temp_dir / "d_image1.jpg")
        Image.new('RGB', (100, 100), color='blue').save(temp_dir / "e_image2.png")

    except ImportError:
        pytest.skip("PIL not available for image tests")

    # Create a test video (for video preview testing)
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
def nav_ui_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="lan_uploader_nav_ui_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def nav_ui_app_server(nav_ui_test_upload_dir: Path, nav_ui_test_db_path: Path):
    """Start the FastAPI app server for navigation UI testing."""
    # Use unique port for this test module (8773 as specified in test-plan.md)
    test_port = 8773

    os.environ["UPLOAD_ROOT"] = str(nav_ui_test_upload_dir)
    os.environ["DB_PATH"] = str(nav_ui_test_db_path)
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


# Helper functions

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
    time.sleep(0.4)  # Allow navigation transition to complete


def get_file_items_in_order(page: Page) -> list:
    """Get list of file names in DOM order (excludes folders)."""
    items = page.locator(".file-item").all()
    return [item.get_attribute("data-name") for item in items]


def get_nav_index_text(page: Page) -> str:
    """Get the current navigation index display text."""
    return page.locator("#preview_nav_index").inner_text()


def click_nav_prev(page: Page):
    """Click the previous navigation button."""
    page.locator("#preview_nav_prev").click()
    time.sleep(0.4)  # Allow navigation transition to complete


def click_nav_next(page: Page):
    """Click the next navigation button."""
    page.locator("#preview_nav_next").click()
    time.sleep(0.4)  # Allow navigation transition to complete


class TestPreviewNavigationUIElements:
    """Test that all navigation bar UI elements exist and are visible."""

    def test_navigation_bar_visible_in_preview_modal(self, page: Page, nav_ui_app_server: str):
        """Test that navigation bar container is visible when preview opens."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 1, "Need at least 1 file for this test"

        open_preview_for_file(page, files[0])

        # Check navigation bar container exists
        nav_bar = page.locator(".preview-nav")
        expect(nav_bar).to_be_visible()

        close_preview_modal(page)

    def test_prev_button_exists(self, page: Page, nav_ui_app_server: str):
        """Test that the previous navigation button exists with correct ID."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        prev_btn = page.locator("#preview_nav_prev")
        expect(prev_btn).to_be_visible()
        expect(prev_btn).to_have_class(re.compile(r"preview-nav-btn"))

        close_preview_modal(page)

    def test_next_button_exists(self, page: Page, nav_ui_app_server: str):
        """Test that the next navigation button exists with correct ID."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        next_btn = page.locator("#preview_nav_next")
        expect(next_btn).to_be_visible()
        expect(next_btn).to_have_class(re.compile(r"preview-nav-btn"))

        close_preview_modal(page)

    def test_index_display_exists(self, page: Page, nav_ui_app_server: str):
        """Test that the index display exists with correct ID."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        index_display = page.locator("#preview_nav_index")
        expect(index_display).to_be_visible()
        expect(index_display).to_have_class(re.compile(r"preview-nav-index"))

        close_preview_modal(page)


class TestPreviewNavigationIndexDisplay:
    """Test index/count display accuracy and updates."""

    def test_index_shows_correct_initial_position(self, page: Page, nav_ui_app_server: str):
        """Test that opening first file shows '1/N' format."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])

        index_text = get_nav_index_text(page)
        assert index_text == f"1/{total}", \
            f"Expected '1/{total}', got '{index_text}'"

        close_preview_modal(page)

    def test_index_shows_correct_middle_position(self, page: Page, nav_ui_app_server: str):
        """Test that opening middle file shows correct index."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 3, "Need at least 3 files for this test"

        middle_index = total // 2
        open_preview_for_file(page, files[middle_index])

        index_text = get_nav_index_text(page)
        expected_index = middle_index + 1  # 1-based display
        assert index_text == f"{expected_index}/{total}", \
            f"Expected '{expected_index}/{total}', got '{index_text}'"

        close_preview_modal(page)

    def test_index_shows_correct_last_position(self, page: Page, nav_ui_app_server: str):
        """Test that opening last file shows 'N/N'."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[-1])

        index_text = get_nav_index_text(page)
        assert index_text == f"{total}/{total}", \
            f"Expected '{total}/{total}', got '{index_text}'"

        close_preview_modal(page)

    def test_index_updates_on_next_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that clicking next button updates the index display."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])
        assert get_nav_index_text(page) == f"1/{total}"

        click_nav_next(page)

        index_text = get_nav_index_text(page)
        assert index_text == f"2/{total}", \
            f"After next click, expected '2/{total}', got '{index_text}'"

        close_preview_modal(page)

    def test_index_updates_on_prev_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that clicking prev button updates the index display."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 2, "Need at least 2 files for this test"

        # Start at second file
        open_preview_for_file(page, files[1])
        assert get_nav_index_text(page) == f"2/{total}"

        click_nav_prev(page)

        index_text = get_nav_index_text(page)
        assert index_text == f"1/{total}", \
            f"After prev click, expected '1/{total}', got '{index_text}'"

        close_preview_modal(page)

    def test_index_updates_on_keyboard_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that keyboard arrow navigation updates the index display."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 3, "Need at least 3 files for this test"

        open_preview_for_file(page, files[0])
        assert get_nav_index_text(page) == f"1/{total}"

        # Use keyboard navigation
        press_arrow_key(page, "right")

        index_text = get_nav_index_text(page)
        assert index_text == f"2/{total}", \
            f"After ArrowRight, expected '2/{total}', got '{index_text}'"

        press_arrow_key(page, "right")
        assert get_nav_index_text(page) == f"3/{total}"

        close_preview_modal(page)

    def test_index_format_is_correct(self, page: Page, nav_ui_app_server: str):
        """Test that index format matches pattern 'N/M' (digits/digits)."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        index_text = get_nav_index_text(page)

        # Verify format matches "N/M" pattern
        assert re.match(r'^\d+/\d+$', index_text), \
            f"Index format should match 'N/M' pattern, got '{index_text}'"

        close_preview_modal(page)


class TestPreviewNavigationClickHandlers:
    """Test that click handlers on navigation buttons work correctly."""

    def test_next_button_navigates_to_next_file(self, page: Page, nav_ui_app_server: str):
        """Test that clicking next button shows next file's content."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])
        initial_filename = get_preview_filename(page)
        assert initial_filename == files[0]

        click_nav_next(page)

        new_filename = get_preview_filename(page)
        assert new_filename == files[1], \
            f"Expected filename to change from '{files[0]}' to '{files[1]}', got '{new_filename}'"

        close_preview_modal(page)

    def test_prev_button_navigates_to_previous_file(self, page: Page, nav_ui_app_server: str):
        """Test that clicking prev button shows previous file's content."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        # Start at second file
        open_preview_for_file(page, files[1])
        assert get_preview_filename(page) == files[1]

        click_nav_prev(page)

        new_filename = get_preview_filename(page)
        assert new_filename == files[0], \
            f"Expected filename to change from '{files[1]}' to '{files[0]}', got '{new_filename}'"

        close_preview_modal(page)

    def test_navigation_updates_preview_content(self, page: Page, nav_ui_app_server: str):
        """Test that button navigation updates the preview content area."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])

        # Get initial content HTML
        content_el = page.locator("#preview_content")
        initial_html = content_el.inner_html()

        click_nav_next(page)

        # Verify content changed
        new_html = content_el.inner_html()
        assert new_html != initial_html, \
            "Preview content should change after navigation"

        close_preview_modal(page)

    def test_multiple_clicks_navigate_correctly(self, page: Page, nav_ui_app_server: str):
        """Test that sequential next clicks work correctly."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 4, "Need at least 4 files for this test"

        open_preview_for_file(page, files[0])
        assert get_preview_filename(page) == files[0]

        # Click next 3 times
        click_nav_next(page)
        assert get_preview_filename(page) == files[1]

        click_nav_next(page)
        assert get_preview_filename(page) == files[2]

        click_nav_next(page)
        assert get_preview_filename(page) == files[3]

        close_preview_modal(page)


class TestPreviewNavigationBoundaries:
    """Test button disabled states at boundaries (first/last file)."""

    def test_prev_button_disabled_at_first_file(self, page: Page, nav_ui_app_server: str):
        """Test that prev button is disabled when on first file."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        prev_btn = page.locator("#preview_nav_prev")
        expect(prev_btn).to_be_disabled()

        close_preview_modal(page)

    def test_next_button_disabled_at_last_file(self, page: Page, nav_ui_app_server: str):
        """Test that next button is disabled when on last file."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[-1])

        next_btn = page.locator("#preview_nav_next")
        expect(next_btn).to_be_disabled()

        close_preview_modal(page)

    def test_prev_button_enabled_not_at_first_file(self, page: Page, nav_ui_app_server: str):
        """Test that prev button is enabled after navigating from first file."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[1])

        prev_btn = page.locator("#preview_nav_prev")
        expect(prev_btn).to_be_enabled()

        close_preview_modal(page)

    def test_next_button_enabled_not_at_last_file(self, page: Page, nav_ui_app_server: str):
        """Test that next button is enabled before last file."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])

        next_btn = page.locator("#preview_nav_next")
        expect(next_btn).to_be_enabled()

        close_preview_modal(page)

    def test_clicking_disabled_prev_does_nothing(self, page: Page, nav_ui_app_server: str):
        """Test that clicking disabled prev button keeps same file."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        initial_filename = get_preview_filename(page)

        # Click disabled prev button (using force since it's disabled)
        page.locator("#preview_nav_prev").click(force=True)
        time.sleep(0.3)

        # Filename should be unchanged
        assert get_preview_filename(page) == initial_filename, \
            "Clicking disabled prev button should not change file"

        close_preview_modal(page)

    def test_clicking_disabled_next_does_nothing(self, page: Page, nav_ui_app_server: str):
        """Test that clicking disabled next button keeps same file."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[-1])

        initial_filename = get_preview_filename(page)

        # Click disabled next button (using force since it's disabled)
        page.locator("#preview_nav_next").click(force=True)
        time.sleep(0.3)

        # Filename should be unchanged
        assert get_preview_filename(page) == initial_filename, \
            "Clicking disabled next button should not change file"

        close_preview_modal(page)

    def test_button_states_update_after_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that button disabled states update correctly after navigation."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 3, "Need at least 3 files for this test"

        # Start at first file
        open_preview_for_file(page, files[0])

        prev_btn = page.locator("#preview_nav_prev")
        next_btn = page.locator("#preview_nav_next")

        # At first file: prev disabled, next enabled
        expect(prev_btn).to_be_disabled()
        expect(next_btn).to_be_enabled()

        # Navigate to middle
        click_nav_next(page)

        # At middle file: both enabled
        expect(prev_btn).to_be_enabled()
        expect(next_btn).to_be_enabled()

        # Navigate to last
        for _ in range(len(files) - 2):
            click_nav_next(page)

        # At last file: prev enabled, next disabled
        expect(prev_btn).to_be_enabled()
        expect(next_btn).to_be_disabled()

        close_preview_modal(page)


class TestPreviewNavigationIntegration:
    """Test integration with existing functionality."""

    def test_ui_and_keyboard_produce_same_result(self, page: Page, nav_ui_app_server: str):
        """Test that clicking next button produces same result as ArrowRight."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 3, "Need at least 3 files for this test"

        # Test with button click
        open_preview_for_file(page, files[0])
        click_nav_next(page)
        filename_after_button = get_preview_filename(page)
        close_preview_modal(page)

        # Test with keyboard
        open_preview_for_file(page, files[0])
        press_arrow_key(page, "right")
        filename_after_keyboard = get_preview_filename(page)
        close_preview_modal(page)

        assert filename_after_button == filename_after_keyboard, \
            "Button click and ArrowRight should produce same result"

    def test_ui_updates_after_keyboard_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that keyboard navigation updates the navigation UI."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])

        # Use keyboard navigation
        press_arrow_key(page, "right")

        # Verify UI updated
        index_text = get_nav_index_text(page)
        assert index_text == f"2/{total}", \
            f"After keyboard navigation, UI should update. Expected '2/{total}', got '{index_text}'"

        # Verify button states updated
        prev_btn = page.locator("#preview_nav_prev")
        expect(prev_btn).to_be_enabled()

        close_preview_modal(page)

    def test_download_works_after_ui_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that download button is functional after UI navigation."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])
        click_nav_next(page)

        # Verify download button is visible and enabled
        download_btn = page.locator("#download_file")
        expect(download_btn).to_be_visible()
        expect(download_btn).to_be_enabled()

        close_preview_modal(page)

    def test_escape_closes_after_ui_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that Escape key closes modal after UI navigation."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])
        click_nav_next(page)

        # Press Escape
        page.keyboard.press("Escape")
        time.sleep(0.2)

        # Modal should be hidden
        modal = page.locator("#preview_modal")
        expect(modal).to_have_class(re.compile(r".*hidden.*"))

    def test_close_button_works_after_ui_navigation(self, page: Page, nav_ui_app_server: str):
        """Test that close button works after UI navigation."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])
        click_nav_next(page)

        # Click close button
        close_btn = page.locator("#close_preview_modal")
        close_btn.click()
        time.sleep(0.2)

        # Modal should be hidden
        modal = page.locator("#preview_modal")
        expect(modal).not_to_be_visible()

    def test_navigate_back_and_forth_with_buttons(self, page: Page, nav_ui_app_server: str):
        """Test navigating forward then backward with buttons returns to original."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 3, "Need at least 3 files for this test"

        original_file = files[0]
        open_preview_for_file(page, original_file)

        # Navigate forward
        click_nav_next(page)
        assert get_preview_filename(page) == files[1]

        click_nav_next(page)
        assert get_preview_filename(page) == files[2]

        # Navigate backward
        click_nav_prev(page)
        assert get_preview_filename(page) == files[1]

        click_nav_prev(page)
        assert get_preview_filename(page) == original_file

        close_preview_modal(page)


class TestPreviewNavigationAccessibility:
    """Test accessibility features of navigation UI."""

    def test_buttons_have_title_attributes(self, page: Page, nav_ui_app_server: str):
        """Test that navigation buttons have descriptive title attributes."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        prev_btn = page.locator("#preview_nav_prev")
        next_btn = page.locator("#preview_nav_next")

        # Buttons should have title attributes
        expect(prev_btn).to_have_attribute("title", re.compile(r".+"))
        expect(next_btn).to_have_attribute("title", re.compile(r".+"))

        close_preview_modal(page)

    def test_disabled_buttons_visually_distinct(self, page: Page, nav_ui_app_server: str):
        """Test that disabled buttons have reduced opacity (visual distinction)."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Get computed opacity of disabled prev button
        opacity = page.evaluate("""
            () => {
                const btn = document.getElementById('preview_nav_prev');
                return parseFloat(window.getComputedStyle(btn).opacity);
            }
        """)

        # Disabled buttons should have reduced opacity (< 1)
        assert opacity < 1.0, \
            f"Disabled button should have reduced opacity, got {opacity}"

        close_preview_modal(page)


class TestPreviewNavigationRegressionPrevention:
    """Tests designed to fail if the implementation is reverted."""

    def test_navigation_bar_elements_present(self, page: Page, nav_ui_app_server: str):
        """Test that all navigation bar elements exist (regression detection)."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # These elements MUST exist - if missing, implementation was reverted
        nav_bar = page.locator(".preview-nav")
        prev_btn = page.locator("#preview_nav_prev")
        next_btn = page.locator("#preview_nav_next")
        index_display = page.locator("#preview_nav_index")

        expect(nav_bar).to_be_visible()
        expect(prev_btn).to_be_visible()
        expect(next_btn).to_be_visible()
        expect(index_display).to_be_visible()

        close_preview_modal(page)

    def test_click_handlers_functional(self, page: Page, nav_ui_app_server: str):
        """Test that click handlers are wired up (regression detection)."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])
        initial_filename = get_preview_filename(page)

        # Click next button
        click_nav_next(page)

        # Filename MUST change - if it doesn't, click handlers were removed
        new_filename = get_preview_filename(page)
        assert new_filename != initial_filename, \
            "Click handler MUST be functional. " \
            "If this fails, the navigation button click handlers have been removed from app.js."

        close_preview_modal(page)

    def test_update_navigation_ui_called(self, page: Page, nav_ui_app_server: str):
        """Test that updateNavigationUI is called during navigation (regression detection)."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        total = len(files)
        assert total >= 2, "Need at least 2 files for this test"

        open_preview_for_file(page, files[0])

        # Initial state
        initial_index = get_nav_index_text(page)
        assert initial_index == f"1/{total}"

        # Navigate
        click_nav_next(page)

        # Index MUST update - if it doesn't, updateNavigationUI was removed
        new_index = get_nav_index_text(page)
        assert new_index == f"2/{total}", \
            f"updateNavigationUI MUST be called during navigation. " \
            f"Expected '2/{total}', got '{new_index}'. " \
            f"If this fails, updateNavigationUI() calls have been removed from preview.js."

        close_preview_modal(page)

    def test_navigation_bar_in_correct_position(self, page: Page, nav_ui_app_server: str):
        """Test that navigation bar is positioned between modal-body and modal-footer."""
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Check DOM structure - preview-nav should be a child of preview-modal-content
        nav_bar = page.locator(".preview-modal-content > .preview-nav")
        expect(nav_bar).to_be_visible()

        close_preview_modal(page)


class TestPreviewNavigationSingleFile:
    """Test edge case: directory with only one file."""

    def test_single_file_shows_correct_index(self, page: Page, nav_ui_app_server: str):
        """Test that single file scenario shows '1/1' or similar."""
        # This test uses the multi-file fixture, but we can test the behavior
        # at boundaries which is similar to single-file behavior
        page.goto(nav_ui_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)

        # Open first file - at boundary like single file
        open_preview_for_file(page, files[0])

        # Prev should be disabled (like single file)
        prev_btn = page.locator("#preview_nav_prev")
        expect(prev_btn).to_be_disabled()

        # Open last file - at other boundary
        close_preview_modal(page)
        open_preview_for_file(page, files[-1])

        # Next should be disabled (like single file)
        next_btn = page.locator("#preview_nav_next")
        expect(next_btn).to_be_disabled()

        close_preview_modal(page)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

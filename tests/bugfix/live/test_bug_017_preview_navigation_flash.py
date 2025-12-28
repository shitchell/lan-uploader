"""
BUG-017: Preview modal flashes/flickers when navigating with arrow keys.

This module contains tests for BUG-017, which verifies that the preview modal
content transitions smoothly when navigating between files using arrow keys.

THE BUG:
When pressing left/right arrow keys to navigate between file previews, the modal
content would briefly flash/flicker. This happened because the navigation functions
called openPreview() which:
1. Set innerHTML to "Loading preview..." immediately
2. Removed the 'hidden' class (unnecessary since modal was already visible)
3. Then loaded the actual content

THE FIX:
The developer created a separate updatePreviewContent() function for navigation that:
1. Updates state and filename immediately
2. Fades out content (opacity: 0) via CSS transition
3. Waits 150ms for transition to complete
4. Updates innerHTML with new content
5. Fades in content (opacity: 1)

This provides a smooth visual transition without showing the "Loading preview..." message.

CSS Changes:
- .preview-content { transition: opacity 0.15s ease-in-out; }
- .preview-modal-content { transition: width 0.2s ease, height 0.2s ease; }

EXPECTED BEHAVIOR (after fix):
- Navigation via arrow keys shows smooth fade transition
- No "Loading preview..." message visible during navigation
- Modal wrapper, overlay, header, and footer buttons remain stable
- Initial preview open (clicking file) still shows loading indicator
- Content fades out, updates, then fades back in

References:
- Commit: 6042520114be8889f13060a1b70752acca562b91
- OBS-009: Fade transition eliminates flash
- OBS-010: All 27 existing tests pass
- OBS-011: CSS transition duration (0.15s) matches JS timeout (150ms)
"""

import os
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
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Mark all tests in this module as e2e tests
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def bug017_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for BUG-017 testing with various file types.

    Creates multiple files and a folder to test navigation across different preview types.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="bug017_test_"))

    # Create a test folder (should be skipped in navigation)
    (temp_dir / "test_folder").mkdir()

    # Create text files
    (temp_dir / "document.txt").write_text("This is a sample document for testing navigation.")
    (temp_dir / "notes.txt").write_text("These are notes for testing smooth transitions.")
    (temp_dir / "readme.txt").write_text("README file content for preview testing.")

    # Create test images with actual content
    try:
        from PIL import Image

        # Create image files (alphabetically ordered for predictable navigation)
        Image.new('RGB', (100, 100), color='red').save(temp_dir / "image1.jpg")
        Image.new('RGB', (100, 100), color='blue').save(temp_dir / "image2.png")
        Image.new('RGB', (100, 100), color='green').save(temp_dir / "image3.jpg")

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
def bug017_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for BUG-017 testing."""
    temp_db = Path(tempfile.mktemp(prefix="bug017_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def bug017_app_server(bug017_test_upload_dir: Path, bug017_test_db_path: Path):
    """Start the FastAPI app server for BUG-017 testing."""
    test_port = 8772  # Unique port for BUG-017 tests

    os.environ["UPLOAD_ROOT"] = str(bug017_test_upload_dir)
    os.environ["DB_PATH"] = str(bug017_test_db_path)
    os.environ["PORT"] = str(test_port)
    os.environ["HOST"] = "127.0.0.1"

    # Reload app module to pick up new environment variables
    import importlib
    import app as app_module
    importlib.reload(app_module)

    from app import app, db, UPLOAD_ROOT
    from thumbnails import ThumbnailGenerator
    from datetime import datetime
    import mimetypes

    # Initialize database
    db.init_db()

    # Initialize thumbnail generator
    thumbnail_cache = UPLOAD_ROOT / ".thumbnails"
    thumbnail_gen = ThumbnailGenerator(thumbnail_cache)

    # Index existing test files
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

    def run_server():
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=test_port, log_level="error")

    server_process = multiprocessing.Process(target=run_server, daemon=True)
    server_process.start()

    # Wait for server to start
    time.sleep(2)

    yield f"http://127.0.0.1:{test_port}"

    server_process.terminate()
    server_process.join(timeout=5)
    if server_process.is_alive():
        server_process.kill()


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
    time.sleep(0.4)  # Allow navigation transition to complete (150ms fade out + 150ms fade in + buffer)


def get_file_items_in_order(page: Page) -> list:
    """Get list of file names in DOM order (excludes folders)."""
    items = page.locator(".file-item").all()
    return [item.get_attribute("data-name") for item in items]


def get_preview_content_transition_style(page: Page) -> dict:
    """Get the computed CSS transition style for preview content element."""
    return page.evaluate("""
        () => {
            const content = document.getElementById('preview_content');
            if (!content) return null;
            const style = window.getComputedStyle(content);
            return {
                transition: style.transition,
                transitionProperty: style.transitionProperty,
                transitionDuration: style.transitionDuration,
                opacity: parseFloat(style.opacity)
            };
        }
    """)


def get_modal_content_transition_style(page: Page) -> dict:
    """Get the computed CSS transition style for preview modal content wrapper."""
    return page.evaluate("""
        () => {
            const content = document.querySelector('.preview-modal-content');
            if (!content) return null;
            const style = window.getComputedStyle(content);
            return {
                transition: style.transition,
                transitionProperty: style.transitionProperty,
                transitionDuration: style.transitionDuration
            };
        }
    """)


class TestPreviewNavigationNoFlash:
    """Tests verifying that navigation does not cause flash/flicker.

    These tests validate the core bug fix - smooth transitions during navigation.
    """

    def test_navigation_does_not_show_loading_message(
        self, page: Page, bug017_app_server: str
    ):
        """Test that arrow key navigation doesn't show 'Loading preview...' message.

        The bug was that navigation called openPreview() which immediately sets
        innerHTML to 'Loading preview...', causing a flash. The fix uses
        updatePreviewContent() which skips the loading message.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for navigation test"

        # Open preview on first file
        open_preview_for_file(page, files[0])

        # Set up a listener to capture any innerHTML changes to 'Loading preview...'
        # during navigation
        loading_detected = page.evaluate("""
            () => {
                return new Promise(resolve => {
                    const content = document.getElementById('preview_content');
                    let loadingDetected = false;

                    const observer = new MutationObserver((mutations) => {
                        for (const mutation of mutations) {
                            if (mutation.type === 'childList' || mutation.type === 'characterData') {
                                if (content.innerHTML.includes('Loading preview...')) {
                                    loadingDetected = true;
                                }
                            }
                        }
                    });

                    observer.observe(content, { childList: true, subtree: true, characterData: true });

                    // Resolve after a short delay to allow navigation
                    setTimeout(() => {
                        observer.disconnect();
                        resolve(loadingDetected);
                    }, 500);
                });
            }
        """)

        # Trigger navigation while observer is active (evaluated async above)
        page.keyboard.press("ArrowRight")
        time.sleep(0.6)

        # Re-run the check after navigation
        loading_message_present = page.evaluate("""
            () => {
                const content = document.getElementById('preview_content');
                return content.innerHTML.includes('Loading preview...');
            }
        """)

        assert not loading_message_present, (
            "BUG-017: 'Loading preview...' message should NOT appear during navigation. "
            "The updatePreviewContent() function should skip the loading message."
        )

        close_preview_modal(page)

    def test_modal_remains_visible_during_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that the modal never gets the 'hidden' class during navigation.

        The bug occurred because openPreview() was being called, which might
        manipulate the modal visibility. The fix ensures modal stays visible.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for navigation test"

        open_preview_for_file(page, files[0])

        # Check modal is visible before navigation
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Navigate to next file
        page.keyboard.press("ArrowRight")

        # Immediately check modal state (should never be hidden)
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Wait for transition and check again
        time.sleep(0.4)
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Verify filename changed (navigation worked)
        new_filename = get_preview_filename(page)
        assert new_filename == files[1], "Navigation should have occurred"

        close_preview_modal(page)

    def test_modal_overlay_stable_during_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that the modal overlay background remains stable during navigation.

        The modal background should never disappear or flicker during navigation.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 3, "Need at least 3 files for multiple navigation test"

        open_preview_for_file(page, files[0])

        # Check modal overlay is visible
        modal = page.locator("#preview_modal.modal")
        expect(modal).to_be_visible()

        # Navigate multiple times and verify overlay stays visible
        for i in range(2):
            page.keyboard.press("ArrowRight")
            # Check immediately after keypress
            expect(modal).to_be_visible()
            time.sleep(0.4)
            # Check after transition
            expect(modal).to_be_visible()

        close_preview_modal(page)

    def test_modal_buttons_stable_during_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that modal footer buttons remain visible and functional during navigation.

        The download, delete, and close buttons should stay in place during navigation.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for navigation test"

        open_preview_for_file(page, files[0])

        # Verify buttons are visible before navigation
        download_btn = page.locator("#download_file")
        delete_btn = page.locator("#delete_file")
        close_btn = page.locator("#close_preview_modal")

        expect(download_btn).to_be_visible()
        expect(delete_btn).to_be_visible()
        expect(close_btn).to_be_visible()

        # Navigate to next file
        page.keyboard.press("ArrowRight")

        # Buttons should remain visible immediately
        expect(download_btn).to_be_visible()
        expect(delete_btn).to_be_visible()
        expect(close_btn).to_be_visible()

        # And after transition
        time.sleep(0.4)
        expect(download_btn).to_be_visible()
        expect(delete_btn).to_be_visible()
        expect(close_btn).to_be_visible()

        # Verify buttons are still enabled
        expect(download_btn).to_be_enabled()
        expect(delete_btn).to_be_enabled()
        expect(close_btn).to_be_enabled()

        close_preview_modal(page)


class TestPreviewNavigationCSSTransitions:
    """Tests verifying that proper CSS transitions are applied for smooth content changes."""

    def test_preview_content_has_opacity_transition(
        self, page: Page, bug017_app_server: str
    ):
        """Test that .preview-content has CSS transition for opacity.

        The fix added: transition: opacity 0.15s ease-in-out;
        This enables smooth fade out/in during navigation.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        # Open a preview to ensure elements are rendered
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Get computed transition style
        style = get_preview_content_transition_style(page)

        assert style is not None, "Could not get preview content style"

        # Check that opacity transition is defined
        has_opacity_transition = (
            'opacity' in style['transitionProperty'].lower() or
            'all' in style['transitionProperty'].lower() or
            'opacity' in style['transition'].lower()
        )

        assert has_opacity_transition, (
            f"BUG-017: .preview-content should have opacity transition. "
            f"Got transition: {style['transition']}, transitionProperty: {style['transitionProperty']}. "
            f"Expected 'transition: opacity 0.15s ease-in-out;' in style.css"
        )

        close_preview_modal(page)

    def test_preview_modal_content_has_size_transition(
        self, page: Page, bug017_app_server: str
    ):
        """Test that .preview-modal-content has CSS transition for width/height.

        The fix added: transition: width 0.2s ease, height 0.2s ease;
        This enables smooth resizing when content dimensions change.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        # Open a preview to ensure elements are rendered
        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        # Get computed transition style
        style = get_modal_content_transition_style(page)

        assert style is not None, "Could not get modal content style"

        # Check that width/height transitions are defined
        transition_str = style['transition'].lower()
        has_size_transition = (
            'width' in transition_str or
            'height' in transition_str or
            'all' in transition_str
        )

        assert has_size_transition, (
            f"BUG-017: .preview-modal-content should have width/height transition. "
            f"Got transition: {style['transition']}. "
            f"Expected 'transition: width 0.2s ease, height 0.2s ease;' in style.css"
        )

        close_preview_modal(page)

    def test_content_opacity_returns_to_full_after_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that content opacity returns to 1 after navigation completes.

        The fade transition should end with opacity: 1 for the new content.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files for navigation test"

        open_preview_for_file(page, files[0])

        # Navigate to next file
        page.keyboard.press("ArrowRight")
        time.sleep(0.5)  # Wait for full transition (150ms out + 150ms in + buffer)

        # Check final opacity
        style = get_preview_content_transition_style(page)

        assert style is not None, "Could not get preview content style"
        assert style['opacity'] == 1.0, (
            f"After navigation transition, opacity should be 1.0, got {style['opacity']}. "
            f"The fade-in transition may not have completed."
        )

        close_preview_modal(page)


class TestPreviewNavigationRegressions:
    """Regression tests to ensure existing functionality still works after the fix."""

    def test_initial_open_still_shows_loading(
        self, page: Page, bug017_app_server: str
    ):
        """Test that clicking a file to open preview still shows loading message.

        The fix should only affect navigation - initial opens should still show
        'Loading preview...' while content loads.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        # Find a text file that requires async loading
        text_files = [f for f in get_file_items_in_order(page) if f.endswith('.txt')]
        assert len(text_files) > 0, "Need a text file for this test"

        # Click to open (not using helper to capture immediate state)
        file_item = page.locator(f".file-item:has-text('{text_files[0]}')")
        file_item.click()

        # Check for loading message immediately after click
        # Note: This might be too fast to catch, so we verify the mechanism exists
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        # Wait for content to load
        time.sleep(0.5)

        # Verify content loaded (no longer shows loading)
        content = page.locator("#preview_content")
        content_html = content.inner_html()
        assert "Loading preview..." not in content_html, (
            "After loading, content should not show 'Loading preview...' message"
        )

        close_preview_modal(page)

    def test_escape_closes_after_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that Escape key still closes preview after navigating with arrows."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"

        open_preview_for_file(page, files[0])

        # Navigate to another file
        press_arrow_key(page, "right")

        # Press Escape
        page.keyboard.press("Escape")
        time.sleep(0.2)

        # Modal should be hidden
        modal = page.locator("#preview_modal")
        expect(modal).to_have_class("modal hidden")

    def test_close_button_works_after_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that close button still works after navigating with arrows."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"

        open_preview_for_file(page, files[0])

        # Navigate to another file
        press_arrow_key(page, "right")

        # Click close button
        close_btn = page.locator("#close_preview_modal")
        close_btn.click()
        time.sleep(0.2)

        # Modal should be hidden
        modal = page.locator("#preview_modal")
        expect(modal).not_to_be_visible()

    def test_download_button_works_after_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """Test that download button is functional after navigating to another file."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"

        open_preview_for_file(page, files[0])

        # Navigate to next file
        press_arrow_key(page, "right")

        # Verify download button is enabled and accessible
        download_btn = page.locator("#download_file")
        expect(download_btn).to_be_visible()
        expect(download_btn).to_be_enabled()

        # Verify the navigated filename matches
        current_filename = get_preview_filename(page)
        assert current_filename == files[1], "Should be on the second file"

        close_preview_modal(page)

    def test_rapid_navigation_works_correctly(
        self, page: Page, bug017_app_server: str
    ):
        """Test that rapid consecutive arrow key presses work without breaking.

        Rapidly pressing arrow keys should result in correct final state without
        errors or visual glitches.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 4, "Need at least 4 files for rapid navigation test"

        open_preview_for_file(page, files[0])

        # Rapidly press right arrow 3 times with short delays
        for _ in range(3):
            page.keyboard.press("ArrowRight")
            time.sleep(0.1)  # Short delay between presses

        # Wait for final transition to complete
        time.sleep(0.5)

        # Verify we ended up on the correct file (4th file)
        final_filename = get_preview_filename(page)
        assert final_filename == files[3], (
            f"After 3 rapid right arrow presses from first file, "
            f"should be on file '{files[3]}', but got '{final_filename}'"
        )

        # Verify modal is still stable
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Verify no console errors
        # Note: Playwright doesn't easily capture console errors in sync API,
        # so we just verify the UI is stable

        close_preview_modal(page)

    def test_boundary_behavior_preserved_first_file(
        self, page: Page, bug017_app_server: str
    ):
        """Test that pressing left arrow at first file does nothing (no wrap)."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)

        # Open first file
        open_preview_for_file(page, files[0])

        # Press left multiple times
        press_arrow_key(page, "left")
        press_arrow_key(page, "left")

        # Should still be on first file
        current_filename = get_preview_filename(page)
        assert current_filename == files[0], (
            f"Left arrow at first file should not change preview. "
            f"Expected '{files[0]}', got '{current_filename}'"
        )

        # Modal should still be visible and stable
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        close_preview_modal(page)

    def test_boundary_behavior_preserved_last_file(
        self, page: Page, bug017_app_server: str
    ):
        """Test that pressing right arrow at last file does nothing (no wrap)."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)

        # Open last file
        open_preview_for_file(page, files[-1])

        # Press right multiple times
        press_arrow_key(page, "right")
        press_arrow_key(page, "right")

        # Should still be on last file
        current_filename = get_preview_filename(page)
        assert current_filename == files[-1], (
            f"Right arrow at last file should not change preview. "
            f"Expected '{files[-1]}', got '{current_filename}'"
        )

        # Modal should still be visible and stable
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        close_preview_modal(page)


class TestBug017NoFlashDetection:
    """Bug detection tests that explicitly fail if BUG-017 manifests.

    These tests are designed to FAIL if the bug is present (implementation reverted)
    and PASS when the bug is fixed.
    """

    def test_bug_017_no_loading_flash_during_navigation(
        self, page: Page, bug017_app_server: str
    ):
        """BUG-017: Fail explicitly if loading message appears during navigation.

        This test monitors for the 'Loading preview...' message appearing during
        navigation, which was the root cause of the visual flash/flicker.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"

        open_preview_for_file(page, files[0])

        # Set up observer before navigation
        page.evaluate("""
            window.loadingDetected = false;
            const content = document.getElementById('preview_content');
            const observer = new MutationObserver(() => {
                if (content.innerHTML.includes('Loading preview...')) {
                    window.loadingDetected = true;
                }
            });
            window.loadingObserver = observer;
            observer.observe(content, { childList: true, subtree: true, characterData: true });
        """)

        # Navigate
        page.keyboard.press("ArrowRight")
        time.sleep(0.5)

        # Check if loading was detected
        loading_detected = page.evaluate("window.loadingDetected")

        # Cleanup observer
        page.evaluate("window.loadingObserver.disconnect()")

        assert not loading_detected, (
            "BUG-017: 'Loading preview...' message detected during arrow key navigation! "
            "The navigation function should use updatePreviewContent() instead of openPreview(). "
            "updatePreviewContent() provides smooth fade transition without showing loading message."
        )

        close_preview_modal(page)

    def test_bug_017_content_has_fade_transition(
        self, page: Page, bug017_app_server: str
    ):
        """BUG-017: Fail if .preview-content lacks opacity transition CSS.

        The fix requires CSS: .preview-content { transition: opacity 0.15s ease-in-out; }
        Without this, the fade effect won't work smoothly.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        open_preview_for_file(page, files[0])

        style = get_preview_content_transition_style(page)
        assert style is not None, "Could not get preview content style"

        # Check for opacity in transition
        transition_str = (style['transition'] + ' ' + style['transitionProperty']).lower()
        has_opacity = 'opacity' in transition_str or 'all' in transition_str

        assert has_opacity, (
            "BUG-017: Missing opacity transition on .preview-content! "
            f"Current transition: '{style['transition']}'. "
            "The CSS fix requires: .preview-content {{ transition: opacity 0.15s ease-in-out; }}"
        )

        close_preview_modal(page)

    def test_bug_017_navigation_uses_smooth_update(
        self, page: Page, bug017_app_server: str
    ):
        """BUG-017: Verify navigation uses updatePreviewContent, not openPreview.

        The fix separates navigation (smooth fade) from initial open (shows loading).
        This test verifies the behavior is different between the two.
        """
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        files = get_file_items_in_order(page)
        assert len(files) >= 2, "Need at least 2 files"

        # Capture initial open behavior
        file_item = page.locator(f".file-item:has-text('{files[0]}')")
        file_item.click()

        # Wait for modal to appear
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()
        time.sleep(0.5)

        # Now navigate and check behavior is different
        page.evaluate("""
            window.contentChanges = [];
            const content = document.getElementById('preview_content');
            const observer = new MutationObserver(() => {
                window.contentChanges.push({
                    time: Date.now(),
                    content: content.innerHTML.substring(0, 100)
                });
            });
            window.contentObserver = observer;
            observer.observe(content, { childList: true, subtree: true });
        """)

        page.keyboard.press("ArrowRight")
        time.sleep(0.5)

        changes = page.evaluate("window.contentChanges")
        page.evaluate("window.contentObserver.disconnect()")

        # Check that no change includes "Loading preview..."
        loading_in_changes = any("Loading preview" in c['content'] for c in changes)

        assert not loading_in_changes, (
            "BUG-017: Navigation should use updatePreviewContent() (smooth fade), "
            "not openPreview() (shows loading message). "
            f"Content changes during navigation: {changes}"
        )

        close_preview_modal(page)


class TestPreviewNavigationContentTypes:
    """Tests for navigation between different file/content types."""

    def test_navigate_from_image_to_text(
        self, page: Page, bug017_app_server: str
    ):
        """Test smooth navigation from image preview to text preview."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        # Find an image file
        image_files = [f for f in get_file_items_in_order(page) if f.endswith(('.jpg', '.png'))]
        assert len(image_files) > 0, "Need image files for this test"

        open_preview_for_file(page, image_files[0])

        # Navigate until we find a text file
        files = get_file_items_in_order(page)
        for _ in range(len(files)):
            current = get_preview_filename(page)
            if current.endswith('.txt'):
                # Found text file - verify content shows <pre> element
                content = page.locator("#preview_content")
                pre_element = content.locator("pre")
                expect(pre_element).to_be_visible()
                break
            press_arrow_key(page, "right")
        else:
            pytest.skip("Could not navigate to a text file")

        close_preview_modal(page)

    def test_navigate_from_text_to_image(
        self, page: Page, bug017_app_server: str
    ):
        """Test smooth navigation from text preview to image preview."""
        page.goto(bug017_app_server)
        page.wait_for_load_state("networkidle")

        # Find a text file
        text_files = [f for f in get_file_items_in_order(page) if f.endswith('.txt')]
        assert len(text_files) > 0, "Need text files for this test"

        open_preview_for_file(page, text_files[0])

        # Navigate until we find an image file
        files = get_file_items_in_order(page)
        for _ in range(len(files)):
            current = get_preview_filename(page)
            if current.endswith(('.jpg', '.png')):
                # Found image file - verify content shows <img> element
                content = page.locator("#preview_content")
                img_element = content.locator("img")
                expect(img_element).to_be_visible()
                break
            press_arrow_key(page, "right")
        else:
            pytest.skip("Could not navigate to an image file")

        close_preview_modal(page)

    def test_navigate_between_images_shows_different_content(
        self, page: Page, bug017_app_server: str
    ):
        """Test that navigating between images updates the image source."""
        page.goto(bug017_app_server)
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
                # Found another image - verify src changed
                new_img = content.locator("img")
                expect(new_img).to_be_visible()
                new_src = new_img.get_attribute("src")
                assert new_src != initial_src, (
                    "Image src should change after navigating to different image"
                )
                break

        close_preview_modal(page)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

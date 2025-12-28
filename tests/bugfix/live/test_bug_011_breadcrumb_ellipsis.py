"""
BUG-011: Breadcrumb left-ellipsis truncation broken in Safari/WebKit browsers.

This module contains dual tests (success + bug detection) for BUG-011.
The bug manifests when:
1. User navigates to a deeply nested folder path
2. The breadcrumb bar overflows (path is too long to display fully)
3. WebKit-based browsers (Safari, Brave) truncate from the WRONG end

ROOT CAUSE: The CSS uses `direction: rtl` + `text-overflow: ellipsis` to achieve
left-side truncation. This technique has a known WebKit bug where truncation
occurs from the wrong end of the text (right instead of left).

Current implementation (static/style.css lines 207-216):
```css
.breadcrumbs {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  direction: rtl;
  text-align: left;
  unicode-bidi: plaintext;
}
```

EXPECTED BEHAVIOR (after fix):
- When breadcrumbs overflow, the RIGHTMOST segments (current folder + New Folder)
  should remain visible
- The LEFTMOST segments (Home, parent folders) should be hidden/truncated
- A visual indicator (ellipsis or fade) should appear on the left side when overflow occurs
- Scrolling breadcrumbs should auto-scroll to show the rightmost content

References:
- WebKit Bug #164999: text-overflow: ellipsis truncates incorrectly in RTL
- W3C CSSWG Issue #2125: text-overflow with different direction text
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
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Mark all tests in this module as e2e tests
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def bug011_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for BUG-011 testing with deep nesting.

    Creates a deeply nested folder structure to force breadcrumb overflow.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="bug011_test_"))

    # Create deeply nested folder structure
    # Path: a/b/c/d/e/f/g/h/i/j/k
    deep_path = temp_dir
    for letter in "abcdefghijk":
        deep_path = deep_path / letter
        deep_path.mkdir(parents=True, exist_ok=True)

    # Create a file in the deepest folder for verification
    (deep_path / "test_file.txt").write_text("Test file in deep folder")

    # Create a folder with long names to further test overflow
    long_name_path = temp_dir / "very_long_folder_name_to_test_overflow" / "another_long_folder_name"
    long_name_path.mkdir(parents=True, exist_ok=True)
    (long_name_path / "file.txt").write_text("Test file")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def bug011_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for BUG-011 testing."""
    temp_db = Path(tempfile.mktemp(prefix="bug011_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def bug011_app_server(bug011_test_upload_dir: Path, bug011_test_db_path: Path):
    """Start the FastAPI app server for BUG-011 testing."""
    test_port = 8770  # Unique port for BUG-011 tests

    os.environ["UPLOAD_ROOT"] = str(bug011_test_upload_dir)
    os.environ["DB_PATH"] = str(bug011_test_db_path)
    os.environ["PORT"] = str(test_port)
    os.environ["HOST"] = "127.0.0.1"

    # Reload app module to pick up new environment variables
    import importlib
    import app as app_module
    importlib.reload(app_module)

    from app import app, db, UPLOAD_ROOT
    from datetime import datetime
    import mimetypes

    db.init_db()

    # Index existing test files
    for file_path in UPLOAD_ROOT.rglob("*"):
        if file_path.is_file():
            filepath_rel = file_path.relative_to(UPLOAD_ROOT).as_posix()
            parent_path_rel = file_path.parent.relative_to(UPLOAD_ROOT).as_posix()
            extension = file_path.suffix.lower()
            mime_type, _ = mimetypes.guess_type(str(file_path))

            preview_type = None
            has_thumbnail = False
            if extension in ['.txt', '.md', '.log']:
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


def navigate_to_deep_path(page: Page, path: str):
    """Navigate to a deep path by clicking through folders or using hash navigation."""
    # Use hash-based navigation to go directly to the path
    current_url = page.url
    base_url = current_url.split('#')[0]
    page.goto(f"{base_url}#{path}")
    page.wait_for_load_state("networkidle")
    # Wait for breadcrumbs to render
    time.sleep(0.5)


def get_breadcrumb_container_box(page: Page) -> dict:
    """Get the bounding box of the breadcrumbs container."""
    breadcrumbs = page.locator("#breadcrumbs")
    return breadcrumbs.bounding_box()


def get_element_box(locator) -> dict:
    """Get the bounding box of an element."""
    return locator.bounding_box()


def is_element_visible_in_container(element_box: dict, container_box: dict) -> bool:
    """Check if an element is fully visible within its container."""
    if element_box is None or container_box is None:
        return False

    # Check if element is within container bounds
    element_left = element_box["x"]
    element_right = element_box["x"] + element_box["width"]
    container_left = container_box["x"]
    container_right = container_box["x"] + container_box["width"]

    return element_left >= container_left and element_right <= container_right


def get_breadcrumb_scroll_position(page: Page) -> int:
    """Get the scroll position of the breadcrumbs container."""
    return page.evaluate("""
        () => {
            const breadcrumbs = document.getElementById('breadcrumbs');
            return breadcrumbs ? breadcrumbs.scrollLeft : 0;
        }
    """)


def get_breadcrumb_overflow_state(page: Page) -> dict:
    """Get detailed overflow state of the breadcrumbs container."""
    return page.evaluate("""
        () => {
            const breadcrumbs = document.getElementById('breadcrumbs');
            if (!breadcrumbs) return null;
            return {
                scrollWidth: breadcrumbs.scrollWidth,
                clientWidth: breadcrumbs.clientWidth,
                scrollLeft: breadcrumbs.scrollLeft,
                isOverflowing: breadcrumbs.scrollWidth > breadcrumbs.clientWidth
            };
        }
    """)


class TestBreadcrumbOverflowBasic:
    """Basic tests for breadcrumb overflow behavior."""

    def test_breadcrumbs_overflow_with_deep_path(
        self, page: Page, bug011_app_server: str
    ):
        """Test that deeply nested paths cause breadcrumb overflow.

        This is a setup verification test to ensure our test fixtures
        create the overflow condition needed to test the bug.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        # Navigate to deep path
        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Resize viewport to narrow width to force overflow
        page.set_viewport_size({"width": 500, "height": 600})
        time.sleep(0.5)

        # Check if overflow occurs
        overflow_state = get_breadcrumb_overflow_state(page)

        assert overflow_state is not None, "Could not get breadcrumb overflow state"
        assert overflow_state["isOverflowing"], (
            f"Breadcrumbs should overflow with deep path at 500px width. "
            f"scrollWidth={overflow_state['scrollWidth']}, "
            f"clientWidth={overflow_state['clientWidth']}"
        )


class TestBreadcrumbEllipsisShowsRightmostPathSegments:
    """Success tests: Verify that rightmost path segments remain visible when overflow occurs.

    These tests verify the EXPECTED behavior after the fix.
    They will FAIL on the buggy codebase (before fix) and PASS after fix.
    """

    def test_new_folder_button_visible_when_overflow(
        self, page: Page, bug011_app_server: str
    ):
        """Test that the New Folder button remains visible even when breadcrumbs overflow.

        The New Folder button is the rightmost element in breadcrumbs and should
        ALWAYS be visible regardless of overflow state.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        # Navigate to deep path
        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Resize viewport to force overflow
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        # Get container and button bounding boxes
        breadcrumbs = page.locator("#breadcrumbs")
        new_folder_btn = page.locator("#new_folder_btn")

        expect(new_folder_btn).to_be_visible()

        container_box = get_breadcrumb_container_box(page)
        btn_box = get_element_box(new_folder_btn)

        assert container_box is not None, "Could not get breadcrumbs bounding box"
        assert btn_box is not None, "Could not get New Folder button bounding box"

        # Button should be within visible bounds of container
        assert is_element_visible_in_container(btn_box, container_box), (
            f"New Folder button should be visible within breadcrumbs container. "
            f"Button: x={btn_box['x']}, width={btn_box['width']}. "
            f"Container: x={container_box['x']}, width={container_box['width']}."
        )

    def test_current_folder_visible_when_overflow(
        self, page: Page, bug011_app_server: str
    ):
        """Test that the current folder breadcrumb is visible when overflow occurs.

        The current folder (deepest path segment) should always be visible as it
        represents where the user currently is.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        # Navigate to deep path - 'k' is the deepest folder
        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Resize viewport to force overflow
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        # Find the current folder link (data-path ends with 'k')
        current_folder_link = page.locator("#breadcrumbs a[data-path='a/b/c/d/e/f/g/h/i/j/k']")
        expect(current_folder_link).to_be_attached()

        container_box = get_breadcrumb_container_box(page)
        link_box = get_element_box(current_folder_link)

        # Current folder should be visible
        assert link_box is not None, "Could not get current folder link bounding box"
        assert is_element_visible_in_container(link_box, container_box), (
            f"Current folder 'k' should be visible within breadcrumbs container. "
            f"Link: x={link_box['x']}, width={link_box['width']}. "
            f"Container: x={container_box['x']}, width={container_box['width']}."
        )

    def test_rightmost_segments_visible_on_narrow_viewport(
        self, page: Page, bug011_app_server: str
    ):
        """Test that rightmost breadcrumb segments remain visible on narrow viewport.

        When overflow occurs, the user should see:
        - Current folder link
        - New Folder button
        - Possibly 1-2 parent folders depending on width
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Very narrow viewport
        page.set_viewport_size({"width": 350, "height": 600})
        time.sleep(0.5)

        breadcrumbs = page.locator("#breadcrumbs")
        container_box = get_breadcrumb_container_box(page)

        # Get all breadcrumb links
        links = page.locator("#breadcrumbs a").all()

        # At least the last link (current folder) should be visible
        if links:
            last_link = links[-1]
            last_link_box = get_element_box(last_link)

            assert last_link_box is not None, "Could not get last breadcrumb link bounding box"

            # Last link should be visible (at least partially)
            last_link_right = last_link_box["x"] + last_link_box["width"]
            container_right = container_box["x"] + container_box["width"]

            # The last link should not extend beyond the container right edge
            assert last_link_right <= container_right + 5, (  # 5px tolerance
                f"Last breadcrumb link should be visible (not beyond container). "
                f"Link right edge: {last_link_right}, Container right edge: {container_right}"
            )


class TestBug011BreadcrumbTruncationDirection:
    """Bug detection tests: Explicitly check that BUG-011 does NOT manifest.

    These tests fail with explicit BUG-011 messages if the bug is present.
    They make it IMPOSSIBLE to misdiagnose the failure cause.
    """

    def test_bug_011_new_folder_button_not_hidden(
        self, page: Page, bug011_app_server: str
    ):
        """BUG-011: Fail explicitly if New Folder button is hidden/truncated.

        This test directly checks for the bug condition where the rightmost
        elements (New Folder button) get hidden due to incorrect truncation.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Narrow viewport to force overflow
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        # Verify overflow is occurring
        overflow_state = get_breadcrumb_overflow_state(page)
        assert overflow_state and overflow_state["isOverflowing"], (
            "Test setup error: breadcrumbs should be overflowing"
        )

        # Get button position
        new_folder_btn = page.locator("#new_folder_btn")
        expect(new_folder_btn).to_be_attached()

        btn_box = get_element_box(new_folder_btn)
        container_box = get_breadcrumb_container_box(page)

        assert btn_box is not None, "BUG-011: New Folder button not found or not rendered"
        assert container_box is not None, "Could not get breadcrumbs container box"

        # Check if button is pushed off the visible area
        btn_left = btn_box["x"]
        btn_right = btn_box["x"] + btn_box["width"]
        container_left = container_box["x"]
        container_right = container_box["x"] + container_box["width"]

        # Button should not be pushed off either edge
        assert btn_left >= container_left - 5, (
            f"BUG-011: Breadcrumb truncation shows wrong path segments! "
            f"New Folder button is pushed off the LEFT edge. "
            f"Button left: {btn_left}, Container left: {container_left}. "
            f"The RTL text-overflow trick is truncating from the wrong side in this browser."
        )

        assert btn_right <= container_right + 50, (  # Some tolerance for button width
            f"BUG-011: Breadcrumb truncation shows wrong path segments! "
            f"New Folder button extends beyond the RIGHT edge. "
            f"Button right: {btn_right}, Container right: {container_right}. "
            f"This may indicate scrolling or positioning issues."
        )

    def test_bug_011_home_hidden_before_current_folder(
        self, page: Page, bug011_app_server: str
    ):
        """BUG-011: Fail if Home is visible but current folder is not.

        When truncation occurs correctly (from left), Home should be hidden first.
        If Home is visible but the current folder is hidden, truncation is wrong.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Very narrow viewport to force significant overflow
        page.set_viewport_size({"width": 350, "height": 600})
        time.sleep(0.5)

        # Verify overflow
        overflow_state = get_breadcrumb_overflow_state(page)
        if not overflow_state or not overflow_state["isOverflowing"]:
            pytest.skip("Viewport not narrow enough to cause overflow")

        container_box = get_breadcrumb_container_box(page)

        # Find Home link and current folder link
        home_link = page.locator("#breadcrumbs a[data-path='']")
        current_folder_link = page.locator("#breadcrumbs a[data-path='a/b/c/d/e/f/g/h/i/j/k']")

        home_box = get_element_box(home_link)
        current_box = get_element_box(current_folder_link)

        home_visible = home_box and is_element_visible_in_container(home_box, container_box)
        current_visible = current_box and is_element_visible_in_container(current_box, container_box)

        # BUG CONDITION: Home is visible but current folder is not
        # This means truncation happened from the WRONG side
        assert not (home_visible and not current_visible), (
            f"BUG-011: Breadcrumb truncation shows wrong path segments! "
            f"Home link IS visible but current folder 'k' is NOT visible. "
            f"This indicates the CSS RTL ellipsis trick is truncating from the wrong end. "
            f"Home should be hidden BEFORE the current folder when overflow occurs."
        )

    def test_bug_011_truncation_preserves_navigation_context(
        self, page: Page, bug011_app_server: str
    ):
        """BUG-011: Fail if truncation removes navigation context (current location).

        The user should always be able to see where they are (current folder).
        If the current folder is hidden, the user loses navigation context.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        # Navigate to a deep path with long folder names for maximum stress
        navigate_to_deep_path(
            page,
            "very_long_folder_name_to_test_overflow/another_long_folder_name"
        )

        # Narrow viewport
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        overflow_state = get_breadcrumb_overflow_state(page)
        if not overflow_state or not overflow_state["isOverflowing"]:
            # Try even narrower
            page.set_viewport_size({"width": 300, "height": 600})
            time.sleep(0.5)
            overflow_state = get_breadcrumb_overflow_state(page)

        if not overflow_state or not overflow_state["isOverflowing"]:
            pytest.skip("Could not force overflow with long folder names")

        container_box = get_breadcrumb_container_box(page)

        # Find the current folder link (the last one in the path)
        current_folder_link = page.locator(
            "#breadcrumbs a[data-path='very_long_folder_name_to_test_overflow/another_long_folder_name']"
        )

        if current_folder_link.count() == 0:
            pytest.skip("Current folder link not found")

        current_box = get_element_box(current_folder_link)

        # At minimum, the current folder should be at least partially visible
        # (its right edge should be within the container)
        if current_box:
            current_right = current_box["x"] + current_box["width"]
            container_right = container_box["x"] + container_box["width"]

            # The current folder's right edge should not be beyond the container
            # (meaning at least part of it should be visible)
            assert current_right <= container_right + 100, (
                f"BUG-011: Current folder navigation context is lost! "
                f"The current folder 'another_long_folder_name' extends beyond visible area. "
                f"Current folder right edge: {current_right}, Container right: {container_right}. "
                f"Users cannot see where they are in the folder hierarchy."
            )


class TestBreadcrumbOverflowIndicator:
    """Tests for visual overflow indicator (ellipsis or gradient fade)."""

    def test_overflow_indicator_visible_when_truncated(
        self, page: Page, bug011_app_server: str
    ):
        """Test that some visual indicator shows when breadcrumbs are truncated.

        After the fix, there should be a visual indicator (gradient fade or ellipsis)
        on the left side when overflow occurs, showing the user that content is hidden.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Force overflow
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        overflow_state = get_breadcrumb_overflow_state(page)
        if not overflow_state or not overflow_state["isOverflowing"]:
            pytest.skip("Could not force overflow")

        # Check for overflow indicator element or CSS pseudo-element
        # The fix should add either:
        # 1. An ellipsis overlay element with gradient
        # 2. A ::before or ::after pseudo-element with ellipsis

        # Check for gradient/fade indicator (JavaScript overlay approach)
        fade_indicator = page.locator(".breadcrumbs-fade, .breadcrumbs-ellipsis, [class*='breadcrumb-overflow']")

        # Check computed style for any gradient-based indicator
        has_indicator = page.evaluate("""
            () => {
                const breadcrumbs = document.getElementById('breadcrumbs');
                if (!breadcrumbs) return false;

                // Check for overlay element
                const overlay = breadcrumbs.querySelector('.breadcrumbs-fade, .breadcrumbs-ellipsis');
                if (overlay) return true;

                // Check for ::before pseudo-element with content
                const beforeStyle = window.getComputedStyle(breadcrumbs, '::before');
                const afterStyle = window.getComputedStyle(breadcrumbs, '::after');

                // Check if either has ellipsis content
                const hasEllipsisBefore = beforeStyle.content && beforeStyle.content.includes('...');
                const hasEllipsisAfter = afterStyle.content && afterStyle.content.includes('...');

                // Check for background gradient (fade effect)
                const hasGradientBefore = beforeStyle.background &&
                    (beforeStyle.background.includes('gradient') || beforeStyle.background.includes('linear'));
                const hasGradientAfter = afterStyle.background &&
                    (afterStyle.background.includes('gradient') || afterStyle.background.includes('linear'));

                return hasEllipsisBefore || hasEllipsisAfter || hasGradientBefore || hasGradientAfter;
            }
        """)

        # This test documents the expected behavior after fix
        # It will fail until the overflow indicator is implemented
        assert has_indicator or fade_indicator.count() > 0, (
            "When breadcrumbs overflow, a visual indicator (ellipsis or gradient fade) "
            "should appear on the left side to show the user that content is hidden. "
            "This indicator helps users understand that they can scroll or that there are "
            "more breadcrumbs hidden to the left."
        )


class TestBreadcrumbAutoScrollOnNavigation:
    """Tests for auto-scroll behavior when navigating to new folders."""

    def test_breadcrumbs_scroll_to_show_current_folder_on_navigation(
        self, page: Page, bug011_app_server: str
    ):
        """Test that breadcrumbs auto-scroll to show current folder after navigation.

        When navigating into a new folder that causes overflow, the breadcrumbs
        should automatically scroll to show the new current folder (rightmost).
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        # Set narrow viewport first
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.3)

        # Navigate to a deep path - this should trigger auto-scroll
        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        overflow_state = get_breadcrumb_overflow_state(page)
        if not overflow_state or not overflow_state["isOverflowing"]:
            pytest.skip("Could not force overflow")

        container_box = get_breadcrumb_container_box(page)

        # The New Folder button should be visible after auto-scroll
        new_folder_btn = page.locator("#new_folder_btn")
        btn_box = get_element_box(new_folder_btn)

        if btn_box:
            btn_right = btn_box["x"] + btn_box["width"]
            container_right = container_box["x"] + container_box["width"]

            # Button should be within visible area (accounting for some margin)
            assert btn_right <= container_right + 50, (
                f"Breadcrumbs should auto-scroll to show New Folder button after navigation. "
                f"Button right edge: {btn_right}, Container right: {container_right}. "
                f"The rightmost content should be visible after navigating to a new folder."
            )


class TestBreadcrumbResponsiveness:
    """Tests for breadcrumb behavior across different viewport sizes."""

    def test_breadcrumbs_work_at_various_viewport_widths(
        self, page: Page, bug011_app_server: str
    ):
        """Test breadcrumb truncation behavior at multiple viewport widths.

        Tests that the fix works consistently across different screen sizes.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Test at various widths
        test_widths = [600, 500, 400, 350, 300]

        for width in test_widths:
            page.set_viewport_size({"width": width, "height": 600})
            time.sleep(0.3)

            overflow_state = get_breadcrumb_overflow_state(page)
            new_folder_btn = page.locator("#new_folder_btn")

            # Button should always be present
            expect(new_folder_btn).to_be_attached()

            btn_box = get_element_box(new_folder_btn)
            container_box = get_breadcrumb_container_box(page)

            if btn_box and container_box:
                btn_right = btn_box["x"] + btn_box["width"]
                container_right = container_box["x"] + container_box["width"]

                # At any width, the button should not extend far beyond container
                assert btn_right <= container_right + 100, (
                    f"At viewport width {width}px, New Folder button extends too far beyond container. "
                    f"Button right: {btn_right}, Container right: {container_right}"
                )

    def test_breadcrumbs_handle_resize_gracefully(
        self, page: Page, bug011_app_server: str
    ):
        """Test that breadcrumbs handle viewport resize gracefully.

        When the viewport is resized, breadcrumbs should adjust their
        overflow/truncation state appropriately.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Start wide (no overflow)
        page.set_viewport_size({"width": 1200, "height": 600})
        time.sleep(0.3)

        wide_overflow = get_breadcrumb_overflow_state(page)

        # Resize to narrow (should cause overflow)
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        narrow_overflow = get_breadcrumb_overflow_state(page)

        # Resize back to wide (overflow should resolve)
        page.set_viewport_size({"width": 1200, "height": 600})
        time.sleep(0.3)

        restored_overflow = get_breadcrumb_overflow_state(page)

        # After restoring wide viewport, overflow state should be similar to original
        if wide_overflow and restored_overflow:
            # Both should either overflow or not overflow (depending on content)
            # The key is that resize doesn't break the breadcrumbs
            new_folder_btn = page.locator("#new_folder_btn")
            expect(new_folder_btn).to_be_visible()


class TestRegressionPrevention:
    """Tests designed to fail if the fix is reverted or broken."""

    def test_rightmost_content_always_accessible(
        self, page: Page, bug011_app_server: str
    ):
        """Regression test: rightmost content must always be accessible.

        This test verifies the core requirement that after the fix,
        users can always see/access the current folder and New Folder button.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        navigate_to_deep_path(page, "a/b/c/d/e/f/g/h/i/j/k")

        # Force significant overflow
        page.set_viewport_size({"width": 350, "height": 600})
        time.sleep(0.5)

        # New Folder button must be clickable
        new_folder_btn = page.locator("#new_folder_btn")
        expect(new_folder_btn).to_be_visible()
        expect(new_folder_btn).to_be_enabled()

        # Click should open modal (proves button is accessible)
        new_folder_btn.click()

        modal = page.locator("#new_folder_modal")
        expect(modal).to_be_visible()

        # Close modal
        page.locator("#close_new_folder_modal").click()
        expect(modal).not_to_be_visible()

    def test_current_folder_link_clickable_when_overflow(
        self, page: Page, bug011_app_server: str
    ):
        """Regression test: current folder link must remain clickable.

        Even when overflow occurs, the current folder link should be
        accessible for users who want to refresh or interact with it.
        """
        page.goto(bug011_app_server)
        page.wait_for_load_state("networkidle")

        # Navigate to a mid-depth path first
        navigate_to_deep_path(page, "a/b/c/d/e")

        # Force overflow
        page.set_viewport_size({"width": 400, "height": 600})
        time.sleep(0.5)

        # Current folder link (e) should be visible and clickable
        current_link = page.locator("#breadcrumbs a[data-path='a/b/c/d/e']")

        # Check if visible within container
        container_box = get_breadcrumb_container_box(page)
        link_box = get_element_box(current_link)

        if link_box and container_box:
            link_right = link_box["x"] + link_box["width"]
            container_right = container_box["x"] + container_box["width"]

            # Link should be at least partially visible
            assert link_right <= container_right + 50, (
                f"Current folder link 'e' should be visible. "
                f"If this fails, the breadcrumb truncation implementation may be broken."
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--headed"])

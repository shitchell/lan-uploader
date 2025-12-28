"""
BUG-014: Mobile action buttons cause list view items to overflow horizontally.

This module contains dual tests (success + bug detection) for BUG-014.
The bug manifests when:
1. User views files in list mode on a mobile device (viewport <= 600px)
2. The Download/Delete action buttons are rendered in each list item
3. Even with opacity: 0, the buttons take up layout space
4. This causes items to overflow horizontally, breaking the layout

ROOT CAUSE: The CSS uses `opacity: 0` to hide action buttons, but this still
allocates space in the flex layout. The @media (max-width: 600px) block has
no rule to hide .item-actions with `display: none`.

Current implementation (static/style.css lines 391-400):
```css
.list-view .item-actions {
  gap: 6px;
  opacity: 0;
  transition: opacity 0.2s;
}
```

Missing mobile CSS (should be in @media (max-width: 600px)):
```css
.list-view .item-actions {
  display: none;
}
```

EXPECTED BEHAVIOR (after fix):
- On mobile (viewport <= 600px), action buttons should be hidden completely
- List items should fit within the viewport without horizontal scrolling
- Users can still access Download/Delete via context menu (long-press/right-click)
- On desktop, hover behavior remains unchanged

References:
- OBS-001: Action buttons rendered in list view by navigation.js
- OBS-002: No mobile-specific CSS for .item-actions in @media (max-width: 600px)
- OBS-006: opacity: 0 still allocates layout space (unlike display: none)
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
def bug014_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for BUG-014 testing with files and folders.

    Creates a directory structure with multiple files and folders to test
    list view layout on mobile.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="bug014_test_"))

    # Create test folders
    (temp_dir / "folder_one").mkdir()
    (temp_dir / "folder_two").mkdir()
    (temp_dir / "folder_three").mkdir()

    # Create test files with various names
    (temp_dir / "document.txt").write_text("Test document content")
    (temp_dir / "image.jpg").write_bytes(b"fake jpg content")
    (temp_dir / "spreadsheet.xlsx").write_bytes(b"fake xlsx content")
    (temp_dir / "presentation.pptx").write_bytes(b"fake pptx content")
    (temp_dir / "archive.zip").write_bytes(b"fake zip content")

    # Create files in subfolders for navigation testing
    (temp_dir / "folder_one" / "nested_file.txt").write_text("Nested file")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def bug014_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for BUG-014 testing."""
    temp_db = Path(tempfile.mktemp(prefix="bug014_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def bug014_app_server(bug014_test_upload_dir: Path, bug014_test_db_path: Path):
    """Start the FastAPI app server for BUG-014 testing."""
    test_port = 8771  # Unique port for BUG-014 tests

    os.environ["UPLOAD_ROOT"] = str(bug014_test_upload_dir)
    os.environ["DB_PATH"] = str(bug014_test_db_path)
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
            elif extension in ['.jpg', '.jpeg', '.png', '.gif']:
                preview_type = 'image'

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


def set_mobile_viewport(page: Page, width: int = 600):
    """Set viewport to mobile dimensions.

    Args:
        page: Playwright page object
        width: Viewport width (default 600px, the mobile breakpoint)
    """
    page.set_viewport_size({"width": width, "height": 800})


def get_horizontal_overflow_state(page: Page) -> dict:
    """Get the horizontal overflow state of the browser content area.

    Returns:
        dict with scrollWidth, clientWidth, and hasOverflow
    """
    return page.evaluate("""
        () => {
            const content = document.querySelector('.browser-content');
            if (!content) return null;
            return {
                scrollWidth: content.scrollWidth,
                clientWidth: content.clientWidth,
                hasOverflow: content.scrollWidth > content.clientWidth
            };
        }
    """)


def get_item_actions_visibility(page: Page) -> dict:
    """Check visibility state of action buttons in list view.

    Returns:
        dict with count, visibleCount, and details for each .item-actions element
    """
    return page.evaluate("""
        () => {
            const actionContainers = document.querySelectorAll('.list-view .item-actions');
            const results = {
                count: actionContainers.length,
                visibleCount: 0,
                hiddenWithDisplayNone: 0,
                hiddenWithOpacity: 0,
                takingUpSpace: 0,
                details: []
            };

            for (const container of actionContainers) {
                const style = window.getComputedStyle(container);
                const rect = container.getBoundingClientRect();
                const display = style.display;
                const opacity = parseFloat(style.opacity);
                const width = rect.width;

                const detail = {
                    display: display,
                    opacity: opacity,
                    width: width,
                    isVisible: display !== 'none' && opacity > 0,
                    takesUpSpace: display !== 'none' && width > 0
                };

                results.details.push(detail);

                if (detail.isVisible) {
                    results.visibleCount++;
                }
                if (display === 'none') {
                    results.hiddenWithDisplayNone++;
                } else if (opacity === 0) {
                    results.hiddenWithOpacity++;
                }
                if (detail.takesUpSpace) {
                    results.takingUpSpace++;
                }
            }

            return results;
        }
    """)


def get_list_item_bounds(page: Page) -> list:
    """Get bounding boxes for all list items.

    Returns:
        List of dicts with item info and bounding box
    """
    return page.evaluate("""
        () => {
            const items = document.querySelectorAll('.list-view .file-item, .list-view .folder-item');
            const viewport = {
                width: window.innerWidth,
                height: window.innerHeight
            };
            const results = [];

            for (const item of items) {
                const rect = item.getBoundingClientRect();
                results.push({
                    name: item.dataset.name || item.querySelector('.item-name')?.textContent,
                    left: rect.left,
                    right: rect.right,
                    width: rect.width,
                    extendsBeyndViewport: rect.right > viewport.width
                });
            }

            return { items: results, viewportWidth: viewport.width };
        }
    """)


class TestMobileListViewLayoutBasic:
    """Basic tests to verify test setup and mobile conditions."""

    def test_list_view_renders_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """Test that list view renders correctly at mobile viewport size.

        This is a setup verification test to ensure our test fixtures work.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.3)

        # Verify we're in list view (default)
        browser_content = page.locator("#browser_content")
        expect(browser_content).to_have_class("browser-content list-view")

        # Should have file and folder items
        items = page.locator(".file-item, .folder-item")
        expect(items.first).to_be_visible()

    def test_action_buttons_exist_in_list_view(
        self, page: Page, bug014_app_server: str
    ):
        """Test that action buttons are created for list view items.

        Verifies the test setup - action buttons should be rendered in list view.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Desktop viewport first to ensure list view renders normally
        page.set_viewport_size({"width": 1024, "height": 768})
        time.sleep(0.3)

        # Should be in list view
        browser_content = page.locator("#browser_content")
        expect(browser_content).to_have_class("browser-content list-view")

        # Action containers should exist
        action_containers = page.locator(".list-view .item-actions")
        count = action_containers.count()
        assert count > 0, "Action buttons should be created in list view"

        # Verify buttons exist inside containers
        download_buttons = page.locator(".list-view .item-actions .action-btn:has-text('Download')")
        delete_buttons = page.locator(".list-view .item-actions .action-btn:has-text('Delete')")

        assert download_buttons.count() > 0, "Download buttons should exist"
        assert delete_buttons.count() > 0, "Delete buttons should exist"


class TestMobileListViewNoOverflow:
    """Success tests: Verify that list items fit within viewport on mobile.

    These tests verify the EXPECTED behavior after the fix.
    They will FAIL on the buggy codebase (before fix) and PASS after fix.
    """

    def test_list_items_fit_within_viewport_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """Test that list view items fit within the mobile viewport.

        After the fix, list items should not cause horizontal overflow
        because action buttons are hidden with display: none on mobile.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Check for horizontal overflow
        overflow_state = get_horizontal_overflow_state(page)

        assert overflow_state is not None, "Could not get overflow state"
        assert not overflow_state["hasOverflow"], (
            f"List view should not have horizontal overflow on mobile. "
            f"scrollWidth={overflow_state['scrollWidth']}, "
            f"clientWidth={overflow_state['clientWidth']}. "
            f"Action buttons should be hidden with display: none on mobile."
        )

    def test_no_horizontal_scrollbar_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """Test that no horizontal scrollbar appears on mobile viewport.

        The browser content area should not require horizontal scrolling.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Check if horizontal scrollbar would appear
        has_horizontal_scroll = page.evaluate("""
            () => {
                const content = document.querySelector('.browser-content');
                if (!content) return false;
                // Check if scrollWidth exceeds clientWidth (would show scrollbar)
                return content.scrollWidth > content.clientWidth;
            }
        """)

        assert not has_horizontal_scroll, (
            "No horizontal scrollbar should appear on mobile. "
            "List items should fit within the viewport width."
        )

    def test_list_items_right_edge_within_viewport(
        self, page: Page, bug014_app_server: str
    ):
        """Test that the right edge of all list items is within viewport bounds.

        Each list item's right edge should not extend beyond the viewport.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Get list item bounds
        bounds_data = get_list_item_bounds(page)
        items = bounds_data["items"]
        viewport_width = bounds_data["viewportWidth"]

        items_exceeding = [item for item in items if item["extendsBeyndViewport"]]

        exceeding_names = [
            f"{item['name']} (right={item['right']:.0f}px)"
            for item in items_exceeding
        ]
        assert len(items_exceeding) == 0, (
            f"All list items should fit within viewport width ({viewport_width}px). "
            f"Items extending beyond viewport: {exceeding_names}"
        )

    def test_action_buttons_hidden_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """Test that action buttons are hidden (display: none) on mobile.

        After the fix, action buttons should be hidden completely on mobile,
        not just set to opacity: 0.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Check action button visibility
        visibility = get_item_actions_visibility(page)

        assert visibility is not None, "Could not get action button visibility"
        assert visibility["count"] > 0, "Test requires action buttons to exist"

        # Buttons should be hidden with display: none (not taking up space)
        assert visibility["takingUpSpace"] == 0, (
            f"Action buttons should not take up any space on mobile. "
            f"Found {visibility['takingUpSpace']} action containers still taking up space. "
            f"They should have display: none, not just opacity: 0."
        )


class TestBug014ActionButtonsOverflow:
    """Bug detection tests: Explicitly check that BUG-014 does NOT manifest.

    These tests fail with explicit BUG-014 messages if the bug is present.
    They make it IMPOSSIBLE to misdiagnose the failure cause.
    """

    def test_bug_014_no_horizontal_overflow_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """BUG-014: Fail explicitly if horizontal overflow occurs on mobile.

        This test directly checks for the bug condition where action buttons
        cause list items to overflow horizontally on mobile viewports.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Check for horizontal overflow
        overflow_state = get_horizontal_overflow_state(page)

        assert overflow_state is not None, "Could not get overflow state"

        assert not overflow_state["hasOverflow"], (
            f"BUG-014: Horizontal overflow detected on mobile viewport! "
            f"scrollWidth={overflow_state['scrollWidth']}px exceeds "
            f"clientWidth={overflow_state['clientWidth']}px. "
            f"Action buttons are causing list items to overflow horizontally. "
            f"The .item-actions container needs display: none in the mobile CSS."
        )

    def test_bug_014_action_buttons_hidden_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """BUG-014: Fail explicitly if action buttons are visible on mobile.

        The action buttons should be completely hidden (display: none) on mobile,
        not just invisible (opacity: 0) since opacity still takes up layout space.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Get detailed visibility info
        visibility = get_item_actions_visibility(page)

        assert visibility is not None, "Could not check action button visibility"
        assert visibility["count"] > 0, "Test setup error: no action buttons found"

        # The bug condition: buttons have opacity: 0 but still take up space
        # because display is not 'none'
        assert visibility["takingUpSpace"] == 0, (
            f"BUG-014: Action buttons visible on mobile causing layout overflow! "
            f"Found {visibility['takingUpSpace']} action containers taking up space. "
            f"hiddenWithOpacity={visibility['hiddenWithOpacity']} (uses opacity: 0), "
            f"hiddenWithDisplayNone={visibility['hiddenWithDisplayNone']}. "
            f"The @media (max-width: 600px) CSS is missing: "
            f".list-view .item-actions {{ display: none; }}"
        )

    def test_bug_014_items_fit_at_narrow_viewport(
        self, page: Page, bug014_app_server: str
    ):
        """BUG-014: Fail if list items extend beyond viewport at 375px width.

        Tests the bug at a common mobile phone width (iPhone SE, etc).
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set narrow mobile viewport (iPhone SE width)
        set_mobile_viewport(page, 375)
        time.sleep(0.5)

        # Get list item bounds
        bounds_data = get_list_item_bounds(page)
        items = bounds_data["items"]
        viewport_width = bounds_data["viewportWidth"]

        items_exceeding = [item for item in items if item["extendsBeyndViewport"]]

        exceeding_names = [
            f"{item['name']} (right={item['right']:.0f}px)"
            for item in items_exceeding[:3]
        ]
        assert len(items_exceeding) == 0, (
            f"BUG-014: List items overflow at narrow mobile viewport ({viewport_width}px)! "
            f"Found {len(items_exceeding)} items extending beyond viewport: {exceeding_names}. "
            f"Action buttons should be hidden on mobile to prevent this overflow."
        )


class TestContextMenuFallback:
    """Tests to verify that context menu provides fallback for hidden action buttons."""

    def test_context_menu_available_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """Test that context menu is available for file actions on mobile.

        Even when action buttons are hidden, users should be able to access
        Download/Delete via the context menu (right-click or long-press).
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Right-click on a file item to trigger context menu
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        file_item.click(button="right")

        # Context menu should appear
        context_menu = page.locator("#context_menu, .context-menu")
        expect(context_menu).to_be_visible()

        # Should have Download and Delete options
        download_option = context_menu.locator(":text('Download')")
        delete_option = context_menu.locator(":text('Delete')")

        expect(download_option).to_be_visible()
        expect(delete_option).to_be_visible()

    def test_context_menu_works_for_folders_on_mobile(
        self, page: Page, bug014_app_server: str
    ):
        """Test that context menu works for folders on mobile as well."""
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set mobile viewport
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        # Right-click on a folder item
        folder_item = page.locator(".folder-item").first
        expect(folder_item).to_be_visible()

        folder_item.click(button="right")

        # Context menu should appear with options
        context_menu = page.locator("#context_menu, .context-menu")
        expect(context_menu).to_be_visible()


class TestDesktopBehaviorUnchanged:
    """Tests to verify that desktop behavior is not affected by the fix."""

    def test_action_buttons_visible_on_hover_desktop(
        self, page: Page, bug014_app_server: str
    ):
        """Test that action buttons are visible on hover on desktop.

        The fix should only hide buttons on mobile. Desktop hover behavior
        should remain unchanged.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set desktop viewport
        page.set_viewport_size({"width": 1024, "height": 768})
        time.sleep(0.3)

        # Get a file item
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        # Hover over the item
        file_item.hover()
        time.sleep(0.3)

        # Action buttons should become visible (opacity: 1)
        action_buttons = file_item.locator(".item-actions .action-btn")
        expect(action_buttons.first).to_be_visible()

    def test_no_overflow_on_desktop(
        self, page: Page, bug014_app_server: str
    ):
        """Test that there's no horizontal overflow on desktop either.

        Desktop should have enough room for action buttons without overflow.
        """
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set desktop viewport
        page.set_viewport_size({"width": 1024, "height": 768})
        time.sleep(0.3)

        # Check for horizontal overflow
        overflow_state = get_horizontal_overflow_state(page)

        assert overflow_state is not None, "Could not get overflow state"
        assert not overflow_state["hasOverflow"], (
            f"Desktop should not have horizontal overflow. "
            f"scrollWidth={overflow_state['scrollWidth']}, "
            f"clientWidth={overflow_state['clientWidth']}"
        )


class TestMobileBreakpointBoundary:
    """Tests for behavior at the mobile breakpoint boundary (600px)."""

    def test_buttons_hidden_at_600px(
        self, page: Page, bug014_app_server: str
    ):
        """Test that action buttons are hidden at exactly 600px (the breakpoint)."""
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set viewport to exactly the breakpoint
        set_mobile_viewport(page, 600)
        time.sleep(0.5)

        visibility = get_item_actions_visibility(page)

        assert visibility["takingUpSpace"] == 0, (
            f"At 600px viewport, action buttons should be hidden. "
            f"Found {visibility['takingUpSpace']} still taking up space."
        )

    def test_buttons_visible_above_breakpoint(
        self, page: Page, bug014_app_server: str
    ):
        """Test that action buttons exist above the 600px breakpoint."""
        page.goto(bug014_app_server)
        page.wait_for_load_state("networkidle")

        # Set viewport just above the breakpoint
        page.set_viewport_size({"width": 601, "height": 800})
        time.sleep(0.5)

        visibility = get_item_actions_visibility(page)

        # Above breakpoint, buttons should be rendered (though possibly with opacity: 0)
        # They will take up space since display is not none
        assert visibility["count"] > 0, "Action buttons should exist above breakpoint"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--headed"])

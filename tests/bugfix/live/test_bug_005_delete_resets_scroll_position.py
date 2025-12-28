"""
BUG-005: Deleting a file resets scroll position with infinite scroll.

This module contains dual tests (success + bug detection) for BUG-005.
The bug manifests when:
1. User scrolls down to load 2+ pages of files via infinite scroll
2. User deletes a file
3. The file list refreshes and jumps back to the top of the page

ROOT CAUSE: Delete handlers call loadDirectory(state.currentPath) after deletion,
which resets pagination state (currentOffset=0), clears fileGrid.innerHTML, and
only loads the first page of items.

EXPECTED BEHAVIOR (after fix):
- After deleting a file, only that file's DOM element should be removed
- Scroll position should remain unchanged
- Previously loaded items should remain visible
- No new /api/browse request should be made
- state.currentOffset should be decremented by 1
"""

import os
import re
import sys
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from playwright.sync_api import Page, expect

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Mark all tests in this module as e2e tests
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def bug005_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for BUG-005 testing with many files.

    Creates 100+ files to enable infinite scroll behavior (PAGE_SIZE is 50).
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="bug005_test_"))

    # Create 100 files to enable infinite scroll (PAGE_SIZE is 50)
    for i in range(100):
        (temp_dir / f"file_{i:03d}.txt").write_text(f"Content of file {i}")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def bug005_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for BUG-005 testing."""
    temp_db = Path(tempfile.mktemp(prefix="bug005_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def bug005_app_server(bug005_test_upload_dir: Path, bug005_test_db_path: Path):
    """Start the FastAPI app server for BUG-005 testing."""
    import time
    import multiprocessing

    os.environ["UPLOAD_ROOT"] = str(bug005_test_upload_dir)
    os.environ["DB_PATH"] = str(bug005_test_db_path)
    os.environ["PORT"] = "8768"  # Unique port for BUG-005 tests
    os.environ["HOST"] = "127.0.0.1"

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
        uvicorn.run(app, host="127.0.0.1", port=8768, log_level="error")

    server_process = multiprocessing.Process(target=run_server, daemon=True)
    server_process.start()

    # Wait for server to start
    time.sleep(2)

    yield "http://127.0.0.1:8768"

    server_process.terminate()
    server_process.join(timeout=5)
    if server_process.is_alive():
        server_process.kill()


def scroll_to_load_multiple_pages(page: Page) -> int:
    """Scroll down to trigger infinite scroll and load multiple pages.

    Returns the scroll position (scrollY) after scrolling.
    """
    # Scroll down to trigger loading of additional pages
    # We need to scroll enough to trigger the IntersectionObserver

    # First, wait for initial load
    page.wait_for_load_state("networkidle")

    # Get the load sentinel element (triggers infinite scroll when visible)
    load_sentinel = page.locator("#load_sentinel")

    # Scroll to the bottom to trigger infinite scroll
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)

    # Wait for more items to load (the second page)
    page.wait_for_load_state("networkidle")

    # Scroll down again to ensure we're past the first page
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)

    # Wait for items to be rendered
    page.wait_for_load_state("networkidle")

    # Now scroll to a middle position to simulate typical user behavior
    scroll_y = page.evaluate("document.body.scrollHeight / 2")
    page.evaluate(f"window.scrollTo(0, {scroll_y})")
    page.wait_for_timeout(200)

    return page.evaluate("window.scrollY")


class TestBug005DeletePreservesScrollPosition:
    """Success tests: Verify expected behavior after BUG-005 fix.

    These tests verify that scroll position is PRESERVED after deleting a file.
    They will FAIL on the buggy codebase (before fix) and PASS after fix.
    """

    def test_delete_preserves_scroll_position(
        self, page: Page, bug005_app_server: str
    ):
        """Verify scroll position is preserved after deleting a file.

        Given: User has scrolled down to load 2+ pages of files
        When: User deletes a file
        Then: Scroll position should remain at the same position
        """
        page.goto(bug005_app_server)
        page.wait_for_load_state("networkidle")

        # Scroll to load multiple pages
        scroll_before = scroll_to_load_multiple_pages(page)

        # Verify we're scrolled down (not at top)
        assert scroll_before > 0, "Test setup failed: should be scrolled down"

        # Count items before delete
        items_before = page.locator(".file-item, .folder-item").count()

        # Find a visible file item to delete
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        # Get the file path for deletion
        file_path = file_item.get_attribute("data-path")

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Find and click the delete button (context menu or list view action button)
        # In list view, there's an action button
        delete_btn = file_item.locator(".action-btn:has-text('Delete')")
        if delete_btn.count() > 0:
            delete_btn.click()
        else:
            # Trigger context menu and delete via that
            file_item.click(button="right")
            page.locator("text=Delete").click()

        # Wait for delete to complete
        page.wait_for_timeout(500)

        # Get scroll position after delete
        scroll_after = page.evaluate("window.scrollY")

        # Scroll position should be preserved (with small tolerance for rendering)
        assert abs(scroll_after - scroll_before) < 50, (
            f"Scroll position changed from {scroll_before} to {scroll_after}. "
            f"Expected scroll position to remain unchanged after delete."
        )

    def test_delete_removes_only_deleted_item_from_dom(
        self, page: Page, bug005_app_server: str
    ):
        """Verify only the deleted item is removed from DOM, not all items.

        Given: User has scrolled down to load 2+ pages of files (100+ items loaded)
        When: User deletes a file
        Then: Only one item should be removed from DOM (not a full refresh)
        """
        page.goto(bug005_app_server)
        page.wait_for_load_state("networkidle")

        # Scroll to load multiple pages
        scroll_to_load_multiple_pages(page)

        # Count items before delete (should be more than PAGE_SIZE=50)
        items_before = page.locator(".file-item, .folder-item").count()

        # We should have loaded more than first page
        assert items_before > 50, (
            f"Test setup failed: expected more than 50 items, got {items_before}"
        )

        # Find a visible file item to delete
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the file
        delete_btn = file_item.locator(".action-btn:has-text('Delete')")
        if delete_btn.count() > 0:
            delete_btn.click()
        else:
            file_item.click(button="right")
            page.locator("text=Delete").click()

        # Wait for delete to complete
        page.wait_for_timeout(500)

        # Count items after delete
        items_after = page.locator(".file-item, .folder-item").count()

        # Only one item should have been removed
        # Bug: All items except first page are removed (full refresh)
        assert items_after == items_before - 1, (
            f"Expected {items_before - 1} items after delete, but got {items_after}. "
            f"The delete operation appears to have triggered a full page refresh instead of "
            f"removing only the deleted item from the DOM."
        )


class TestBug005Detection:
    """Bug detection tests: Explicitly check that BUG-005 does NOT manifest.

    These tests fail with explicit BUG-005 messages if the bug is present.
    They make it IMPOSSIBLE to misdiagnose the failure cause.
    """

    def test_bug_005_no_scroll_reset_after_delete(
        self, page: Page, bug005_app_server: str
    ):
        """BUG-005: Fail explicitly if scroll position resets to top after delete.

        This test directly checks for the bug condition and fails with a clear
        BUG-005 message if the bug manifests.
        """
        page.goto(bug005_app_server)
        page.wait_for_load_state("networkidle")

        # Scroll to load multiple pages
        scroll_before = scroll_to_load_multiple_pages(page)

        # Verify we're scrolled down (not at top)
        assert scroll_before > 100, (
            f"Test setup failed: expected scroll position > 100, got {scroll_before}"
        )

        # Find a visible file item to delete
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the file
        delete_btn = file_item.locator(".action-btn:has-text('Delete')")
        if delete_btn.count() > 0:
            delete_btn.click()
        else:
            file_item.click(button="right")
            page.locator("text=Delete").click()

        # Wait for delete to complete
        page.wait_for_timeout(500)

        # Get scroll position after delete
        scroll_after = page.evaluate("window.scrollY")

        # Check if scroll position was reset (bug condition)
        scroll_reset_to_top = scroll_after < 50  # Near the top
        scroll_changed_significantly = abs(scroll_after - scroll_before) > 100

        assert not (scroll_reset_to_top or scroll_changed_significantly), (
            f"BUG-005: Delete should not reset scroll position! "
            f"Scroll was at {scroll_before}px, now at {scroll_after}px. "
            f"The delete handler is calling loadDirectory() which resets pagination state, "
            f"clears fileGrid.innerHTML, and only loads the first page. "
            f"Instead, the deleted item should be removed directly from the DOM without refreshing."
        )

    def test_bug_005_no_load_directory_call_after_delete(
        self, page: Page, bug005_app_server: str
    ):
        """BUG-005: Fail explicitly if delete triggers a browse API call.

        This test intercepts network requests to detect if loadDirectory() was called
        after the delete operation (which would cause the scroll reset).
        """
        page.goto(bug005_app_server)
        page.wait_for_load_state("networkidle")

        # Scroll to load multiple pages
        scroll_to_load_multiple_pages(page)

        # Track browse API calls
        browse_calls = []

        def on_request(request):
            if "/api/browse" in request.url:
                browse_calls.append(request.url)

        page.on("request", on_request)

        # Clear any previous calls
        browse_calls.clear()

        # Find a visible file item to delete
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the file
        delete_btn = file_item.locator(".action-btn:has-text('Delete')")
        if delete_btn.count() > 0:
            delete_btn.click()
        else:
            file_item.click(button="right")
            page.locator("text=Delete").click()

        # Wait for any network activity
        page.wait_for_timeout(1000)

        # Check if any browse calls were made after delete
        assert len(browse_calls) == 0, (
            f"BUG-005: Delete should not trigger /api/browse call! "
            f"Found {len(browse_calls)} browse call(s) after delete: {browse_calls}. "
            f"The delete handler is calling loadDirectory(state.currentPath) which makes "
            f"a new browse request with offset=0, causing all previously loaded items to be lost. "
            f"Instead, the deleted item should be removed directly from the DOM."
        )

    def test_bug_005_no_dom_clear_after_delete(
        self, page: Page, bug005_app_server: str
    ):
        """BUG-005: Fail explicitly if delete clears and reloads the file list.

        This test checks that after delete, items from page 2+ are still present
        (not cleared by fileGrid.innerHTML = '').
        """
        page.goto(bug005_app_server)
        page.wait_for_load_state("networkidle")

        # Scroll to load multiple pages
        scroll_to_load_multiple_pages(page)

        # Get items from the second page (files with higher numbers)
        # PAGE_SIZE is 50, so files 50-99 are on page 2
        # Find a file from the second page to verify it's loaded
        page.wait_for_timeout(500)

        # Count total items - should be more than PAGE_SIZE if infinite scroll worked
        items_before = page.locator(".file-item, .folder-item").count()

        # Verify we have items from multiple pages
        assert items_before > 50, (
            f"Test setup failed: expected more than 50 items (multiple pages), got {items_before}"
        )

        # Find a file item to delete
        file_item = page.locator(".file-item").first
        expect(file_item).to_be_visible()

        # Accept the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the file
        delete_btn = file_item.locator(".action-btn:has-text('Delete')")
        if delete_btn.count() > 0:
            delete_btn.click()
        else:
            file_item.click(button="right")
            page.locator("text=Delete").click()

        # Wait for delete to complete
        page.wait_for_timeout(500)

        # Count items after delete
        items_after = page.locator(".file-item, .folder-item").count()

        # The bug clears DOM and reloads only first page (50 items)
        # Expected behavior: items_before - 1
        # Buggy behavior: 50 or less

        assert items_after > 50, (
            f"BUG-005: Delete should not clear the file list! "
            f"Started with {items_before} items, now have {items_after} items. "
            f"The delete handler is calling loadDirectory() which sets "
            f"fileGrid.innerHTML = '' and only loads the first page (50 items). "
            f"Previously loaded items from pages 2+ should still be in the DOM."
        )

        # More specific check: we should have lost exactly 1 item
        assert items_after == items_before - 1, (
            f"BUG-005: Delete removed {items_before - items_after} items instead of 1! "
            f"Started with {items_before} items, now have {items_after} items. "
            f"Expected exactly {items_before - 1} items after deleting one file."
        )

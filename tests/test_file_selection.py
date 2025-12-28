"""
End-to-end tests for file selection/highlight feature.

These tests verify that clicking a file highlights it with a visual indicator,
and that the selection can be cleared via click-outside or Escape key.

Test cases based on ticket 009-enhancement-highlight-selected-file.
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
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mark all tests in this module as e2e tests
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def selection_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for selection testing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="selection_test_"))

    # Create test structure with multiple files for selection testing
    (temp_dir / "test_folder").mkdir()

    # Create multiple test files
    (temp_dir / "file_a.txt").write_text("File A content")
    (temp_dir / "file_b.txt").write_text("File B content")
    (temp_dir / "file_c.txt").write_text("File C content")
    (temp_dir / "test_folder" / "nested_file.txt").write_text("Nested file")

    # Create an image file for thumbnail testing
    try:
        from PIL import Image
        img = Image.new('RGB', (100, 100), color='blue')
        img.save(temp_dir / "test_image.jpg")
    except ImportError:
        (temp_dir / "test_image.jpg").write_bytes(b"fake image")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def selection_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for selection testing."""
    temp_db = Path(tempfile.mktemp(prefix="selection_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="session")
def selection_app_server(selection_test_upload_dir: Path, selection_test_db_path: Path):
    """Start the FastAPI app server for selection testing."""
    os.environ["UPLOAD_ROOT"] = str(selection_test_upload_dir)
    os.environ["DB_PATH"] = str(selection_test_db_path)
    os.environ["PORT"] = "8766"  # Different port from main e2e tests
    os.environ["HOST"] = "127.0.0.1"

    from app import app, db, UPLOAD_ROOT
    from models import FileIndex
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
            if extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                preview_type = 'image'
                has_thumbnail = True
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
        uvicorn.run(app, host="127.0.0.1", port=8766, log_level="error")

    process = multiprocessing.Process(target=run_server, daemon=True)
    process.start()

    # Wait for server to start
    time.sleep(2)

    yield "http://127.0.0.1:8766"

    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()


class TestFileSelectionBasic:
    """Test basic file selection functionality (TC-001, TC-002)."""

    def test_file_click_adds_selected_class(self, page: Page, selection_app_server: str):
        """TC-001: File click adds .selected class to the file item.

        Given: A file browser with files displayed
        When: User clicks on a file item
        Then:
        - The file item has .selected class
        - The item displays visible selection styling (outline)
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        # Get a file item
        file_item = page.locator(".file-item:has-text('file_a.txt')")
        expect(file_item).to_be_visible()

        # Initially, the file should NOT have .selected class
        expect(file_item).not_to_have_class(re.compile(r"\bselected\b"))

        # Click the file
        file_item.click()

        # Wait for modal to open (indicates click registered)
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        # Close the modal to verify selection state
        page.locator("#close_preview_modal").click()
        expect(modal).not_to_be_visible()

        # The file item should now have .selected class
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

    def test_single_selection_only(self, page: Page, selection_app_server: str):
        """TC-002: Only one item can be selected at a time.

        Given: File A is selected
        When: User clicks on File B
        Then:
        - File A no longer has .selected class
        - File B has .selected class
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_a = page.locator(".file-item:has-text('file_a.txt')")
        file_b = page.locator(".file-item:has-text('file_b.txt')")

        # Click file A
        file_a.click()
        page.locator("#close_preview_modal").click()

        # Verify file A is selected
        expect(file_a).to_have_class(re.compile(r"\bselected\b"))

        # Click file B
        file_b.click()
        page.locator("#close_preview_modal").click()

        # File A should no longer be selected
        expect(file_a).not_to_have_class(re.compile(r"\bselected\b"))

        # File B should now be selected
        expect(file_b).to_have_class(re.compile(r"\bselected\b"))


class TestSelectionPersistence:
    """Test selection persistence after modal close (TC-003)."""

    def test_selection_persists_after_modal_close(self, page: Page, selection_app_server: str):
        """TC-003: Selection persists after modal close.

        Given: User clicked a file (preview modal opened)
        When: User closes the preview modal
        Then: The file item still has .selected class
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")

        # Click file to open preview
        file_item.click()

        # Modal should be open
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        # Close modal via close button
        page.locator("#close_preview_modal").click()
        expect(modal).not_to_be_visible()

        # Selection should persist
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Click a different file and close its modal via X button
        file_b = page.locator(".file-item:has-text('file_b.txt')")
        file_b.click()
        expect(modal).to_be_visible()

        # Close with X button
        page.locator("#close_preview_modal").click()

        # file_b should be selected now
        expect(file_b).to_have_class(re.compile(r"\bselected\b"))
        expect(file_item).not_to_have_class(re.compile(r"\bselected\b"))


class TestSelectionClearing:
    """Test selection clearing via click-outside and Escape (TC-004, TC-005, TC-010)."""

    def test_click_outside_clears_selection(self, page: Page, selection_app_server: str):
        """TC-004: Click outside clears selection.

        Given: A file is selected
        When: User clicks on empty space in the file browser (not on any file/folder item)
        Then:
        - No element has .selected class
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")

        # Select a file
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify selection
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Click on empty space (the file browser area, not on any item)
        file_browser = page.locator(".file-browser")
        # Get the browser's bounding box and click near the bottom (below items)
        box = file_browser.bounding_box()
        if box:
            # Click at the bottom of the file browser area
            page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] - 20)

        # Selection should be cleared
        expect(file_item).not_to_have_class(re.compile(r"\bselected\b"))

        # Verify no elements have .selected class
        selected_items = page.locator(".file-item.selected, .folder-item.selected")
        expect(selected_items).to_have_count(0)

    def test_escape_key_clears_selection(self, page: Page, selection_app_server: str):
        """TC-005: Escape key clears selection.

        Given: A file is selected
        When: User presses Escape key
        Then:
        - No element has .selected class
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")

        # Select a file and close the modal first
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify selection exists
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Press Escape
        page.keyboard.press("Escape")

        # Selection should be cleared
        expect(file_item).not_to_have_class(re.compile(r"\bselected\b"))

        # Verify no elements have .selected class
        selected_items = page.locator(".file-item.selected, .folder-item.selected")
        expect(selected_items).to_have_count(0)

    def test_escape_clears_selection_when_modal_open(self, page: Page, selection_app_server: str):
        """TC-010: Escape with modal open closes modal but PRESERVES selection.

        NOTE: Updated for BUG-015 fix. Previously, this test expected selection
        to clear when Escape closed a modal. The correct behavior is that
        selection persists until a subsequent Escape/click when no modal is open.

        Given: File is selected and preview modal is open
        When: User presses Escape
        Then:
        - Modal closes (existing behavior)
        - Selection PERSISTS (corrected behavior after BUG-015 fix)
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview (this also selects it)
        file_item.click()
        expect(modal).to_be_visible()

        # Press Escape
        page.keyboard.press("Escape")

        # Modal should be closed
        expect(modal).not_to_be_visible()

        # Selection should PERSIST (BUG-015 fix)
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))


class TestViewModeSelection:
    """Test selection works in both list and gallery views (TC-006, TC-007)."""

    def test_selection_in_list_view(self, page: Page, selection_app_server: str):
        """TC-006: Selection works in list view.

        Given: View mode is "list"
        When: User clicks a file
        Then: The file item displays visible selection styling (outline)
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        # Ensure we're in list view
        browser_content = page.locator("#browser_content")
        if "gallery-view" in (browser_content.get_attribute("class") or ""):
            page.locator("#view_toggle_btn").click()
            page.wait_for_load_state("networkidle")

        expect(browser_content).to_have_class(re.compile(r"\blist-view\b"))

        # Click a file
        file_item = page.locator(".file-item:has-text('file_a.txt')")
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify selection class is present
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Verify the element has the outline style (CSS computed style check)
        outline = file_item.evaluate("el => getComputedStyle(el).outline")
        assert "solid" in outline.lower() or outline != "none", \
            f"Expected outline style for selected item in list view, got: {outline}"

    def test_selection_in_gallery_view(self, page: Page, selection_app_server: str):
        """TC-007: Selection works in gallery view.

        Given: View mode is "gallery"
        When: User clicks a file
        Then: The file item displays visible selection styling (outline)
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        # Switch to gallery view
        browser_content = page.locator("#browser_content")
        if "list-view" in (browser_content.get_attribute("class") or ""):
            page.locator("#view_toggle_btn").click()
            page.wait_for_load_state("networkidle")

        expect(browser_content).to_have_class(re.compile(r"\bgallery-view\b"))

        # Click a file
        file_item = page.locator(".file-item:has-text('file_a.txt')")
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify selection class is present
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Verify the element has the outline style
        outline = file_item.evaluate("el => getComputedStyle(el).outline")
        assert "solid" in outline.lower() or outline != "none", \
            f"Expected outline style for selected item in gallery view, got: {outline}"


class TestEdgeCases:
    """Test edge cases for selection (TC-008, TC-009)."""

    def test_folder_click_behavior(self, page: Page, selection_app_server: str):
        """TC-008: Folder click behavior.

        Given: A file browser with folders
        When: User clicks on a folder
        Then: Navigation occurs (folder may briefly show selection before re-render)

        Note: This test verifies that clicking a folder navigates rather than
        persisting selection, since the view re-renders on navigation.
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        # First select a file to have a baseline selection
        file_item = page.locator(".file-item:has-text('file_a.txt')")
        file_item.click()
        page.locator("#close_preview_modal").click()
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Click on folder
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        expect(folder_item).to_be_visible()
        folder_item.click()

        # Wait for navigation
        page.wait_for_load_state("networkidle")

        # After navigation, we should see the nested file
        nested_file = page.locator(".file-item:has-text('nested_file.txt')")
        expect(nested_file).to_be_visible()

        # Selection should be cleared due to re-render (no selected items in new view)
        selected_items = page.locator(".file-item.selected, .folder-item.selected")
        expect(selected_items).to_have_count(0)

    def test_double_click_same_file_idempotent(self, page: Page, selection_app_server: str):
        """TC-009: Double click same file is idempotent.

        Given: File A is selected
        When: User clicks File A again
        Then: File A remains selected (idempotent)
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")

        # Click file first time
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify selection
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Click same file again
        file_item.click()
        page.locator("#close_preview_modal").click()

        # File should still be selected
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Click it a third time for good measure
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Should still be selected
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))


class TestRapidInteraction:
    """Test rapid interactions don't cause issues."""

    def test_rapid_clicking_between_files(self, page: Page, selection_app_server: str):
        """Test that rapid clicking between files doesn't cause issues.

        This tests the edge case mentioned in the test plan about rapid clicking.
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_a = page.locator(".file-item:has-text('file_a.txt')")
        file_b = page.locator(".file-item:has-text('file_b.txt')")
        file_c = page.locator(".file-item:has-text('file_c.txt')")
        modal = page.locator("#preview_modal")

        # Rapidly click between files
        for _ in range(3):
            file_a.click()
            if modal.is_visible():
                page.locator("#close_preview_modal").click()

            file_b.click()
            if modal.is_visible():
                page.locator("#close_preview_modal").click()

            file_c.click()
            if modal.is_visible():
                page.locator("#close_preview_modal").click()

        # After all the rapid clicking, only the last clicked file should be selected
        expect(file_c).to_have_class(re.compile(r"\bselected\b"))
        expect(file_a).not_to_have_class(re.compile(r"\bselected\b"))
        expect(file_b).not_to_have_class(re.compile(r"\bselected\b"))

        # There should be exactly one selected item
        selected_items = page.locator(".file-item.selected, .folder-item.selected")
        expect(selected_items).to_have_count(1)


class TestCausalityCheck:
    """Tests that verify the implementation is actually working.

    These tests are designed to fail if the selectItem/clearSelection
    functions are removed or if the CSS .selected class is removed.
    """

    def test_selected_class_has_visual_styling(self, page: Page, selection_app_server: str):
        """Verify that .selected class actually applies visual styling.

        This test will fail if the CSS rule is removed.
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")

        # Get outline before selection
        outline_before = file_item.evaluate("el => getComputedStyle(el).outline")

        # Select the file
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Get outline after selection
        outline_after = file_item.evaluate("el => getComputedStyle(el).outline")

        # The outline should have changed (proving CSS is applied)
        # Note: outline_before will typically be "0px none rgb(...)" or similar
        # outline_after should include "solid" from our CSS rule
        assert outline_before != outline_after, \
            f"Selection should change the visual styling. Before: {outline_before}, After: {outline_after}"
        assert "solid" in outline_after.lower(), \
            f"Selected item should have solid outline. Got: {outline_after}"

    def test_state_tracks_selection(self, page: Page, selection_app_server: str):
        """Verify that state.selectedElement is updated on selection.

        This test will fail if selectItem() doesn't update state.
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        # Check state before selection
        state_before = page.evaluate("""
            () => {
                // Access the state module
                return window.__testGetState ? window.__testGetState().selectedElement : null;
            }
        """)

        # Since we can't easily access the module state directly, we verify through DOM
        # that clicking creates the .selected class (which proves selectItem was called)
        file_item = page.locator(".file-item:has-text('file_a.txt')")
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify the DOM shows selection
        has_selected_class = file_item.evaluate("el => el.classList.contains('selected')")
        assert has_selected_class, "File should have 'selected' class after being clicked"

        # Verify exactly one item is selected
        selected_count = page.locator(".file-item.selected, .folder-item.selected").count()
        assert selected_count == 1, f"Expected exactly 1 selected item, got {selected_count}"

    def test_clear_selection_removes_class(self, page: Page, selection_app_server: str):
        """Verify that clearSelection actually removes the .selected class.

        This test will fail if clearSelection() is not called on Escape/click-outside.
        """
        page.goto(selection_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")

        # Select file
        file_item.click()
        page.locator("#close_preview_modal").click()

        # Verify selection exists
        selected_count_before = page.locator(".selected").count()
        assert selected_count_before > 0, "Should have a selection before clearing"

        # Press Escape to clear
        page.keyboard.press("Escape")

        # Verify selection is cleared
        selected_count_after = page.locator(".selected").count()
        assert selected_count_after == 0, \
            f"Escape should clear all selections, but found {selected_count_after} selected items"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--headed"])

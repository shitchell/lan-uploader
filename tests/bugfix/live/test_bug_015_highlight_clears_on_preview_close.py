"""
BUG-015: File highlight clears when closing preview modal.

This module contains dual tests (success + bug detection) for BUG-015.
The bug manifests when:
1. User clicks a file to open preview (file gets highlighted)
2. User presses Escape or clicks close button to close the preview
3. The file highlight incorrectly clears immediately instead of persisting

EXPECTED BEHAVIOR (after fix):
- Highlight should persist when modal closes
- Highlight should only clear on the NEXT Escape/click (when no modal is open)
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
def bug015_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for BUG-015 testing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="bug015_test_"))

    # Create test structure with multiple files
    (temp_dir / "test_folder").mkdir()
    (temp_dir / "file_a.txt").write_text("File A content")
    (temp_dir / "file_b.txt").write_text("File B content")
    (temp_dir / "file_c.txt").write_text("File C content")
    (temp_dir / "test_folder" / "nested_file.txt").write_text("Nested file")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def bug015_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for BUG-015 testing."""
    temp_db = Path(tempfile.mktemp(prefix="bug015_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def bug015_app_server(bug015_test_upload_dir: Path, bug015_test_db_path: Path):
    """Start the FastAPI app server for BUG-015 testing."""
    import time
    import multiprocessing

    os.environ["UPLOAD_ROOT"] = str(bug015_test_upload_dir)
    os.environ["DB_PATH"] = str(bug015_test_db_path)
    os.environ["PORT"] = "8767"  # Unique port for BUG-015 tests
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
        uvicorn.run(app, host="127.0.0.1", port=8767, log_level="error")

    server_process = multiprocessing.Process(target=run_server, daemon=True)
    server_process.start()

    # Wait for server to start
    time.sleep(2)

    yield "http://127.0.0.1:8767"

    server_process.terminate()
    server_process.join(timeout=5)
    if server_process.is_alive():
        server_process.kill()


class TestBug015HighlightPersistsAfterPreviewClose:
    """Success tests: Verify expected behavior after BUG-015 fix.

    These tests verify that the highlight PERSISTS after closing the preview modal.
    They will FAIL on the buggy codebase (before fix) and PASS after fix.
    """

    def test_highlight_persists_after_escape_closes_preview(
        self, page: Page, bug015_app_server: str
    ):
        """Verify highlight persists after pressing Escape to close preview modal.

        Given: File is clicked (opens preview and highlights file)
        When: User presses Escape to close the preview
        Then: File highlight should PERSIST (not clear)
        """
        page.goto(bug015_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview (this also selects it)
        file_item.click()
        expect(modal).to_be_visible()
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Press Escape to close modal
        page.keyboard.press("Escape")

        # Modal should close
        expect(modal).not_to_be_visible()

        # Highlight should PERSIST (this fails on buggy code)
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

    def test_highlight_persists_after_click_outside_closes_preview(
        self, page: Page, bug015_app_server: str
    ):
        """Verify highlight persists after clicking close button on preview modal.

        Given: File is clicked (opens preview and highlights file)
        When: User clicks the modal close button
        Then: File highlight should PERSIST (not clear)
        """
        page.goto(bug015_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview
        file_item.click()
        expect(modal).to_be_visible()
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Click close button on modal
        close_button = page.locator("#close_preview_modal")
        close_button.click()

        # Modal should close
        expect(modal).not_to_be_visible()

        # Highlight should PERSIST (this fails on buggy code)
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

    def test_second_escape_clears_highlight_when_no_modal_open(
        self, page: Page, bug015_app_server: str
    ):
        """Verify highlight clears on SECOND Escape (after modal already closed).

        Given: File is clicked, preview opened, then closed with Escape (highlight persists)
        When: User presses Escape again (no modal open)
        Then: File highlight should NOW clear

        This tests the full intended workflow: first Escape closes modal, second clears selection.
        """
        page.goto(bug015_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview
        file_item.click()
        expect(modal).to_be_visible()
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # First Escape - close modal (highlight should persist)
        page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()

        # On buggy code, highlight is already gone here, so the second
        # assertion below will fail for a different reason
        # This test will fail on buggy code because first Escape clears selection
        expect(file_item).to_have_class(re.compile(r"\bselected\b"))

        # Second Escape - should now clear selection (no modal open)
        page.keyboard.press("Escape")

        # NOW highlight should be cleared
        expect(file_item).not_to_have_class(re.compile(r"\bselected\b"))


class TestBug015Detection:
    """Bug detection tests: Explicitly check that BUG-015 does NOT manifest.

    These tests fail with explicit BUG-015 messages if the bug is present.
    They make it IMPOSSIBLE to misdiagnose the failure cause.
    """

    def test_bug_015_no_highlight_clear_on_escape_when_modal_open(
        self, page: Page, bug015_app_server: str
    ):
        """BUG-015: Fail explicitly if highlight clears when pressing Escape to close modal.

        This test directly checks for the bug condition and fails with a clear
        BUG-015 message if the bug manifests.
        """
        page.goto(bug015_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview
        file_item.click()
        expect(modal).to_be_visible()

        # Press Escape to close modal
        page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()

        # Wait a moment for any async state updates
        page.wait_for_timeout(100)

        # Check if bug manifested
        class_attr = file_item.get_attribute("class") or ""
        has_selected_class = "selected" in class_attr

        assert has_selected_class, (
            "BUG-015: File highlight should persist after closing preview modal! "
            "The highlight was cleared when pressing Escape to close the preview, "
            "but it should only clear on the NEXT Escape/click (when no modal is open). "
            "The Escape handler is calling clearSelection() unconditionally instead of "
            "checking if a modal is currently open first."
        )

    def test_bug_015_no_highlight_clear_on_modal_close_button_click(
        self, page: Page, bug015_app_server: str
    ):
        """BUG-015: Fail explicitly if highlight clears when clicking modal close button.

        This test directly checks for the bug condition and fails with a clear
        BUG-015 message if the bug manifests.
        """
        page.goto(bug015_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview
        file_item.click()
        expect(modal).to_be_visible()

        # Click close button
        close_button = page.locator("#close_preview_modal")
        close_button.click()
        expect(modal).not_to_be_visible()

        # Wait a moment for any async state updates
        page.wait_for_timeout(100)

        # Check if bug manifested
        class_attr = file_item.get_attribute("class") or ""
        has_selected_class = "selected" in class_attr

        assert has_selected_class, (
            "BUG-015: File highlight should persist after closing preview modal! "
            "The highlight was cleared when clicking the modal close button, "
            "but it should only clear when clicking outside file items AND no modal is open. "
            "The click handler is calling clearSelection() unconditionally instead of "
            "checking if a modal is currently open first."
        )

    def test_bug_015_state_selectedElement_persists_after_modal_close(
        self, page: Page, bug015_app_server: str
    ):
        """BUG-015: Verify internal state (selectedElement) persists after modal close.

        This test checks the DOM state to verify that exactly one item remains
        selected after closing the modal, indicating the internal state is correct.
        """
        page.goto(bug015_app_server)
        page.wait_for_load_state("networkidle")

        file_item = page.locator(".file-item:has-text('file_a.txt')")
        modal = page.locator("#preview_modal")

        # Click file to open preview
        file_item.click()
        expect(modal).to_be_visible()

        # Press Escape to close modal
        page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()

        # Wait a moment for any async state updates
        page.wait_for_timeout(100)

        # Count selected items in the DOM
        selected_count = page.locator(".file-item.selected, .folder-item.selected").count()

        assert selected_count == 1, (
            f"BUG-015: Expected exactly 1 selected item after closing preview modal, "
            f"but found {selected_count}. The selection state was incorrectly cleared "
            f"when the modal closed. state.selectedElement should still reference the clicked file."
        )

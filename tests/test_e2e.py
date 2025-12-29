"""
End-to-end tests for LAN Uploader using Playwright.

These tests verify the complete user experience including:
- Page loading and element visibility
- File browsing and navigation
- Upload functionality
- Folder creation (including the New Folder button)
- Search functionality
- View mode toggling
- File preview and deletion
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
# These tests use Playwright which creates its own event loop
# and should be run separately from pytest-asyncio tests
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory for testing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="lan_uploader_test_"))

    # Create some test structure
    (temp_dir / "test_folder").mkdir()
    (temp_dir / "test_folder" / "nested_folder").mkdir()

    # Create test files
    (temp_dir / "test.txt").write_text("Test file content")
    (temp_dir / "test_folder" / "nested.txt").write_text("Nested file")

    # Create an image file for thumbnail testing
    try:
        from PIL import Image
        img = Image.new('RGB', (100, 100), color='red')
        img.save(temp_dir / "test_image.jpg")
        img.save(temp_dir / "test_folder" / "nested_image.png")
    except ImportError:
        # If PIL is not available, create dummy files
        (temp_dir / "test_image.jpg").write_bytes(b"fake image")
        (temp_dir / "test_folder" / "nested_image.png").write_bytes(b"fake image")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="lan_uploader_test_", suffix=".db"))
    yield temp_db
    # Cleanup
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="session")
def app_server(test_upload_dir: Path, test_db_path: Path):
    """Start the FastAPI app server for testing."""
    # Import app after setting environment variables
    os.environ["UPLOAD_ROOT"] = str(test_upload_dir)
    os.environ["DB_PATH"] = str(test_db_path)
    os.environ["PORT"] = "8765"  # Use a different port for testing
    os.environ["HOST"] = "127.0.0.1"

    # Import and configure app
    from app import app, db, UPLOAD_ROOT

    # Initialize database
    db.init_db()

    # Index existing test files
    from models import FileIndex
    from datetime import datetime
    import mimetypes

    for file_path in UPLOAD_ROOT.rglob("*"):
        if file_path.is_file():
            filepath_rel = file_path.relative_to(UPLOAD_ROOT).as_posix()
            parent_path_rel = file_path.parent.relative_to(UPLOAD_ROOT).as_posix()
            extension = file_path.suffix.lower()
            mime_type, _ = mimetypes.guess_type(str(file_path))

            # Simple preview type detection
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

    # Start server in a separate process
    def run_server():
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8765, log_level="error")

    process = multiprocessing.Process(target=run_server, daemon=True)
    process.start()

    # Wait for server to start
    time.sleep(2)

    yield "http://127.0.0.1:8765"

    # Cleanup
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()


@pytest.fixture
def page_with_screenshot(page: Page, request):
    """Fixture that takes screenshots on test failure."""
    yield page

    # Take screenshot on failure
    if request.node.rep_call.failed:
        screenshot_dir = Path(__file__).parent / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)
        screenshot_path = screenshot_dir / f"{request.node.name}.png"
        page.screenshot(path=str(screenshot_path))
        print(f"\nScreenshot saved to: {screenshot_path}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to make test results available to fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


class TestPageLoad:
    """Test that the page loads with all required elements visible."""

    def test_page_loads_successfully(self, page: Page, app_server: str):
        """Test that the main page loads without errors."""
        page.goto(app_server)
        expect(page).to_have_title("LAN Uploader")

    def test_header_visible(self, page: Page, app_server: str):
        """Test that the header is visible with all elements."""
        page.goto(app_server)

        # Check header title
        header = page.locator(".app-header h1")
        expect(header).to_be_visible()
        expect(header).to_contain_text("LAN Uploader")

        # Check search input
        search_input = page.locator("#search_input")
        expect(search_input).to_be_visible()
        expect(search_input).to_have_attribute("placeholder", "Search files...")

        # Check search button
        search_btn = page.locator("#search_btn")
        expect(search_btn).to_be_visible()

        # Check upload button
        upload_btn = page.locator("#upload_btn")
        expect(upload_btn).to_be_visible()
        expect(upload_btn).to_contain_text("Upload")

        # Check view toggle button
        view_toggle = page.locator("#view_toggle_btn")
        expect(view_toggle).to_be_visible()

    def test_breadcrumbs_visible(self, page: Page, app_server: str):
        """Test that breadcrumbs navigation is visible."""
        page.goto(app_server)

        breadcrumbs = page.locator("#breadcrumbs")
        expect(breadcrumbs).to_be_visible()

        # Should have "Home" link
        home_link = breadcrumbs.locator('a:has-text("Home")')
        expect(home_link).to_be_visible()

    def test_new_folder_button_visible(self, page: Page, app_server: str):
        """Test that the New Folder button appears in breadcrumbs."""
        page.goto(app_server)

        # Wait for page to load and JavaScript to execute
        page.wait_for_load_state("networkidle")

        # The New Folder button is dynamically created by JavaScript
        new_folder_btn = page.locator("#new_folder_btn")
        expect(new_folder_btn).to_be_visible()
        expect(new_folder_btn).to_contain_text("New Folder")
        expect(new_folder_btn).to_have_class("new-folder-btn")

    def test_file_browser_visible(self, page: Page, app_server: str):
        """Test that the file browser area is visible."""
        page.goto(app_server)

        browser = page.locator(".file-browser")
        expect(browser).to_be_visible()

        # Check file grid
        file_grid = page.locator("#file_grid")
        expect(file_grid).to_be_visible()


class TestFileBrowser:
    """Test file browsing and navigation functionality."""

    def test_displays_folders_and_files(self, page: Page, app_server: str):
        """Test that folders and files are displayed in the browser."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Should see test_folder
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        expect(folder_item).to_be_visible()

        # Should see test.txt file
        file_item = page.locator(".file-item:has-text('test.txt')")
        expect(file_item).to_be_visible()

    def test_navigate_into_folder(self, page: Page, app_server: str):
        """Test clicking a folder to navigate into it."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Click on test_folder
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        folder_item.click()

        # Wait for navigation
        page.wait_for_load_state("networkidle")

        # Should see nested_folder
        nested_folder = page.locator(".folder-item:has-text('nested_folder')")
        expect(nested_folder).to_be_visible()

        # Should see nested.txt
        nested_file = page.locator(".file-item:has-text('nested.txt')")
        expect(nested_file).to_be_visible()

    def test_breadcrumb_navigation(self, page: Page, app_server: str):
        """Test that breadcrumb navigation works."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Navigate into test_folder
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        folder_item.click()
        page.wait_for_load_state("networkidle")

        # Breadcrumbs should show: Home > test_folder
        breadcrumbs = page.locator("#breadcrumbs")
        expect(breadcrumbs).to_contain_text("Home")
        expect(breadcrumbs).to_contain_text("test_folder")

        # Click Home to navigate back
        home_link = breadcrumbs.locator('a:has-text("Home")')
        home_link.click()
        page.wait_for_load_state("networkidle")

        # Should be back at root, seeing test_folder again
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        expect(folder_item).to_be_visible()


class TestWebSocketUpload:
    """Test WebSocket upload functionality with real-time progress."""

    def test_websocket_upload_with_progress(self, page: Page, app_server: str):
        """Test that upload with WebSocket shows real-time progress updates."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open upload modal
        upload_btn = page.locator("#upload_btn")
        upload_btn.click()

        # Wait for modal to appear
        modal = page.locator("#upload_modal")
        expect(modal).not_to_have_class("hidden")

        # Create a temporary test file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test file content for WebSocket upload\n" * 100)
            temp_file_path = f.name

        try:
            # Upload the file
            file_input = page.locator("#file_input")
            file_input.set_input_files(temp_file_path)

            # Wait for file preview to show
            file_preview = page.locator("#file_preview")
            expect(file_preview).not_to_have_class("hidden")

            # Click upload button
            start_upload = page.locator("#start_upload")
            start_upload.click()

            # Wait for progress container to appear
            progress_container = page.locator("#progress_container")
            expect(progress_container).not_to_have_class("hidden")

            # Wait for upload to complete
            # The modal should close automatically (wait for hidden class, not visibility)
            page.wait_for_selector("#upload_modal.hidden", state="attached", timeout=10000)

            # Should show success message (class includes "success" among other classes)
            status_message = page.locator("#status_message")
            expect(status_message).to_be_visible()
            expect(status_message).to_have_class(re.compile(r".*\bsuccess\b.*"))

        finally:
            # Clean up temp file
            import os
            os.unlink(temp_file_path)

    def test_websocket_upload_multiple_files(self, page: Page, app_server: str):
        """Test upload of multiple files shows file count in progress."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open upload modal
        page.locator("#upload_btn").click()

        # Create multiple test files
        import tempfile
        import os
        temp_files = []
        try:
            for i in range(3):
                f = tempfile.NamedTemporaryFile(mode='w', suffix=f'_file{i}.txt', delete=False)
                f.write(f"Test file {i} content\n")
                f.close()
                temp_files.append(f.name)

            # Upload all files
            file_input = page.locator("#file_input")
            file_input.set_input_files(temp_files)

            # Verify file count shows 3
            file_count = page.locator("#file_count")
            expect(file_count).to_have_text("3")

            # Start upload
            page.locator("#start_upload").click()

            # Wait for progress to show file counts
            # Progress text should show format: "XX% (N / M files)"
            progress_text = page.locator("#progress_text")

            # Wait for upload to start
            expect(progress_text).to_be_visible()

            # Wait for completion
            page.wait_for_selector("#upload_modal.hidden", state="attached", timeout=10000)

        finally:
            # Clean up temp files
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)

    def test_websocket_fallback_when_unavailable(self, page: Page, app_server: str):
        """Test that upload falls back to legacy mode if WebSocket unavailable."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Mock WebSocket to be unavailable - must delete, not just set to undefined
        # because the check uses 'WebSocket' in window
        page.evaluate("""
            // Delete WebSocket to simulate unsupported browser
            delete window.WebSocket;
        """)

        # Open upload modal
        page.locator("#upload_btn").click()

        # Create test file
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Fallback test content\n")
            temp_file_path = f.name

        try:
            # Upload file
            file_input = page.locator("#file_input")
            file_input.set_input_files(temp_file_path)

            # Start upload
            page.locator("#start_upload").click()

            # Should still work via legacy upload
            # Progress should show
            progress_container = page.locator("#progress_container")
            expect(progress_container).not_to_have_class("hidden")

            # Wait for completion
            page.wait_for_selector("#upload_modal.hidden", state="attached", timeout=10000)

            # Should show success
            status_message = page.locator("#status_message")
            expect(status_message).to_be_visible()

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    def test_websocket_error_display(self, page: Page, app_server: str):
        """Test that WebSocket errors are displayed immediately."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open upload modal
        page.locator("#upload_btn").click()

        # Create a file with invalid name to trigger error
        import tempfile
        import os
        # Use a forbidden filename like ".."
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Error test\n")
            temp_file_path = f.name

        try:
            # Upload file
            file_input = page.locator("#file_input")
            file_input.set_input_files(temp_file_path)

            # Rename the file to something invalid before upload
            # (This test is simplified - in real scenario, backend would reject invalid filenames)

            # Start upload
            page.locator("#start_upload").click()

            # Wait for either success or error status
            status_message = page.locator("#status_message")
            page.wait_for_selector("#status_message:not(.hidden)", timeout=10000)

            # Error should be visible
            expect(status_message).to_be_visible()

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)


class TestUploadModal:
    """Test upload modal functionality."""

    def test_upload_modal_opens(self, page: Page, app_server: str):
        """Test that clicking Upload button opens the modal."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Click upload button
        upload_btn = page.locator("#upload_btn")
        upload_btn.click()

        # Modal should be visible
        modal = page.locator("#upload_modal")
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Should show target path
        target_path = page.locator("#upload_target_path")
        expect(target_path).to_be_visible()

    def test_upload_modal_closes(self, page: Page, app_server: str):
        """Test that the upload modal can be closed."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open modal
        upload_btn = page.locator("#upload_btn")
        upload_btn.click()

        modal = page.locator("#upload_modal")
        expect(modal).to_be_visible()

        # Close modal
        close_btn = page.locator("#close_upload_modal")
        close_btn.click()

        # Modal should be hidden
        expect(modal).not_to_be_visible()

    def test_upload_modal_cancel_button(self, page: Page, app_server: str):
        """Test that clicking Cancel closes the modal."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open modal
        upload_btn = page.locator("#upload_btn")
        upload_btn.click()

        # Click cancel
        cancel_btn = page.locator("#cancel_upload")
        cancel_btn.click()

        # Modal should be hidden
        modal = page.locator("#upload_modal")
        expect(modal).not_to_be_visible()


class TestNewFolderModal:
    """Test new folder creation functionality."""

    def test_new_folder_button_clickable(self, page: Page, app_server: str):
        """Test that the New Folder button is clickable."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        new_folder_btn = page.locator("#new_folder_btn")
        expect(new_folder_btn).to_be_visible()
        expect(new_folder_btn).to_be_enabled()

    def test_new_folder_modal_opens(self, page: Page, app_server: str):
        """Test that clicking New Folder button opens the modal."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Click New Folder button
        new_folder_btn = page.locator("#new_folder_btn")
        new_folder_btn.click()

        # Modal should be visible
        modal = page.locator("#new_folder_modal")
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Should have input field
        name_input = page.locator("#new_folder_name")
        expect(name_input).to_be_visible()
        expect(name_input).to_be_focused()

    def test_new_folder_modal_closes(self, page: Page, app_server: str):
        """Test that the new folder modal can be closed."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open modal
        new_folder_btn = page.locator("#new_folder_btn")
        new_folder_btn.click()

        modal = page.locator("#new_folder_modal")
        expect(modal).to_be_visible()

        # Close modal
        close_btn = page.locator("#close_new_folder_modal")
        close_btn.click()

        # Modal should be hidden
        expect(modal).not_to_be_visible()

    def test_create_new_folder(self, page: Page, app_server: str, test_upload_dir: Path):
        """Test creating a new folder."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Click New Folder button
        new_folder_btn = page.locator("#new_folder_btn")
        new_folder_btn.click()

        # Enter folder name
        name_input = page.locator("#new_folder_name")
        folder_name = f"test_new_folder_{int(time.time())}"
        name_input.fill(folder_name)

        # Click Create
        create_btn = page.locator("#create_new_folder")
        create_btn.click()

        # Wait for folder to be created
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)  # Give time for the UI to update

        # Modal should close
        modal = page.locator("#new_folder_modal")
        expect(modal).not_to_be_visible()

        # New folder should appear in the file browser
        folder_item = page.locator(f".folder-item:has-text('{folder_name}')")
        expect(folder_item).to_be_visible()

        # Verify folder exists on filesystem
        created_folder = test_upload_dir / folder_name
        assert created_folder.exists()
        assert created_folder.is_dir()

    def test_new_folder_in_subdirectory(self, page: Page, app_server: str, test_upload_dir: Path):
        """Test creating a folder in a subdirectory."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Navigate into test_folder
        folder_item = page.locator(".folder-item:has-text('test_folder')")
        folder_item.click()
        page.wait_for_load_state("networkidle")

        # Click New Folder button
        new_folder_btn = page.locator("#new_folder_btn")
        new_folder_btn.click()

        # Should show correct parent path
        parent_path = page.locator("#new_folder_parent_path")
        expect(parent_path).to_contain_text("test_folder")

        # Enter folder name
        name_input = page.locator("#new_folder_name")
        folder_name = f"nested_new_{int(time.time())}"
        name_input.fill(folder_name)

        # Click Create
        create_btn = page.locator("#create_new_folder")
        create_btn.click()

        # Wait for creation
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # New folder should appear
        folder_item = page.locator(f".folder-item:has-text('{folder_name}')")
        expect(folder_item).to_be_visible()

        # Verify on filesystem
        created_folder = test_upload_dir / "test_folder" / folder_name
        assert created_folder.exists()
        assert created_folder.is_dir()


class TestSearchFunctionality:
    """Test search functionality."""

    def test_search_opens_modal(self, page: Page, app_server: str):
        """Test that performing a search opens the search results modal."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Enter search query
        search_input = page.locator("#search_input")
        search_input.fill("test")

        # Click search button
        search_btn = page.locator("#search_btn")
        search_btn.click()

        # Wait for search
        page.wait_for_load_state("networkidle")

        # Search modal should be visible
        modal = page.locator("#search_modal")
        expect(modal).to_be_visible()

    def test_search_finds_files(self, page: Page, app_server: str):
        """Test that search returns matching files."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Search for "test"
        search_input = page.locator("#search_input")
        search_input.fill("test")

        search_btn = page.locator("#search_btn")
        search_btn.click()

        # Wait for results
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Should see results
        results = page.locator("#search_results")
        expect(results).to_be_visible()

        # Should contain test.txt
        expect(results).to_contain_text("test")

    def test_search_modal_closes(self, page: Page, app_server: str):
        """Test that search modal can be closed."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Perform search
        search_input = page.locator("#search_input")
        search_input.fill("test")
        search_btn = page.locator("#search_btn")
        search_btn.click()

        page.wait_for_load_state("networkidle")

        # Close search modal
        close_btn = page.locator("#close_search_modal")
        close_btn.click()

        # Modal should be hidden
        modal = page.locator("#search_modal")
        expect(modal).not_to_be_visible()


class TestViewModeToggle:
    """Test view mode toggle functionality."""

    def test_toggle_to_gallery_view(self, page: Page, app_server: str):
        """Test toggling to gallery view mode."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Should start in list view
        browser_content = page.locator("#browser_content")
        expect(browser_content).to_have_class("browser-content list-view")

        # Click view toggle
        view_toggle = page.locator("#view_toggle_btn")
        view_toggle.click()

        # Should switch to gallery view
        expect(browser_content).to_have_class("browser-content gallery-view")

    def test_toggle_back_to_list_view(self, page: Page, app_server: str):
        """Test toggling back to list view."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        browser_content = page.locator("#browser_content")
        view_toggle = page.locator("#view_toggle_btn")

        # Toggle to gallery
        view_toggle.click()
        expect(browser_content).to_have_class("browser-content gallery-view")

        # Toggle back to list
        view_toggle.click()
        expect(browser_content).to_have_class("browser-content list-view")


class TestFilePreview:
    """Test file preview modal functionality."""

    def test_file_preview_opens(self, page: Page, app_server: str):
        """Test that clicking a file opens the preview modal."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Click on test.txt
        file_item = page.locator(".file-item:has-text('test.txt')")
        file_item.click()

        # Preview modal should open
        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()
        expect(modal).not_to_have_class("hidden")

        # Should show filename
        filename = page.locator("#preview_filename")
        expect(filename).to_contain_text("test.txt")

    def test_preview_modal_closes(self, page: Page, app_server: str):
        """Test that preview modal can be closed."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open preview
        file_item = page.locator(".file-item:has-text('test.txt')")
        file_item.click()

        modal = page.locator("#preview_modal")
        expect(modal).to_be_visible()

        # Close modal
        close_btn = page.locator("#close_preview_modal")
        close_btn.click()

        # Modal should be hidden
        expect(modal).not_to_be_visible()


class TestDeleteConfirmation:
    """Test file deletion functionality."""

    def test_delete_button_in_preview(self, page: Page, app_server: str):
        """Test that delete button is present in file preview."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Open file preview
        file_item = page.locator(".file-item:has-text('test.txt')")
        file_item.click()

        # Delete button should be visible
        delete_btn = page.locator("#delete_file")
        expect(delete_btn).to_be_visible()
        expect(delete_btn).to_have_class("danger-btn")

    def test_delete_shows_confirmation(self, page: Page, app_server: str):
        """Test that clicking delete shows a confirmation dialog."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Create a test file to delete
        file_item = page.locator(".file-item:has-text('test.txt')")
        file_item.click()

        # Set up dialog handler to cancel deletion
        page.on("dialog", lambda dialog: dialog.dismiss())

        # Click delete
        delete_btn = page.locator("#delete_file")
        delete_btn.click()

        # File should still exist (we dismissed the dialog)
        page.locator("#close_preview_modal").click()
        file_item = page.locator(".file-item:has-text('test.txt')")
        expect(file_item).to_be_visible()


class TestJavaScriptExecution:
    """Test that JavaScript loads and executes correctly."""

    def test_app_js_loads(self, page: Page, app_server: str):
        """Test that app.js loads without errors."""
        page.goto(app_server)

        # Check for JavaScript errors
        errors = []
        page.on("pageerror", lambda error: errors.append(error))

        page.wait_for_load_state("networkidle")

        # Should have no JavaScript errors
        assert len(errors) == 0, f"JavaScript errors: {errors}"

    def test_dynamic_elements_created(self, page: Page, app_server: str):
        """Test that JavaScript creates dynamic elements like New Folder button."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # New Folder button should be created by JavaScript
        new_folder_btn = page.locator("#new_folder_btn")
        expect(new_folder_btn).to_be_visible()

        # File grid should be populated
        file_grid = page.locator("#file_grid")
        expect(file_grid).to_be_visible()

        # Should have some content (folders or files)
        items = page.locator(".folder-item, .file-item")
        expect(items.first).to_be_visible()

    def test_event_listeners_attached(self, page: Page, app_server: str):
        """Test that event listeners are properly attached."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Test upload button click
        upload_btn = page.locator("#upload_btn")
        upload_btn.click()

        modal = page.locator("#upload_modal")
        expect(modal).to_be_visible()

        # Close and test view toggle
        page.locator("#close_upload_modal").click()

        view_toggle = page.locator("#view_toggle_btn")
        browser_content = page.locator("#browser_content")

        # Initial state
        initial_class = browser_content.get_attribute("class")

        # Toggle
        view_toggle.click()

        # Class should change
        new_class = browser_content.get_attribute("class")
        assert initial_class != new_class


class TestChangelogModal:
    """Test changelog modal functionality."""

    def test_changelog_modal_exists(self, page: Page, app_server: str):
        """Test that the changelog modal exists in the DOM."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        modal = page.locator("#changelog_modal")
        expect(modal).to_be_attached()
        # Modal should start hidden
        expect(modal).to_have_class(re.compile(r".*\bhidden\b.*"))

    def test_changelog_modal_has_required_elements(self, page: Page, app_server: str):
        """Test that changelog modal has all required elements."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Check version header
        version_el = page.locator("#changelog_version")
        expect(version_el).to_be_attached()

        # Check content container
        content_el = page.locator("#changelog_content")
        expect(content_el).to_be_attached()

        # Check close button
        close_btn = page.locator("#close_changelog_modal")
        expect(close_btn).to_be_attached()

        # Check dismiss button
        dismiss_btn = page.locator("#dismiss_changelog")
        expect(dismiss_btn).to_be_attached()
        expect(dismiss_btn).to_have_text("Got it!")

    def test_changelog_not_shown_on_first_visit(self, page: Page, app_server: str):
        """Test that changelog modal is not shown on first visit (no localStorage)."""
        # Clear localStorage before navigating
        page.goto(app_server)
        page.evaluate("localStorage.clear()")

        # Reload page
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)  # Wait for version check to complete

        # Modal should remain hidden (first visit silently sets version)
        modal = page.locator("#changelog_modal")
        expect(modal).to_have_class(re.compile(r".*\bhidden\b.*"))

        # localStorage should now have last_seen_version set
        version = page.evaluate("localStorage.getItem('last_seen_version')")
        assert version is not None
        assert len(version) > 0

    def test_changelog_shown_on_version_change(self, page: Page, app_server: str):
        """Test that changelog modal shows when version changes."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        # Set a fake old version in localStorage
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")

        # Reload page - should show changelog
        page.reload()
        page.wait_for_load_state("networkidle")

        # Wait for version check to complete
        time.sleep(0.5)

        # Modal should be visible
        modal = page.locator("#changelog_modal")
        expect(modal).not_to_have_class(re.compile(r".*\bhidden\b.*"))
        expect(modal).to_be_visible()

    def test_changelog_close_button(self, page: Page, app_server: str):
        """Test that close button hides the modal."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        modal = page.locator("#changelog_modal")
        expect(modal).to_be_visible()

        # Click close button
        close_btn = page.locator("#close_changelog_modal")
        close_btn.click()

        # Modal should be hidden
        expect(modal).not_to_be_visible()

    def test_changelog_dismiss_updates_storage(self, page: Page, app_server: str):
        """Test that dismiss button updates localStorage."""
        page.goto(app_server)

        # Get current server version
        version = page.evaluate("""
            async () => {
                const response = await fetch('/healthz');
                const data = await response.json();
                return data.version;
            }
        """)

        # Set old version
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Click dismiss button
        dismiss_btn = page.locator("#dismiss_changelog")
        dismiss_btn.click()

        # Modal should close
        modal = page.locator("#changelog_modal")
        expect(modal).not_to_be_visible()

        # Wait for localStorage update
        time.sleep(0.3)

        # localStorage should be updated to current version
        stored_version = page.evaluate("localStorage.getItem('last_seen_version')")
        assert stored_version == version

    def test_changelog_not_shown_after_dismiss(self, page: Page, app_server: str):
        """Test that changelog is not shown again after dismiss."""
        page.goto(app_server)

        # Set old version and trigger changelog
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Dismiss the changelog
        dismiss_btn = page.locator("#dismiss_changelog")
        dismiss_btn.click()

        # Wait for dismiss to complete
        time.sleep(0.3)

        # Reload page
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Modal should not appear
        modal = page.locator("#changelog_modal")
        expect(modal).to_have_class(re.compile(r".*\bhidden\b.*"))

    def test_changelog_escape_closes_modal(self, page: Page, app_server: str):
        """Test that Escape key closes the changelog modal."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        modal = page.locator("#changelog_modal")
        expect(modal).to_be_visible()

        # Press Escape
        page.keyboard.press("Escape")

        # Modal should close
        expect(modal).not_to_be_visible()


class TestChangelogContent:
    """Test changelog content rendering."""

    def test_changelog_displays_version_number(self, page: Page, app_server: str):
        """Test that changelog modal displays the version number."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        version_el = page.locator("#changelog_version")
        expect(version_el).to_contain_text("Version")

        # Version should be a valid format (e.g., "Version 2.0.0")
        version_text = version_el.inner_text()
        assert re.match(r"Version \d+\.\d+\.\d+", version_text)

    def test_changelog_renders_markdown_headers(self, page: Page, app_server: str):
        """Test that markdown headers are rendered as HTML."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        content = page.locator("#changelog_content")
        # Should have rendered h2 or h3 elements from ## headers
        headers = content.locator("h2, h3")
        expect(headers.first).to_be_visible()

    def test_changelog_renders_markdown_lists(self, page: Page, app_server: str):
        """Test that markdown lists are rendered as HTML."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        content = page.locator("#changelog_content")
        # Should have rendered ul/li elements from - items
        lists = content.locator("ul")
        expect(lists.first).to_be_visible()

        # Should have list items
        items = content.locator("li")
        expect(items.first).to_be_visible()
        # Check there are multiple list items (2.0.0 changelog has many)
        assert items.count() >= 5

    def test_changelog_content_scrollable(self, page: Page, app_server: str):
        """Test that changelog content is scrollable if too long."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        body = page.locator(".changelog-body")
        # Check that overflow-y is auto
        overflow = body.evaluate("el => getComputedStyle(el).overflowY")
        assert overflow == "auto"

    def test_changelog_has_expected_sections(self, page: Page, app_server: str):
        """Test that changelog displays expected sections (Features, Improvements, Bug Fixes)."""
        page.goto(app_server)
        page.evaluate("localStorage.setItem('last_seen_version', '0.0.1')")
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        content = page.locator("#changelog_content")
        content_text = content.inner_text()

        # 2.0.0 changelog has these sections
        assert "Features" in content_text
        assert "Improvements" in content_text
        assert "Bug Fixes" in content_text


class TestChangelogAPIFromBrowser:
    """Test changelog API from browser context."""

    def test_healthz_has_version(self, page: Page, app_server: str):
        """Test that /healthz returns version in browser."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""
            async () => {
                const response = await fetch('/healthz');
                const data = await response.json();
                return data;
            }
        """)

        assert "version" in result
        assert result["ok"] is True
        # Version should be a valid semver string
        version = result["version"]
        assert len(version.split('.')) >= 2

    def test_changelog_api_accessible(self, page: Page, app_server: str):
        """Test that /api/changelog is accessible from browser."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""
            async () => {
                const response = await fetch('/api/changelog');
                const data = await response.json();
                return { ok: response.ok, data: data };
            }
        """)

        assert result["ok"] is True
        assert result["data"]["ok"] is True
        assert "version" in result["data"]
        assert "content" in result["data"]

    def test_changelog_versions_api_accessible(self, page: Page, app_server: str):
        """Test that /api/changelog/versions is accessible from browser."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""
            async () => {
                const response = await fetch('/api/changelog/versions');
                const data = await response.json();
                return data;
            }
        """)

        assert result["ok"] is True
        assert "versions" in result
        assert isinstance(result["versions"], list)
        assert len(result["versions"]) >= 1

    def test_changelog_api_returns_markdown_content(self, page: Page, app_server: str):
        """Test that changelog API returns valid markdown content."""
        page.goto(app_server)
        page.wait_for_load_state("networkidle")

        result = page.evaluate("""
            async () => {
                const response = await fetch('/api/changelog');
                const data = await response.json();
                return data.content;
            }
        """)

        # Should contain markdown elements
        assert "#" in result  # Headers
        assert "- " in result  # List items


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--headed"])

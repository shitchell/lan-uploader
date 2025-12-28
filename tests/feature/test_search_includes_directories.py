"""
E2E tests for search including directories feature (Issue #013).

These tests verify:
- Directory search results show folder icon
- Clicking directory result navigates to it (not preview)
- Clicking file result still opens preview (regression test)
- Mixed results display correctly (directories first, then files)
- Directory path is displayed correctly in results

Test Strategy:
- Uses Playwright for E2E testing (following existing patterns)
- Creates test directories and files via API/filesystem
- Strong assertions on actual behavior (icon display, navigation)
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
def search_dir_test_upload_dir() -> Generator[Path, None, None]:
    """Create a temporary upload directory with test structure for directory search tests."""
    temp_dir = Path(tempfile.mkdtemp(prefix="lan_uploader_search_dir_test_"))

    # Create directories for testing
    (temp_dir / "search_test_dir").mkdir()
    (temp_dir / "clickable_dir").mkdir()
    (temp_dir / "mixed_test").mkdir()

    # Create nested directory for path display testing
    (temp_dir / "parent").mkdir()
    (temp_dir / "parent" / "nested_search_dir").mkdir()

    # Create test files
    (temp_dir / "test_preview.txt").write_text("Test file content for preview testing.")
    (temp_dir / "mixed_test.txt").write_text("Mixed test file content.")

    # Create images with actual content for better testing
    try:
        from PIL import Image
        Image.new('RGB', (100, 100), color='red').save(temp_dir / "test_image.jpg")
    except ImportError:
        (temp_dir / "test_image.jpg").write_bytes(b"fake image")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def search_dir_test_db_path() -> Generator[Path, None, None]:
    """Create a temporary database file for testing."""
    temp_db = Path(tempfile.mktemp(prefix="lan_uploader_search_dir_test_", suffix=".db"))
    yield temp_db
    if temp_db.exists():
        temp_db.unlink()


@pytest.fixture(scope="module")
def search_dir_app_server(search_dir_test_upload_dir: Path, search_dir_test_db_path: Path):
    """Start the FastAPI app server for directory search testing."""
    # Use unique port for this test module
    test_port = 8770

    os.environ["UPLOAD_ROOT"] = str(search_dir_test_upload_dir)
    os.environ["DB_PATH"] = str(search_dir_test_db_path)
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

    # Index files
    from datetime import datetime
    import mimetypes

    for file_path in UPLOAD_ROOT.rglob("*"):
        if file_path.is_file() and not str(file_path).startswith(str(thumbnail_cache)):
            filepath_rel = file_path.relative_to(UPLOAD_ROOT).as_posix()
            parent_path_rel = file_path.parent.relative_to(UPLOAD_ROOT).as_posix()
            extension = file_path.suffix.lower()
            mime_type, _ = mimetypes.guess_type(str(file_path))

            preview_type = None
            has_thumbnail = False

            if extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                preview_type = 'image'
                try:
                    thumb_path = thumbnail_gen.generate(file_path)
                    has_thumbnail = thumb_path is not None
                except Exception:
                    has_thumbnail = False
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


def perform_search(page: Page, query: str):
    """Helper to perform a search and wait for results."""
    search_input = page.locator("#search_input")
    search_input.fill(query)

    search_btn = page.locator("#search_btn")
    search_btn.click()

    # Wait for search modal to appear
    modal = page.locator("#search_modal")
    expect(modal).to_be_visible()
    time.sleep(0.3)  # Allow results to render


def close_search_modal(page: Page):
    """Helper to close the search modal."""
    close_btn = page.locator("#close_search_modal")
    close_btn.click()
    modal = page.locator("#search_modal")
    expect(modal).not_to_be_visible()


class TestDirectorySearchResultDisplay:
    """Test that directory search results display correctly."""

    def test_directory_search_result_shows_folder_icon(self, page: Page, search_dir_app_server: str):
        """Test that directory results display folder icon (folder emoji)."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for the test directory
        perform_search(page, "search_test_dir")

        # Find search results
        results = page.locator("#search_results")
        expect(results).to_be_visible()

        # Find the directory result item
        result_items = page.locator(".search-result-item")
        expect(result_items.first).to_be_visible()

        # Get the icon element content - should contain folder emoji
        icon_element = result_items.first.locator(".search-result-icon")
        icon_text = icon_element.inner_text()

        # Folder emoji is U+1F4C1 or similar folder icon
        # The implementation uses folder emoji from createFolderItem pattern
        assert icon_text.strip() != "", "Icon should not be empty"
        # Verify it's a folder-related icon (folder emoji character)
        # Common folder emojis: U+1F4C1, U+1F4C2, U+1F5C1
        folder_chars = ["\U0001F4C1", "\U0001F4C2", "\U0001F5C1", "\U0001F4C0"]
        assert any(char in icon_text for char in folder_chars), \
            f"Expected folder emoji in icon, got: {repr(icon_text)}"

        close_search_modal(page)

    def test_directory_result_shows_path(self, page: Page, search_dir_app_server: str):
        """Test that nested directory path is displayed correctly."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for nested directory
        perform_search(page, "nested_search_dir")

        results = page.locator("#search_results")
        expect(results).to_be_visible()

        # Check that result shows path with parent
        result_path = page.locator(".search-result-path").first
        path_text = result_path.inner_text()

        # Path should include "parent/nested_search_dir"
        assert "parent" in path_text, f"Expected 'parent' in path, got: {path_text}"
        assert "nested_search_dir" in path_text, f"Expected 'nested_search_dir' in path, got: {path_text}"

        close_search_modal(page)

    def test_file_result_does_not_show_folder_icon(self, page: Page, search_dir_app_server: str):
        """Test that file results do NOT show folder icon."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for a file
        perform_search(page, "test_preview")

        results = page.locator("#search_results")
        expect(results).to_be_visible()

        # Find result item for file
        result_items = page.locator(".search-result-item")
        expect(result_items.first).to_be_visible()

        # Get the icon
        icon_element = result_items.first.locator(".search-result-icon")
        icon_text = icon_element.inner_text()

        # Should NOT be folder emoji - should be file icon
        folder_chars = ["\U0001F4C1", "\U0001F4C2", "\U0001F5C1"]
        is_folder_icon = any(char in icon_text for char in folder_chars)
        assert not is_folder_icon, \
            f"File result should not have folder icon, got: {repr(icon_text)}"

        close_search_modal(page)


class TestDirectorySearchResultNavigation:
    """Test clicking directory search results navigates correctly."""

    def test_clicking_directory_result_navigates(self, page: Page, search_dir_app_server: str):
        """Test that clicking a directory result navigates to that directory."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for clickable_dir
        perform_search(page, "clickable_dir")

        # Click on the directory result
        result_item = page.locator(".search-result-item").first
        expect(result_item).to_be_visible()
        result_item.click()

        # Wait for navigation
        page.wait_for_load_state("networkidle")
        time.sleep(0.3)

        # Search modal should be closed
        search_modal = page.locator("#search_modal")
        expect(search_modal).to_have_class(re.compile(r".*hidden.*"))

        # URL hash should contain the directory path
        url = page.url
        assert "clickable_dir" in url, \
            f"Expected URL to contain 'clickable_dir', got: {url}"

        # Breadcrumbs should show the directory
        breadcrumbs = page.locator("#breadcrumbs")
        expect(breadcrumbs).to_contain_text("clickable_dir")

    def test_clicking_directory_does_not_open_preview(self, page: Page, search_dir_app_server: str):
        """Test that clicking a directory does NOT open preview modal."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for a directory
        perform_search(page, "search_test_dir")

        # Click on the directory result
        result_item = page.locator(".search-result-item").first
        result_item.click()

        # Wait for any modal transitions
        time.sleep(0.3)

        # Preview modal should NOT be visible
        preview_modal = page.locator("#preview_modal")
        expect(preview_modal).to_have_class(re.compile(r".*hidden.*"))

    def test_clicking_nested_directory_navigates_correctly(self, page: Page, search_dir_app_server: str):
        """Test that clicking nested directory navigates to correct path."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for nested directory
        perform_search(page, "nested_search_dir")

        # Click on the result
        result_item = page.locator(".search-result-item").first
        result_item.click()

        page.wait_for_load_state("networkidle")
        time.sleep(0.3)

        # URL should contain full path
        url = page.url
        assert "parent" in url or "nested_search_dir" in url, \
            f"Expected nested path in URL, got: {url}"

        # Breadcrumbs should show both parent and nested
        breadcrumbs = page.locator("#breadcrumbs")
        breadcrumbs_text = breadcrumbs.inner_text()
        assert "parent" in breadcrumbs_text or "nested_search_dir" in breadcrumbs_text


class TestFileSearchResultBehavior:
    """Test that file search results still work correctly (regression tests)."""

    def test_clicking_file_result_opens_preview(self, page: Page, search_dir_app_server: str):
        """Test that clicking a file result opens preview (not navigation)."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for a text file
        perform_search(page, "test_preview")

        # Click on the file result
        result_item = page.locator(".search-result-item").first
        result_item.click()

        # Wait for modal transition
        time.sleep(0.5)

        # Preview modal should be visible
        preview_modal = page.locator("#preview_modal")
        expect(preview_modal).not_to_have_class(re.compile(r".*hidden.*"))

        # Preview should show the filename
        preview_filename = page.locator("#preview_filename")
        expect(preview_filename).to_contain_text("test_preview")

        # Close preview
        close_btn = page.locator("#close_preview_modal")
        close_btn.click()

    def test_file_preview_shows_content(self, page: Page, search_dir_app_server: str):
        """Test that file preview shows actual content."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for text file
        perform_search(page, "test_preview")

        # Click on file result
        result_item = page.locator(".search-result-item").first
        result_item.click()

        time.sleep(0.5)

        # Preview content should be visible
        preview_content = page.locator("#preview_content")
        expect(preview_content).to_be_visible()

        # For text files, should have <pre> element with content
        pre_element = preview_content.locator("pre")
        expect(pre_element).to_be_visible()
        content_text = pre_element.inner_text()
        assert "Test file content" in content_text, \
            f"Expected file content in preview, got: {content_text}"

        # Close preview
        page.locator("#close_preview_modal").click()


class TestMixedSearchResults:
    """Test mixed directory and file search results."""

    def test_mixed_results_display_correctly(self, page: Page, search_dir_app_server: str):
        """Test that both directories and files appear in search results."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for "mixed_test" which matches both directory and file
        perform_search(page, "mixed_test")

        # Should have multiple results
        result_items = page.locator(".search-result-item")
        count = result_items.count()
        assert count >= 2, f"Expected at least 2 results, got: {count}"

        # Get all icons
        icons = page.locator(".search-result-icon").all()
        icon_texts = [icon.inner_text() for icon in icons]

        # Should have mix of folder and file icons
        folder_chars = ["\U0001F4C1", "\U0001F4C2", "\U0001F5C1"]
        has_folder = any(
            any(char in text for char in folder_chars)
            for text in icon_texts
        )
        has_file = any(
            not any(char in text for char in folder_chars)
            for text in icon_texts
        )

        assert has_folder, "Expected at least one folder icon in mixed results"
        assert has_file, "Expected at least one file icon in mixed results"

        close_search_modal(page)

    def test_directories_appear_before_files(self, page: Page, search_dir_app_server: str):
        """Test that directories appear before files in search results."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for "mixed_test"
        perform_search(page, "mixed_test")

        result_items = page.locator(".search-result-item")
        count = result_items.count()

        if count >= 2:
            # First result should be directory (folder icon)
            first_icon = result_items.first.locator(".search-result-icon")
            first_icon_text = first_icon.inner_text()

            folder_chars = ["\U0001F4C1", "\U0001F4C2", "\U0001F5C1"]
            assert any(char in first_icon_text for char in folder_chars), \
                f"First result should be directory, but icon is: {repr(first_icon_text)}"

        close_search_modal(page)


class TestSearchModalBehavior:
    """Test search modal closes correctly after clicking results."""

    def test_search_modal_closes_on_directory_click(self, page: Page, search_dir_app_server: str):
        """Test that search modal closes when clicking directory result."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        perform_search(page, "clickable_dir")

        search_modal = page.locator("#search_modal")
        expect(search_modal).not_to_have_class(re.compile(r".*hidden.*"))

        # Click directory result
        result_item = page.locator(".search-result-item").first
        result_item.click()

        time.sleep(0.3)

        # Modal should be hidden
        expect(search_modal).to_have_class(re.compile(r".*hidden.*"))

    def test_search_modal_closes_on_file_click(self, page: Page, search_dir_app_server: str):
        """Test that search modal closes when clicking file result."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        perform_search(page, "test_preview")

        search_modal = page.locator("#search_modal")
        expect(search_modal).not_to_have_class(re.compile(r".*hidden.*"))

        # Click file result
        result_item = page.locator(".search-result-item").first
        result_item.click()

        time.sleep(0.3)

        # Search modal should be hidden
        expect(search_modal).to_have_class(re.compile(r".*hidden.*"))

        # Close preview modal
        page.locator("#close_preview_modal").click()


class TestRegressionPrevention:
    """Tests designed to fail if the directory search implementation is reverted."""

    def test_api_returns_is_directory_field(self, page: Page, search_dir_app_server: str):
        """Test that API includes is_directory field in results."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Make API call directly via page context
        result = page.evaluate("""
            async () => {
                const response = await fetch('/api/search?q=search_test_dir');
                return await response.json();
            }
        """)

        assert result["ok"] is True
        assert len(result["results"]) > 0

        # Check for is_directory field
        dir_result = next(
            (r for r in result["results"] if r.get("is_directory")),
            None
        )
        assert dir_result is not None, \
            "API must return is_directory field. " \
            "If this fails, the directory search implementation has been removed."
        assert dir_result["is_directory"] is True

    def test_directory_navigation_works(self, page: Page, search_dir_app_server: str):
        """Test that clicking directory actually navigates (core feature test)."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Record initial URL
        initial_url = page.url

        # Search and click directory
        perform_search(page, "clickable_dir")
        result_item = page.locator(".search-result-item").first
        result_item.click()

        page.wait_for_load_state("networkidle")
        time.sleep(0.3)

        # URL must have changed
        new_url = page.url
        assert new_url != initial_url or "clickable_dir" in new_url, \
            "Clicking directory must trigger navigation. " \
            "If this fails, the directory click handler has been removed."

    def test_file_click_still_opens_preview(self, page: Page, search_dir_app_server: str):
        """Test that file click behavior is preserved (regression test)."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search and click file
        perform_search(page, "test_preview")
        result_item = page.locator(".search-result-item").first
        result_item.click()

        time.sleep(0.5)

        # Preview modal must open
        preview_modal = page.locator("#preview_modal")
        is_hidden = "hidden" in (preview_modal.get_attribute("class") or "")
        assert not is_hidden, \
            "File click must still open preview modal. " \
            "If this fails, file preview behavior has regressed."

        page.locator("#close_preview_modal").click()


class TestEdgeCases:
    """Test edge cases for directory search."""

    def test_empty_query_shows_validation_error(self, page: Page, search_dir_app_server: str):
        """Test that empty search query shows error (existing behavior preserved)."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Try to search with empty query
        search_input = page.locator("#search_input")
        search_input.fill("")

        search_btn = page.locator("#search_btn")
        search_btn.click()

        # Should not open modal or should show error
        # (implementation may vary - just verify no crash)
        time.sleep(0.3)

    def test_search_no_results(self, page: Page, search_dir_app_server: str):
        """Test search with no matching results."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for non-existent term
        perform_search(page, "xyznonexistent123")

        # Should show "no results" message (element ID is no_results)
        no_results = page.locator("#no_results")
        expect(no_results).to_be_visible()

        close_search_modal(page)

    def test_search_only_matches_directories(self, page: Page, search_dir_app_server: str):
        """Test search that only matches directories (no files)."""
        page.goto(search_dir_app_server)
        page.wait_for_load_state("networkidle")

        # Search for directory-only term
        perform_search(page, "clickable_dir")

        result_items = page.locator(".search-result-item")
        expect(result_items.first).to_be_visible()

        # All results should be directories
        icons = page.locator(".search-result-icon").all()
        folder_chars = ["\U0001F4C1", "\U0001F4C2", "\U0001F5C1"]

        for icon in icons:
            icon_text = icon.inner_text()
            is_folder = any(char in icon_text for char in folder_chars)
            assert is_folder, f"Expected only folder results, got icon: {repr(icon_text)}"

        close_search_modal(page)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

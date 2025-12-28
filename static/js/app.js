// Main entry point - wires together all modules
import { state } from './state.js';
import { showStatus } from './utils.js';
import { createDirectory, batchDelete } from './api.js';
import { setContextMenuHandlers, hideContextMenu, setEnterSelectModeCallback } from './context-menu.js';
import {
  navigateTo,
  loadDirectory,
  toggleViewMode,
  initBrowserView,
  setNavigationHandlers,
  clearSelection,
  enterSelectMode,
  exitSelectMode,
  clearAllSelections,
} from './navigation.js';
import {
  openUploadModal,
  closeUploadModal,
  performUpload,
  clearFiles,
  setupUploadHandlers,
  setupBrowserDragDrop,
  setUploadCompleteHandler,
} from './upload.js';
import {
  openPreview,
  closePreview,
  downloadCurrentFile,
  deleteCurrentFile,
  downloadFileDirectly,
  downloadDirectoryDirectly,
  deleteFileDirectly,
  setFileDeletedHandler,
} from './preview.js';
import {
  performSearch,
  closeSearchModal,
  expandSearch,
  collapseSearch,
  isMobileSearchActive,
  setSearchResultHandler,
} from './search.js';

// ===== Wire up cross-module handlers =====

// Check if any modal is currently visible
function isAnyModalOpen() {
  const previewModal = document.getElementById('preview_modal');
  const uploadModal = document.getElementById('upload_modal');
  const searchModal = document.getElementById('search_modal');
  const newFolderModal = document.getElementById('new_folder_modal');

  return (
    !previewModal.classList.contains('hidden') ||
    !uploadModal.classList.contains('hidden') ||
    !searchModal.classList.contains('hidden') ||
    !newFolderModal.classList.contains('hidden')
  );
}

// Navigation needs to know how to open preview, new folder, and handle file actions
setNavigationHandlers({
  openPreview,
  openNewFolderModal,
  downloadFile: (path) => downloadFileDirectly(path),
  downloadDirectory: (path) => downloadDirectoryDirectly(path),
  deleteFile: (path, name) => deleteFileDirectly(path, name, () => loadDirectory(state.currentPath)),
});

// Context menu needs download/delete handlers
setContextMenuHandlers({
  download: (item) => {
    if (item.isDirectory) {
      downloadDirectoryDirectly(item.path);
    } else {
      downloadFileDirectly(item.path);
    }
  },
  delete: (item) => {
    deleteFileDirectly(item.path, item.name, () => loadDirectory(state.currentPath));
  },
});

// Context menu long-press should enter select mode
setEnterSelectModeCallback(() => enterSelectMode());

// Preview needs to refresh after delete
setFileDeletedHandler(() => loadDirectory(state.currentPath));

// Upload needs to refresh after complete
setUploadCompleteHandler(() => loadDirectory(state.currentPath));

// Search needs to navigate and open preview on result click
setSearchResultHandler((file) => {
  navigateTo(file.parent_path).then(() => openPreview(file));
});

// ===== DOM Elements =====
const viewToggleBtn = document.getElementById('view_toggle_btn');
const viewIcon = document.getElementById('view_icon');
const uploadBtn = document.getElementById('upload_btn');
const uploadHereBtn = document.getElementById('upload_here_btn');
const closeUploadBtn = document.getElementById('close_upload_modal');
const cancelUploadBtn = document.getElementById('cancel_upload');
const startUploadBtn = document.getElementById('start_upload');
const clearFilesBtn = document.getElementById('clear_files');

const closePreviewBtn = document.getElementById('close_preview_modal');
const downloadFileBtn = document.getElementById('download_file');
const deleteFileBtn = document.getElementById('delete_file');

const searchBtn = document.getElementById('search_btn');
const searchInput = document.getElementById('search_input');
const searchCancelBtn = document.getElementById('search_cancel');
const closeSearchBtn = document.getElementById('close_search_modal');

const selectModeBtn = document.getElementById('select_mode_btn');
const cancelSelectionBtn = document.getElementById('cancel_selection');
const downloadSelectedBtn = document.getElementById('download_selected');
const deleteSelectedBtn = document.getElementById('delete_selected');
const kebabMenuBtn = document.getElementById('kebab_menu_btn');
const kebabMenu = document.getElementById('kebab_menu');

const newFolderModal = document.getElementById('new_folder_modal');
const closeNewFolderBtn = document.getElementById('close_new_folder_modal');
const cancelNewFolderBtn = document.getElementById('cancel_new_folder');
const createNewFolderBtn = document.getElementById('create_new_folder');
const newFolderNameInput = document.getElementById('new_folder_name');
const newFolderParentPath = document.getElementById('new_folder_parent_path');

// ===== New Folder Modal =====
function openNewFolderModal() {
  newFolderParentPath.textContent = '/' + state.currentPath;
  newFolderNameInput.value = '';
  newFolderModal.classList.remove('hidden');
  setTimeout(() => newFolderNameInput.focus(), 100);
}

function closeNewFolderModal() {
  newFolderModal.classList.add('hidden');
  newFolderNameInput.value = '';
}

async function performCreateFolder() {
  const folderName = newFolderNameInput.value.trim();

  if (!folderName) {
    showStatus('Please enter a folder name', 'error', 2000);
    return;
  }

  try {
    const data = await createDirectory(state.currentPath, folderName);
    showStatus(data.message, 'success');
    closeNewFolderModal();
    loadDirectory(state.currentPath);
  } catch (error) {
    showStatus('Failed to create folder: ' + error.message, 'error');
  }
}

// ===== Kebab Overflow Menu =====
const overflowableButtons = [
  { btn: selectModeBtn, label: 'Select', icon: '☑', width: 50 },
  { btn: viewToggleBtn, label: 'Toggle View', icon: '⊞', width: 50 },
  { btn: uploadBtn, label: 'Upload', icon: '⬆', width: 90 },
];

function updateKebabOverflow() {
  const headerActions = document.querySelector('.header-actions');
  if (!headerActions) return;

  if (headerActions.classList.contains('mobile-search-active')) {
    kebabMenuBtn.style.display = 'none';
    return;
  }

  const viewportWidth = window.innerWidth;
  const isMobile = viewportWidth <= 600;

  let buttonsToOverflow = 0;
  if (isMobile) {
    buttonsToOverflow = 2;
  } else if (viewportWidth <= 480) {
    buttonsToOverflow = 3;
  } else if (viewportWidth <= 768) {
    buttonsToOverflow = 1;
  }

  kebabMenu.innerHTML = '';
  state.currentlyOverflowed.clear();

  overflowableButtons.forEach(item => {
    item.btn.classList.remove('hidden');
  });

  if (buttonsToOverflow === 0) {
    kebabMenuBtn.style.display = 'none';
    return;
  }

  for (let i = 0; i < buttonsToOverflow && i < overflowableButtons.length; i++) {
    const item = overflowableButtons[i];
    item.btn.classList.add('hidden');
    state.currentlyOverflowed.add(item.btn.id);

    const menuItem = document.createElement('button');
    menuItem.className = 'menu-item';
    menuItem.dataset.for = item.btn.id;
    menuItem.innerHTML = `<span>${item.icon}</span> ${item.label}`;
    menuItem.addEventListener('click', () => {
      kebabMenu.classList.add('hidden');
      item.btn.click();
    });
    kebabMenu.appendChild(menuItem);
  }

  kebabMenuBtn.style.display = 'flex';
}

// ===== Event Listeners =====

// View toggle
viewToggleBtn.addEventListener('click', () => {
  viewIcon.textContent = toggleViewMode();
});

// Upload
uploadBtn.addEventListener('click', openUploadModal);
uploadHereBtn.addEventListener('click', openUploadModal);
closeUploadBtn.addEventListener('click', closeUploadModal);
cancelUploadBtn.addEventListener('click', closeUploadModal);
startUploadBtn.addEventListener('click', performUpload);
clearFilesBtn.addEventListener('click', clearFiles);

// Preview
closePreviewBtn.addEventListener('click', closePreview);
downloadFileBtn.addEventListener('click', downloadCurrentFile);
deleteFileBtn.addEventListener('click', deleteCurrentFile);

// Search
searchBtn.addEventListener('click', (e) => {
  if (window.innerWidth <= 600 && !isMobileSearchActive()) {
    e.preventDefault();
    expandSearch();
  } else {
    performSearch();
  }
});
searchInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') performSearch();
});
searchCancelBtn.addEventListener('click', collapseSearch);
closeSearchBtn.addEventListener('click', closeSearchModal);

// Kebab menu
kebabMenuBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  kebabMenu.classList.toggle('hidden');
});
document.addEventListener('click', (e) => {
  kebabMenu.classList.add('hidden');
  // Clear selection if click is not on a file-item or folder-item
  if (!e.target.closest('.file-item') && !e.target.closest('.folder-item')) {
    // Only clear selection if no modal is open AND click is not inside a modal
    // (modal close buttons hide the modal before click bubbles here)
    if (!isAnyModalOpen() && !e.target.closest('.modal')) {
      clearSelection();
    }
  }
});

// Select mode
selectModeBtn.addEventListener('click', () => {
  if (state.selectMode) {
    exitSelectMode();
  } else {
    enterSelectMode();
  }
});

cancelSelectionBtn.addEventListener('click', () => {
  exitSelectMode();
});

downloadSelectedBtn.addEventListener('click', () => {
  // For now, download each selected item individually
  // TODO: Could be enhanced to create a zip of all selected files
  state.selectedItems.forEach((item) => {
    if (item.isDirectory) {
      downloadDirectoryDirectly(item.path);
    } else {
      downloadFileDirectly(item.path);
    }
  });
  showStatus(`Downloading ${state.selectedItems.size} item(s)`, 'success', 2000);
});

deleteSelectedBtn.addEventListener('click', async () => {
  const count = state.selectedItems.size;
  if (count === 0) {
    showStatus('No items selected', 'error', 2000);
    return;
  }

  const confirmed = confirm(`Are you sure you want to delete ${count} item(s)?`);
  if (!confirmed) return;

  try {
    const paths = Array.from(state.selectedItems.keys());
    const result = await batchDelete(paths);

    if (result.deleted > 0) {
      showStatus(`Deleted ${result.deleted} item(s)`, 'success');
    }

    if (result.errors && result.errors.length > 0) {
      console.error('Batch delete errors:', result.errors);
      showStatus(`${result.errors.length} item(s) failed to delete`, 'error');
    }

    // Exit select mode and refresh
    exitSelectMode();
    loadDirectory(state.currentPath);
  } catch (error) {
    showStatus('Failed to delete items: ' + error.message, 'error');
  }
});

// New folder
closeNewFolderBtn.addEventListener('click', closeNewFolderModal);
cancelNewFolderBtn.addEventListener('click', closeNewFolderModal);
createNewFolderBtn.addEventListener('click', performCreateFolder);
newFolderNameInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') performCreateFolder();
});

// Escape to close modals, exit select mode, and clear selection
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // Exit select mode first if active
    if (state.selectMode) {
      exitSelectMode();
      return;
    }

    // Only clear selection if no modal is currently open
    if (!isAnyModalOpen()) {
      clearSelection();
    }
    hideContextMenu();
    const uploadModal = document.getElementById('upload_modal');
    const previewModal = document.getElementById('preview_modal');
    const searchModal = document.getElementById('search_modal');

    if (!uploadModal.classList.contains('hidden')) closeUploadModal();
    if (!previewModal.classList.contains('hidden')) closePreview();
    if (!searchModal.classList.contains('hidden')) closeSearchModal();
    if (!newFolderModal.classList.contains('hidden')) closeNewFolderModal();
  }
});

// Resize handler for kebab overflow
window.addEventListener('resize', updateKebabOverflow);

// Hash change for browser navigation
window.addEventListener('hashchange', () => {
  const hashPath = window.location.hash.slice(1).split('/').map(decodeURIComponent).join('/');
  if (hashPath !== state.currentPath) {
    navigateTo(hashPath, false);
  }
});

// ===== Initialize =====

// Set initial view mode
viewIcon.textContent = initBrowserView();

// Setup upload handlers
setupUploadHandlers();
setupBrowserDragDrop();

// Kebab overflow
setTimeout(updateKebabOverflow, 100);

// Infinite scroll observer
const loadSentinel = document.getElementById('load_sentinel');
if (loadSentinel) {
  state.infiniteScrollObserver = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && state.hasMoreItems && !state.isLoadingMore) {
      loadDirectory(state.currentPath, true);
    }
  }, { rootMargin: '200px' });
  state.infiniteScrollObserver.observe(loadSentinel);
}

// Load initial directory from URL hash
const initialPath = window.location.hash.slice(1).split('/').map(decodeURIComponent).join('/');
navigateTo(initialPath, false);

// Navigation, breadcrumbs, and file grid rendering
import { state } from './state.js';
import { escapeHtml, getFileIcon, formatFileSize, showStatus } from './utils.js';
import { fetchDirectory, getFileUrl, getThumbnailUrl, getDirectoryDownloadUrl } from './api.js';
import { attachContextMenuEvents, attachSelectModeContextMenuEvents } from './context-menu.js';

// DOM elements (cached on first use)
let elements = null;

function getElements() {
  if (!elements) {
    elements = {
      breadcrumbs: document.getElementById('breadcrumbs'),
      fileGrid: document.getElementById('file_grid'),
      emptyState: document.getElementById('empty_state'),
      browserContent: document.getElementById('browser_content'),
    };
  }
  return elements;
}

// Action handlers - set by app.js
let actionHandlers = {
  openPreview: null,
  openNewFolderModal: null,
  downloadFile: null,
  downloadDirectory: null,
  deleteFile: null,
};

export function setNavigationHandlers(handlers) {
  actionHandlers = { ...actionHandlers, ...handlers };
}

// Selection functions
export function selectItem(element) {
  // Clear previous selection
  if (state.selectedElement) {
    state.selectedElement.classList.remove('selected');
  }
  // Set new selection
  state.selectedElement = element;
  if (element) {
    element.classList.add('selected');
  }
}

export function clearSelection() {
  if (state.selectedElement) {
    state.selectedElement.classList.remove('selected');
    state.selectedElement = null;
  }
}

// Multi-selection functions for batch operations
export function toggleItemSelection(path, itemData, element) {
  if (state.selectedItems.has(path)) {
    state.selectedItems.delete(path);
    element.classList.remove('batch-selected');
    const checkbox = element.querySelector('.item-checkbox');
    if (checkbox) checkbox.checked = false;
  } else {
    state.selectedItems.set(path, { ...itemData, element });
    element.classList.add('batch-selected');
    const checkbox = element.querySelector('.item-checkbox');
    if (checkbox) checkbox.checked = true;
  }
  state.lastSelectedPath = path;
  updateSelectionCount();
}

export function selectItemRange(fromPath, toPath) {
  // Get all items in the file grid
  const { fileGrid } = getElements();
  const items = Array.from(fileGrid.querySelectorAll('.file-item, .folder-item'));

  // Find indices of from and to
  let fromIndex = -1;
  let toIndex = -1;

  items.forEach((item, index) => {
    const itemPath = item.dataset.path;
    if (itemPath === fromPath) fromIndex = index;
    if (itemPath === toPath) toIndex = index;
  });

  if (fromIndex === -1 || toIndex === -1) return;

  // Normalize range
  const start = Math.min(fromIndex, toIndex);
  const end = Math.max(fromIndex, toIndex);

  // Select all items in range
  for (let i = start; i <= end; i++) {
    const item = items[i];
    const itemPath = item.dataset.path;
    const isDirectory = item.classList.contains('folder-item');
    const itemName = item.dataset.name;

    if (!state.selectedItems.has(itemPath)) {
      state.selectedItems.set(itemPath, {
        path: itemPath,
        name: itemName,
        isDirectory,
        element: item,
      });
      item.classList.add('batch-selected');
      const checkbox = item.querySelector('.item-checkbox');
      if (checkbox) checkbox.checked = true;
    }
  }

  updateSelectionCount();
}

export function clearAllSelections() {
  state.selectedItems.forEach(({ element }) => {
    if (element) {
      element.classList.remove('batch-selected');
      const checkbox = element.querySelector('.item-checkbox');
      if (checkbox) checkbox.checked = false;
    }
  });
  state.selectedItems.clear();
  state.lastSelectedPath = null;
  updateSelectionCount();
}

export function updateSelectionCount() {
  const countEl = document.getElementById('selection_count');
  if (countEl) {
    const count = state.selectedItems.size;
    countEl.textContent = `${count} selected`;
  }
}

export function enterSelectMode() {
  state.selectMode = true;
  document.body.classList.add('select-mode');

  // Show selection bar
  const selectionBar = document.getElementById('selection_bar');
  if (selectionBar) selectionBar.classList.remove('hidden');

  // Add checkboxes to existing items
  const { fileGrid } = getElements();
  const items = fileGrid.querySelectorAll('.file-item, .folder-item');
  items.forEach(item => {
    addCheckboxToItem(item);
  });

  updateSelectionCount();
}

export function exitSelectMode() {
  state.selectMode = false;
  document.body.classList.remove('select-mode');

  // Hide selection bar
  const selectionBar = document.getElementById('selection_bar');
  if (selectionBar) selectionBar.classList.add('hidden');

  // Clear all selections
  clearAllSelections();

  // Remove checkboxes from items
  const { fileGrid } = getElements();
  const checkboxes = fileGrid.querySelectorAll('.item-checkbox');
  checkboxes.forEach(cb => cb.remove());
}

function addCheckboxToItem(item) {
  // Don't add if already has checkbox
  if (item.querySelector('.item-checkbox')) return;

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'item-checkbox';
  checkbox.checked = state.selectedItems.has(item.dataset.path);

  // Prevent checkbox click from bubbling to item click handler
  checkbox.addEventListener('click', (e) => {
    e.stopPropagation();
    const path = item.dataset.path;
    const isDirectory = item.classList.contains('folder-item');
    const name = item.dataset.name;

    toggleItemSelection(path, { path, name, isDirectory }, item);
  });

  // Insert at the beginning of the item
  item.insertBefore(checkbox, item.firstChild);
}

export async function navigateTo(path, updateHash = true) {
  state.currentPath = path || '';

  if (updateHash) {
    const newHash = state.currentPath
      ? state.currentPath.split('/').map(encodeURIComponent).join('/')
      : '';
    if (window.location.hash.slice(1) !== newHash) {
      window.location.hash = newHash;
    }
  }

  // Reset pagination
  state.currentOffset = 0;
  state.hasMoreItems = false;

  await loadDirectory(state.currentPath, false);
}

export async function loadDirectory(path, append = false) {
  if (state.isLoadingMore) return;

  try {
    state.isLoadingMore = true;

    const data = await fetchDirectory(
      path || '',
      state.PAGE_SIZE,
      append ? state.currentOffset : 0
    );

    const itemsReturned = data.directories.length + data.files.length;
    state.currentOffset = append ? state.currentOffset + itemsReturned : itemsReturned;
    state.hasMoreItems = data.has_more;

    if (!append) {
      renderBreadcrumbs(data.breadcrumbs);
    }

    renderFileGrid(data.directories, data.files, append);
  } catch (error) {
    showStatus('Failed to load directory: ' + error.message, 'error');
  } finally {
    state.isLoadingMore = false;
  }
}

function renderBreadcrumbs(crumbs) {
  const { breadcrumbs } = getElements();
  breadcrumbs.innerHTML = '';

  crumbs.forEach((crumb, index) => {
    const link = document.createElement('a');
    link.href = '#';
    link.textContent = crumb.label;
    link.dataset.path = crumb.path;
    link.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo(crumb.path);
    });
    breadcrumbs.appendChild(link);

    if (index < crumbs.length - 1) {
      const separator = document.createElement('span');
      separator.className = 'separator';
      separator.textContent = '›';
      breadcrumbs.appendChild(separator);
    }
  });

  // Add separator and "New Folder" button
  const separator = document.createElement('span');
  separator.className = 'separator';
  separator.textContent = '›';
  breadcrumbs.appendChild(separator);

  const newFolderButton = document.createElement('button');
  newFolderButton.id = 'new_folder_btn';
  newFolderButton.className = 'new-folder-btn primary-btn';
  newFolderButton.title = 'Create new folder';
  newFolderButton.textContent = '+ New Folder';
  newFolderButton.addEventListener('click', () => {
    if (actionHandlers.openNewFolderModal) {
      actionHandlers.openNewFolderModal();
    }
  });
  breadcrumbs.appendChild(newFolderButton);
}

function renderFileGrid(directories, files, append = false) {
  const { fileGrid, emptyState } = getElements();

  if (!append) {
    fileGrid.innerHTML = '';
  }

  const hasContent = directories.length > 0 || files.length > 0;
  const hadContentBefore = fileGrid.children.length > 0;

  if (!hasContent && !hadContentBefore) {
    emptyState.classList.remove('hidden');
    return;
  } else {
    emptyState.classList.add('hidden');
  }

  directories.forEach(dir => {
    fileGrid.appendChild(createFolderItem(dir));
  });

  files.forEach(file => {
    fileGrid.appendChild(createFileItem(file));
  });
}

function createFolderItem(dir) {
  const item = document.createElement('div');
  item.className = 'folder-item card';
  item.dataset.path = dir.path;
  item.dataset.name = dir.name;

  item.addEventListener('click', (e) => {
    if (state.selectMode) {
      e.preventDefault();
      e.stopPropagation();

      // Handle Shift+click for range selection
      if (e.shiftKey && state.lastSelectedPath) {
        selectItemRange(state.lastSelectedPath, dir.path);
      } else {
        toggleItemSelection(dir.path, { path: dir.path, name: dir.name, isDirectory: true }, item);
      }
      return;
    }

    navigateTo(dir.path);
  });

  if (state.currentViewMode === 'list') {
    item.innerHTML = `
      <div class="item-icon">📁</div>
      <div class="item-info">
        <div class="item-name truncate">${escapeHtml(dir.name)}</div>
        <div class="item-details text-sm">${dir.file_count} file(s)</div>
      </div>
      <div class="item-actions flex-row"></div>
    `;

    // Add action buttons programmatically
    const actions = item.querySelector('.item-actions');
    actions.appendChild(createActionButton('Download', () => {
      if (actionHandlers.downloadDirectory) {
        actionHandlers.downloadDirectory(dir.path, dir.name);
      }
    }));
    actions.appendChild(createActionButton('Delete', () => {
      if (actionHandlers.deleteFile) {
        actionHandlers.deleteFile(dir.path, dir.name);
      }
    }));
  } else {
    item.innerHTML = `
      <div class="item-icon">📁</div>
      <div class="item-name truncate" title="${escapeHtml(dir.name)}">${escapeHtml(dir.name)}</div>
      <div class="item-details text-sm">${dir.file_count} file(s)</div>
    `;
  }

  attachSelectModeContextMenuEvents(item, {
    path: dir.path,
    name: dir.name,
    isDirectory: true,
  });

  // Add checkbox if already in select mode
  if (state.selectMode) {
    addCheckboxToItem(item);
  }

  return item;
}

function createFileItem(file) {
  const item = document.createElement('div');
  item.className = 'file-item card';
  item.dataset.path = file.path;
  item.dataset.name = file.name;

  item.addEventListener('click', (e) => {
    if (state.selectMode) {
      e.preventDefault();
      e.stopPropagation();

      // Handle Shift+click for range selection
      if (e.shiftKey && state.lastSelectedPath) {
        selectItemRange(state.lastSelectedPath, file.path);
      } else {
        toggleItemSelection(file.path, { path: file.path, name: file.name, isDirectory: false }, item);
      }
      return;
    }

    selectItem(item);
    if (actionHandlers.openPreview) {
      actionHandlers.openPreview(file);
    }
  });

  const icon = getFileIcon(file.preview_type);
  const size = formatFileSize(file.size);

  if (state.currentViewMode === 'list') {
    item.innerHTML = `
      <div class="item-icon">${icon}</div>
      <div class="item-info">
        <div class="item-name truncate">${escapeHtml(file.name)}</div>
        <div class="item-details text-sm">${size} • ${file.extension || 'unknown'}</div>
      </div>
      <div class="item-actions flex-row"></div>
    `;

    const actions = item.querySelector('.item-actions');
    actions.appendChild(createActionButton('Download', () => {
      if (actionHandlers.downloadFile) {
        actionHandlers.downloadFile(file.path, file.name);
      }
    }));
    actions.appendChild(createActionButton('Delete', () => {
      if (actionHandlers.deleteFile) {
        actionHandlers.deleteFile(file.path, file.name);
      }
    }));
  } else {
    if (file.has_thumbnail && file.preview_type === 'image') {
      item.innerHTML = `
        <img src="${getThumbnailUrl(file.path)}" class="item-thumbnail" alt="${escapeHtml(file.name)}">
        <div class="item-name truncate" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
        <div class="item-details text-sm">${size}</div>
      `;
    } else {
      item.innerHTML = `
        <div class="item-icon">${icon}</div>
        <div class="item-name truncate" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
        <div class="item-details text-sm">${size}</div>
      `;
    }
  }

  attachSelectModeContextMenuEvents(item, {
    path: file.path,
    name: file.name,
    isDirectory: false,
    preview_type: file.preview_type,
  });

  // Add checkbox if already in select mode
  if (state.selectMode) {
    addCheckboxToItem(item);
  }

  return item;
}

function createActionButton(label, onClick) {
  const btn = document.createElement('button');
  btn.className = 'action-btn btn-sm secondary-btn';
  btn.textContent = label;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    onClick();
  });
  return btn;
}

export function toggleViewMode() {
  state.currentViewMode = state.currentViewMode === 'list' ? 'gallery' : 'list';
  localStorage.setItem('view_mode', state.currentViewMode);

  const { browserContent } = getElements();
  browserContent.className = `browser-content ${state.currentViewMode}-view`;

  // Return icon for UI update
  const newIcon = state.currentViewMode === 'list' ? '⊞' : '☰';

  // Re-render current directory
  loadDirectory(state.currentPath);

  return newIcon;
}

export function initBrowserView() {
  const { browserContent } = getElements();
  browserContent.className = `browser-content ${state.currentViewMode}-view`;
  return state.currentViewMode === 'list' ? '⊞' : '☰';
}

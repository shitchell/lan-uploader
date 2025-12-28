// Navigation, breadcrumbs, and file grid rendering
import { state } from './state.js';
import { escapeHtml, getFileIcon, formatFileSize, showStatus } from './utils.js';
import { fetchDirectory, getFileUrl, getThumbnailUrl, getDirectoryDownloadUrl } from './api.js';
import { attachContextMenuEvents } from './context-menu.js';

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
  item.addEventListener('click', () => navigateTo(dir.path));

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

  attachContextMenuEvents(item, {
    path: dir.path,
    name: dir.name,
    isDirectory: true,
  });

  return item;
}

function createFileItem(file) {
  const item = document.createElement('div');
  item.className = 'file-item card';
  item.addEventListener('click', () => {
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

  attachContextMenuEvents(item, {
    path: file.path,
    name: file.name,
    isDirectory: false,
    preview_type: file.preview_type,
  });

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

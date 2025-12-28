// File preview modal
import { state } from './state.js';
import { escapeHtml, formatFileSize, showStatus } from './utils.js';
import { fetchTextPreview, deleteFile, deleteFileForce, getFileUrl } from './api.js';
import { removeItemFromGrid } from './navigation.js';

// DOM elements (cached)
let elements = null;

function getElements() {
  if (!elements) {
    elements = {
      modal: document.getElementById('preview_modal'),
      filename: document.getElementById('preview_filename'),
      content: document.getElementById('preview_content'),
      navPrev: document.getElementById('preview_nav_prev'),
      navNext: document.getElementById('preview_nav_next'),
      navIndex: document.getElementById('preview_nav_index'),
    };
  }
  return elements;
}

// Callback for after delete
let onFileDeleted = null;

export function setFileDeletedHandler(handler) {
  onFileDeleted = handler;
}

export async function openPreview(file) {
  const { modal, filename, content } = getElements();

  state.currentPreviewFile = file;
  filename.textContent = file.name;
  content.innerHTML = '<p class="muted">Loading preview...</p>';
  modal.classList.remove('hidden');

  try {
    if (file.preview_type === 'image') {
      content.innerHTML = `<img src="${getFileUrl(file.path)}" alt="${escapeHtml(file.name)}">`;
    } else if (file.preview_type === 'video') {
      content.innerHTML = `<video controls src="${getFileUrl(file.path)}"></video>`;
    } else if (file.preview_type === 'audio') {
      content.innerHTML = `<audio controls src="${getFileUrl(file.path)}"></audio>`;
    } else if (file.preview_type === 'text' || file.preview_type === 'code') {
      const data = await fetchTextPreview(file.path);
      const truncatedNote = data.truncated
        ? `<p class="muted">(Showing first 1000 chars of ${formatFileSize(data.size)})</p>`
        : '';
      content.innerHTML = `<pre>${escapeHtml(data.content)}</pre>${truncatedNote}`;
    } else {
      content.innerHTML = `
        <div class="muted">
          <p>Preview not available for this file type</p>
          <p>File: ${escapeHtml(file.name)}</p>
          <p>Size: ${formatFileSize(file.size)}</p>
          <p>Type: ${file.mime_type || 'unknown'}</p>
        </div>
      `;
    }
  } catch (error) {
    content.innerHTML = `<p class="muted">Failed to load preview: ${error.message}</p>`;
  }

  // Update navigation UI after loading content
  updateNavigationUI();
}

export function closePreview() {
  const { modal, content } = getElements();
  modal.classList.add('hidden');
  state.currentPreviewFile = null;
  content.innerHTML = '';
}

/**
 * Update preview content with smooth fade transition (used for navigation)
 * Unlike openPreview(), this doesn't show loading message or touch modal visibility
 * @param {Object} file - File object to preview
 */
async function updatePreviewContent(file) {
  const { filename, content } = getElements();

  // Update state and filename
  state.currentPreviewFile = file;
  filename.textContent = file.name;

  // Fade out current content
  content.style.opacity = '0';

  // Wait for fade out transition (150ms matches CSS transition duration)
  await new Promise(resolve => setTimeout(resolve, 150));

  // Generate new content based on file type
  try {
    if (file.preview_type === 'image') {
      content.innerHTML = `<img src="${getFileUrl(file.path)}" alt="${escapeHtml(file.name)}">`;
    } else if (file.preview_type === 'video') {
      content.innerHTML = `<video controls src="${getFileUrl(file.path)}"></video>`;
    } else if (file.preview_type === 'audio') {
      content.innerHTML = `<audio controls src="${getFileUrl(file.path)}"></audio>`;
    } else if (file.preview_type === 'text' || file.preview_type === 'code') {
      const data = await fetchTextPreview(file.path);
      const truncatedNote = data.truncated
        ? `<p class="muted">(Showing first 1000 chars of ${formatFileSize(data.size)})</p>`
        : '';
      content.innerHTML = `<pre>${escapeHtml(data.content)}</pre>${truncatedNote}`;
    } else {
      content.innerHTML = `
        <div class="muted">
          <p>Preview not available for this file type</p>
          <p>File: ${escapeHtml(file.name)}</p>
          <p>Size: ${formatFileSize(file.size)}</p>
          <p>Type: ${file.mime_type || 'unknown'}</p>
        </div>
      `;
    }
  } catch (error) {
    content.innerHTML = `<p class="muted">Failed to load preview: ${error.message}</p>`;
  }

  // Fade in new content
  content.style.opacity = '1';

  // Update navigation UI after loading content
  updateNavigationUI();
}

/**
 * Get list of navigable files (files only, no directories) from the current grid
 * @returns {Array} Array of file objects from state.fileDataMap in DOM order
 */
function getNavigableFiles() {
  const fileGrid = document.getElementById('file_grid');
  const fileItems = fileGrid.querySelectorAll('.file-item');

  return Array.from(fileItems)
    .map(item => state.fileDataMap.get(item.dataset.path))
    .filter(file => file !== undefined);
}

/**
 * Get the index of the current preview file in the navigable files array
 * @returns {number} Index of current file, or -1 if not found
 */
function getCurrentFileIndex() {
  if (!state.currentPreviewFile) return -1;

  const files = getNavigableFiles();
  return files.findIndex(file => file.path === state.currentPreviewFile.path);
}

/**
 * Update the navigation bar UI (index display and button states)
 */
export function updateNavigationUI() {
  const { navPrev, navNext, navIndex } = getElements();
  if (!navPrev || !navNext || !navIndex) return;

  const files = getNavigableFiles();
  const currentIndex = getCurrentFileIndex();
  const total = files.length;

  // Update index display (1-based for user display)
  navIndex.textContent = total > 0 ? `${currentIndex + 1}/${total}` : '0/0';

  // Update button states
  navPrev.disabled = currentIndex <= 0;
  navNext.disabled = currentIndex === -1 || currentIndex >= total - 1;
}

/**
 * Navigate to the previous file in the preview modal
 * Stops at the first file (no wrap-around)
 */
export function navigatePreviewPrev() {
  const files = getNavigableFiles();
  const currentIndex = getCurrentFileIndex();

  if (currentIndex <= 0) {
    // Already at the first file or not found
    return;
  }

  const prevFile = files[currentIndex - 1];
  updatePreviewContent(prevFile);
}

/**
 * Navigate to the next file in the preview modal
 * Stops at the last file (no wrap-around)
 */
export function navigatePreviewNext() {
  const files = getNavigableFiles();
  const currentIndex = getCurrentFileIndex();

  if (currentIndex === -1 || currentIndex >= files.length - 1) {
    // At the last file or not found
    return;
  }

  const nextFile = files[currentIndex + 1];
  updatePreviewContent(nextFile);
}

export function downloadCurrentFile() {
  if (state.currentPreviewFile) {
    window.location.href = getFileUrl(state.currentPreviewFile.path, true);
  }
}

export async function deleteCurrentFile() {
  if (!state.currentPreviewFile) return;

  if (!confirm(`Delete "${state.currentPreviewFile.name}"?`)) return;

  const deletedPath = state.currentPreviewFile.path;

  try {
    await deleteFile(deletedPath);
    showStatus('File deleted successfully', 'success');
    closePreview();
    // Remove the item from grid directly instead of triggering full refresh
    removeItemFromGrid(deletedPath);
  } catch (error) {
    if (error.code === 'directory_not_empty') {
      if (confirm('Directory is not empty. Delete anyway? This will delete all contents.')) {
        await deleteFileForce(deletedPath);
        showStatus('Deleted successfully', 'success');
        closePreview();
        // Remove the item from grid directly instead of triggering full refresh
        removeItemFromGrid(deletedPath);
      }
    } else {
      showStatus('Delete failed: ' + error.message, 'error');
    }
  }
}

// Direct file actions (used by navigation buttons and context menu)
export function downloadFileDirectly(filepath) {
  window.location.href = getFileUrl(filepath, true);
}

export function downloadDirectoryDirectly(dirpath) {
  window.location.href = `/api/download-dir/${dirpath}`;
}

export async function deleteFileDirectly(filepath, filename, onComplete) {
  if (!confirm(`Delete "${filename}"?`)) return;

  try {
    await deleteFile(filepath);
    showStatus('Deleted successfully', 'success');
    if (onComplete) {
      onComplete();
    }
  } catch (error) {
    if (error.code === 'directory_not_empty') {
      if (confirm('Directory is not empty. Delete anyway?')) {
        await deleteFileForce(filepath);
        showStatus('Deleted successfully', 'success');
        if (onComplete) {
          onComplete();
        }
      }
    } else {
      showStatus('Delete failed: ' + error.message, 'error');
    }
  }
}

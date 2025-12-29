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

/**
 * Generate HTML content for previewing a file based on its type.
 * This is the single source of truth for preview content generation.
 * @param {Object} file - File object with preview_type, path, name, size, mime_type
 * @returns {Promise<string>} HTML string for the preview content
 */
async function generatePreviewContentHtml(file) {
  if (file.preview_type === 'image') {
    return `<img src="${getFileUrl(file.path)}" alt="${escapeHtml(file.name)}">`;
  } else if (file.preview_type === 'video') {
    return `<video controls src="${getFileUrl(file.path)}"></video>`;
  } else if (file.preview_type === 'audio') {
    return `<audio controls src="${getFileUrl(file.path)}"></audio>`;
  } else if (file.preview_type === 'text' || file.preview_type === 'code') {
    const data = await fetchTextPreview(file.path);
    const truncatedNote = data.truncated
      ? `<p class="muted">(Showing first 1000 chars of ${formatFileSize(data.size)})</p>`
      : '';
    return `<pre>${escapeHtml(data.content)}</pre>${truncatedNote}`;
  } else {
    return `
      <div class="muted">
        <p>Preview not available for this file type</p>
        <p>File: ${escapeHtml(file.name)}</p>
        <p>Size: ${formatFileSize(file.size)}</p>
        <p>Type: ${file.mime_type || 'unknown'}</p>
      </div>
    `;
  }
}

export async function openPreview(file) {
  const { modal, filename, content } = getElements();

  state.currentPreviewFile = file;
  filename.textContent = file.name;
  content.innerHTML = '<p class="muted">Loading preview...</p>';
  modal.classList.remove('hidden');

  try {
    content.innerHTML = await generatePreviewContentHtml(file);
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

  // Generate new content
  try {
    content.innerHTML = await generatePreviewContentHtml(file);
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

// ===== Fullscreen Gallery Mode =====

// Fullscreen elements cache
let fullscreenElements = null;

function getFullscreenElements() {
  if (!fullscreenElements) {
    fullscreenElements = {
      gallery: document.getElementById('fullscreen_gallery'),
      content: document.getElementById('fullscreen_content'),
      navPrev: document.getElementById('fullscreen_nav_prev'),
      navNext: document.getElementById('fullscreen_nav_next'),
      navIndex: document.getElementById('fullscreen_nav_index'),
      closeBtn: document.getElementById('fullscreen_close'),
    };
  }
  return fullscreenElements;
}

/**
 * Check if Fullscreen API is supported
 * @returns {boolean} true if fullscreen is supported
 */
export function isFullscreenSupported() {
  return !!(
    document.fullscreenEnabled ||
    document.webkitFullscreenEnabled ||
    document.mozFullScreenEnabled ||
    document.msFullscreenEnabled
  );
}

/**
 * Check if currently in native fullscreen mode
 * @returns {boolean} true if in native fullscreen
 */
export function isInNativeFullscreen() {
  return !!(
    document.fullscreenElement ||
    document.webkitFullscreenElement ||
    document.mozFullScreenElement ||
    document.msFullscreenElement
  );
}

/**
 * Enter fullscreen gallery mode
 */
export async function enterFullscreen() {
  if (!state.currentPreviewFile) return;
  if (!isFullscreenSupported()) {
    showStatus('Fullscreen not supported in this browser', 'error', 3000);
    return;
  }

  const { gallery, content } = getFullscreenElements();

  // Copy current preview content to fullscreen container
  const previewContent = document.getElementById('preview_content');
  content.innerHTML = previewContent.innerHTML;

  // Show the fullscreen container
  gallery.classList.remove('hidden');

  // Update navigation UI
  updateFullscreenNavigationUI();

  // Request native fullscreen
  try {
    if (gallery.requestFullscreen) {
      await gallery.requestFullscreen();
    } else if (gallery.webkitRequestFullscreen) {
      await gallery.webkitRequestFullscreen();
    } else if (gallery.mozRequestFullScreen) {
      await gallery.mozRequestFullScreen();
    } else if (gallery.msRequestFullscreen) {
      await gallery.msRequestFullscreen();
    }
    state.isFullscreen = true;
  } catch (error) {
    console.error('Failed to enter fullscreen:', error);
    // Still show the fullscreen container even if native fullscreen fails
    state.isFullscreen = true;
  }
}

/**
 * Exit fullscreen gallery mode
 */
export async function exitFullscreen() {
  const { gallery, content: fullscreenContent } = getFullscreenElements();
  const { filename, content: previewContent } = getElements();

  // Sync preview modal with current state before exiting
  // (user may have navigated to a different file while in fullscreen)
  if (state.currentPreviewFile) {
    filename.textContent = state.currentPreviewFile.name;
    previewContent.innerHTML = fullscreenContent.innerHTML;
  }

  // Hide the fullscreen container
  gallery.classList.add('hidden');
  state.isFullscreen = false;

  // Exit native fullscreen if active
  if (isInNativeFullscreen()) {
    try {
      if (document.exitFullscreen) {
        await document.exitFullscreen();
      } else if (document.webkitExitFullscreen) {
        await document.webkitExitFullscreen();
      } else if (document.mozCancelFullScreen) {
        await document.mozCancelFullScreen();
      } else if (document.msExitFullscreen) {
        await document.msExitFullscreen();
      }
    } catch (error) {
      console.error('Failed to exit fullscreen:', error);
    }
  }
}

/**
 * Toggle fullscreen mode
 */
export async function toggleFullscreen() {
  if (state.isFullscreen) {
    await exitFullscreen();
  } else {
    await enterFullscreen();
  }
}

/**
 * Update fullscreen navigation UI
 */
export function updateFullscreenNavigationUI() {
  const { navPrev, navNext, navIndex } = getFullscreenElements();
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
 * Navigate to previous file in fullscreen mode
 */
export function navigateFullscreenPrev() {
  if (!state.isFullscreen) return;

  const files = getNavigableFiles();
  const currentIndex = getCurrentFileIndex();

  if (currentIndex <= 0) return;

  const prevFile = files[currentIndex - 1];
  updateFullscreenContent(prevFile);
}

/**
 * Navigate to next file in fullscreen mode
 */
export function navigateFullscreenNext() {
  if (!state.isFullscreen) return;

  const files = getNavigableFiles();
  const currentIndex = getCurrentFileIndex();

  if (currentIndex === -1 || currentIndex >= files.length - 1) return;

  const nextFile = files[currentIndex + 1];
  updateFullscreenContent(nextFile);
}

/**
 * Update fullscreen content with new file
 * @param {Object} file - File object to display
 */
async function updateFullscreenContent(file) {
  const { content } = getFullscreenElements();

  // Update state
  state.currentPreviewFile = file;

  // Fade out
  content.style.opacity = '0';
  await new Promise(resolve => setTimeout(resolve, 150));

  // Generate content
  try {
    content.innerHTML = await generatePreviewContentHtml(file);
  } catch (error) {
    content.innerHTML = `<p class="muted">Failed to load preview: ${error.message}</p>`;
  }

  // Fade in
  content.style.opacity = '1';

  // Update navigation UI for both preview and fullscreen
  updateNavigationUI();
  updateFullscreenNavigationUI();
}

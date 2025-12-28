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
}

export function closePreview() {
  const { modal, content } = getElements();
  modal.classList.add('hidden');
  state.currentPreviewFile = null;
  content.innerHTML = '';
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

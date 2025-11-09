// ===== State Management =====
let currentPath = '';
let currentViewMode = localStorage.getItem('view_mode') || 'list'; // list or gallery
let storedFiles = [];
let currentPreviewFile = null;
let uploadWsClient = null; // WebSocket client for upload progress

// ===== DOM Elements =====
// Header
const searchInput = document.getElementById('search_input');
const searchBtn = document.getElementById('search_btn');
const uploadBtn = document.getElementById('upload_btn');
const viewToggleBtn = document.getElementById('view_toggle_btn');
const viewIcon = document.getElementById('view_icon');

// Browser
const breadcrumbs = document.getElementById('breadcrumbs');
const browserContent = document.getElementById('browser_content');
const fileGrid = document.getElementById('file_grid');
const emptyState = document.getElementById('empty_state');
const uploadHereBtn = document.getElementById('upload_here_btn');
const statusMessage = document.getElementById('status_message');

// Upload Modal
const uploadModal = document.getElementById('upload_modal');
const closeUploadModal = document.getElementById('close_upload_modal');
const cancelUpload = document.getElementById('cancel_upload');
const uploadTargetPath = document.getElementById('upload_target_path');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file_input');
const filePreview = document.getElementById('file_preview');
const fileList = document.getElementById('file_list');
const fileCount = document.getElementById('file_count');
const clearFiles = document.getElementById('clear_files');
const startUpload = document.getElementById('start_upload');
const progressContainer = document.getElementById('progress_container');
const progressBar = document.getElementById('progress_bar');
const progressText = document.getElementById('progress_text');

// Preview Modal
const previewModal = document.getElementById('preview_modal');
const closePreviewModal = document.getElementById('close_preview_modal');
const previewFilename = document.getElementById('preview_filename');
const previewContent = document.getElementById('preview_content');
const downloadFile = document.getElementById('download_file');
const deleteFile = document.getElementById('delete_file');

// Search Modal
const searchModal = document.getElementById('search_modal');
const closeSearchModal = document.getElementById('close_search_modal');
const searchQuery = document.getElementById('search_query');
const searchResults = document.getElementById('search_results');
const noResults = document.getElementById('no_results');

// New Folder Modal
const newFolderModal = document.getElementById('new_folder_modal');
const closeNewFolderModal = document.getElementById('close_new_folder_modal');
const cancelNewFolder = document.getElementById('cancel_new_folder');
const createNewFolder = document.getElementById('create_new_folder');
const newFolderName = document.getElementById('new_folder_name');
const newFolderParentPath = document.getElementById('new_folder_parent_path');

// ===== Utility Functions =====
function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function getFileIcon(previewType, extension) {
  const icons = {
    image: '🖼️',
    video: '🎬',
    audio: '🎵',
    text: '📄',
    code: '📝',
    pdf: '📕',
    archive: '📦',
  };
  return icons[previewType] || '📄';
}

function showStatus(message, type = 'info', duration = 3000) {
  statusMessage.textContent = message;
  statusMessage.className = `status-message ${type}`;
  statusMessage.classList.remove('hidden');

  if (duration > 0) {
    setTimeout(() => {
      statusMessage.classList.add('hidden');
    }, duration);
  }
}

function hideStatus() {
  statusMessage.classList.add('hidden');
}

// ===== Navigation =====
async function navigateTo(path) {
  currentPath = path || '';
  await loadDirectory(currentPath);
}

async function loadDirectory(path) {
  try {
    const params = new URLSearchParams({ path: path || '' });
    const response = await fetch(`/api/browse?${params}`);

    if (!response.ok) {
      throw new Error('Failed to load directory');
    }

    const data = await response.json();
    renderBreadcrumbs(data.breadcrumbs);
    renderFileGrid(data.directories, data.files);
  } catch (error) {
    showStatus('Failed to load directory: ' + error.message, 'error');
  }
}

function renderBreadcrumbs(crumbs) {
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

  // Add the "New Folder" button at the end
  const newFolderButton = document.createElement('button');
  newFolderButton.id = 'new_folder_btn';
  newFolderButton.className = 'new-folder-btn';
  newFolderButton.title = 'Create new folder';
  newFolderButton.textContent = '+ New Folder';
  newFolderButton.addEventListener('click', openNewFolderModal);
  breadcrumbs.appendChild(newFolderButton);
}

function renderFileGrid(directories, files) {
  fileGrid.innerHTML = '';

  const hasContent = directories.length > 0 || files.length > 0;

  if (!hasContent) {
    emptyState.classList.remove('hidden');
    return;
  } else {
    emptyState.classList.add('hidden');
  }

  // Render directories first
  directories.forEach(dir => {
    const item = createFolderItem(dir);
    fileGrid.appendChild(item);
  });

  // Then render files
  files.forEach(file => {
    const item = createFileItem(file);
    fileGrid.appendChild(item);
  });
}

function createFolderItem(dir) {
  const item = document.createElement('div');
  item.className = 'folder-item';
  item.addEventListener('click', () => navigateTo(dir.path));

  if (currentViewMode === 'list') {
    item.innerHTML = `
      <div class="item-icon">📁</div>
      <div class="item-info">
        <div class="item-name">${escapeHtml(dir.name)}</div>
        <div class="item-details">${dir.file_count} file(s)</div>
      </div>
    `;
  } else {
    item.innerHTML = `
      <div class="item-icon">📁</div>
      <div class="item-name" title="${escapeHtml(dir.name)}">${escapeHtml(dir.name)}</div>
      <div class="item-details">${dir.file_count} file(s)</div>
    `;
  }

  return item;
}

function createFileItem(file) {
  const item = document.createElement('div');
  item.className = 'file-item';
  item.addEventListener('click', () => openPreview(file));

  const icon = getFileIcon(file.preview_type, file.extension);
  const size = formatFileSize(file.size);

  if (currentViewMode === 'list') {
    item.innerHTML = `
      <div class="item-icon">${icon}</div>
      <div class="item-info">
        <div class="item-name">${escapeHtml(file.name)}</div>
        <div class="item-details">${size} • ${file.extension || 'unknown'}</div>
      </div>
      <div class="item-actions">
        <button class="action-btn" onclick="event.stopPropagation(); downloadFileDirectly('${escapeHtml(file.path)}', '${escapeHtml(file.name)}')">Download</button>
        <button class="action-btn" onclick="event.stopPropagation(); deleteFileDirectly('${escapeHtml(file.path)}', '${escapeHtml(file.name)}')">Delete</button>
      </div>
    `;
  } else {
    // Gallery view - show thumbnail if available
    if (file.has_thumbnail && file.preview_type === 'image') {
      item.innerHTML = `
        <img src="/api/thumbnail/${file.path}" class="item-thumbnail" alt="${escapeHtml(file.name)}">
        <div class="item-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
        <div class="item-details">${size}</div>
      `;
    } else {
      item.innerHTML = `
        <div class="item-icon">${icon}</div>
        <div class="item-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
        <div class="item-details">${size}</div>
      `;
    }
  }

  return item;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ===== View Mode Toggle =====
function toggleViewMode() {
  currentViewMode = currentViewMode === 'list' ? 'gallery' : 'list';
  localStorage.setItem('view_mode', currentViewMode);

  browserContent.className = `browser-content ${currentViewMode}-view`;
  viewIcon.textContent = currentViewMode === 'list' ? '⊞' : '☰';

  // Re-render current directory
  loadDirectory(currentPath);
}

// ===== Upload Modal =====
function openUploadModal() {
  uploadTargetPath.textContent = '/' + currentPath;
  uploadModal.classList.remove('hidden');
}

function closeUploadModalFn() {
  uploadModal.classList.add('hidden');
  fileInput.value = '';
  storedFiles = [];
  updateFilePreview();
  progressContainer.classList.add('hidden');
}

function updateFilePreview() {
  if (storedFiles.length === 0) {
    filePreview.classList.add('hidden');
    return;
  }

  filePreview.classList.remove('hidden');
  fileCount.textContent = storedFiles.length;
  fileList.innerHTML = '';

  storedFiles.forEach((file, index) => {
    const item = document.createElement('div');
    item.className = 'file-item';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'file-name';
    nameSpan.textContent = file.name;
    nameSpan.title = file.name;

    const sizeSpan = document.createElement('span');
    sizeSpan.className = 'file-size';
    sizeSpan.textContent = formatFileSize(file.size);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'file-remove';
    removeBtn.textContent = 'Remove';
    removeBtn.addEventListener('click', () => removeFile(index));

    item.appendChild(nameSpan);
    item.appendChild(sizeSpan);
    item.appendChild(removeBtn);
    fileList.appendChild(item);
  });
}

function removeFile(index) {
  storedFiles.splice(index, 1);
  const dt = new DataTransfer();
  storedFiles.forEach(f => dt.items.add(f));
  fileInput.files = dt.files;
  updateFilePreview();
}

async function performUpload() {
  if (storedFiles.length === 0) {
    showStatus('No files selected', 'error');
    return;
  }

  // Check WebSocket support
  if (!UploadWebSocketClient.isSupported()) {
    console.warn('WebSocket not supported, falling back to legacy upload');
    await performUploadLegacy();
    return;
  }

  try {
    // Connect to WebSocket
    showStatus('Connecting...', 'info', 0);
    uploadWsClient = new UploadWebSocketClient();

    // Register message handlers
    uploadWsClient.on('upload_started', handleUploadStarted);
    uploadWsClient.on('progress', handleUploadProgress);
    uploadWsClient.on('file_complete', handleFileComplete);
    uploadWsClient.on('error', handleUploadError);
    uploadWsClient.on('complete', handleUploadComplete);

    // Connect and get session ID
    const sessionId = await uploadWsClient.connect();
    console.log('Got session ID:', sessionId);

    // Prepare form data
    const formData = new FormData();
    storedFiles.forEach(file => formData.append('files', file));
    formData.append('target_dir', currentPath);
    formData.append('session_id', sessionId);

    // Show progress
    progressContainer.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressText.textContent = '0%';
    hideStatus();

    // Start upload (XHR for upload progress)
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      // This shows bytes sent to server, not processing progress
      // WebSocket will show actual processing progress
      if (e.lengthComputable) {
        const sendPercent = Math.round((e.loaded / e.total) * 100);
        console.log(`Bytes sent: ${sendPercent}%`);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        // Success handled by WebSocket 'complete' event
        console.log('Upload HTTP request completed');
      } else {
        // Error not caught by WebSocket
        handleUploadError({
          type: 'error',
          message: `Upload failed: ${xhr.statusText}`,
          code: xhr.status
        });
      }
    });

    xhr.addEventListener('error', () => {
      handleUploadError({
        type: 'error',
        message: 'Upload failed: Network error',
        code: 0
      });
    });

    xhr.open('POST', '/upload');
    xhr.send(formData);

  } catch (error) {
    console.error('Upload error:', error);
    showStatus('Upload failed: ' + error.message, 'error');
    progressContainer.classList.add('hidden');

    // Clean up WebSocket
    if (uploadWsClient) {
      uploadWsClient.close();
      uploadWsClient = null;
    }
  }
}

// WebSocket message handlers
function handleUploadStarted(data) {
  console.log('Upload started:', data);
  showStatus(`Uploading ${data.total_files} file(s)...`, 'info', 0);
}

function handleUploadProgress(data) {
  console.log('Progress:', data);
  progressBar.style.width = data.percent + '%';
  progressText.textContent = `${data.percent}% (${data.files_done}/${data.total_files} files)`;
}

function handleFileComplete(data) {
  console.log('File complete:', data.filename);
  // Could show a list of completed files here if desired
}

function handleUploadError(data) {
  console.error('Upload error:', data);

  // Show error IMMEDIATELY
  showStatus(
    `Error: ${data.message}${data.filename ? ` (${data.filename})` : ''}`,
    'error',
    0
  );

  // Hide progress bar
  progressContainer.classList.add('hidden');

  // Close WebSocket
  if (uploadWsClient) {
    uploadWsClient.close();
    uploadWsClient = null;
  }
}

function handleUploadComplete(data) {
  console.log('Upload complete:', data);

  progressContainer.classList.add('hidden');

  const hasErrors = data.errors && data.errors.length > 0;
  const message = hasErrors
    ? `Uploaded ${data.total_files} file(s) with ${data.errors.length} error(s)`
    : `Uploaded ${data.total_files} file(s) successfully`;

  showStatus(message, hasErrors ? 'warning' : 'success');

  closeUploadModalFn();
  loadDirectory(currentPath); // Refresh

  // Close WebSocket
  if (uploadWsClient) {
    uploadWsClient.close();
    uploadWsClient = null;
  }
}

// Legacy upload (no WebSocket) - fallback for browsers without WebSocket support
async function performUploadLegacy() {
  if (storedFiles.length === 0) {
    showStatus('No files selected', 'error');
    return;
  }

  const formData = new FormData();
  storedFiles.forEach(file => formData.append('files', file));
  formData.append('target_dir', currentPath);

  progressContainer.classList.remove('hidden');
  progressBar.style.width = '0%';
  progressText.textContent = '0%';

  const xhr = new XMLHttpRequest();

  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      const percent = Math.round((e.loaded / e.total) * 100);
      progressBar.style.width = percent + '%';
      progressText.textContent = percent + '%';
    }
  });

  xhr.addEventListener('load', () => {
    progressContainer.classList.add('hidden');

    if (xhr.status >= 200 && xhr.status < 300) {
      const data = JSON.parse(xhr.responseText);
      showStatus(`Uploaded ${data.saved.length} file(s) successfully`, 'success');
      closeUploadModalFn();
      loadDirectory(currentPath); // Refresh current directory
    } else {
      showStatus('Upload failed: ' + xhr.statusText, 'error');
    }
  });

  xhr.addEventListener('error', () => {
    progressContainer.classList.add('hidden');
    showStatus('Upload failed: Network error', 'error');
  });

  xhr.open('POST', '/upload');
  xhr.send(formData);
}

// ===== File Preview Modal =====
async function openPreview(file) {
  currentPreviewFile = file;
  previewFilename.textContent = file.name;
  previewContent.innerHTML = '<p class="muted">Loading preview...</p>';
  previewModal.classList.remove('hidden');

  try {
    if (file.preview_type === 'image') {
      previewContent.innerHTML = `<img src="/api/file/${file.path}" alt="${escapeHtml(file.name)}">`;
    } else if (file.preview_type === 'video') {
      previewContent.innerHTML = `<video controls src="/api/file/${file.path}"></video>`;
    } else if (file.preview_type === 'audio') {
      previewContent.innerHTML = `<audio controls src="/api/file/${file.path}"></audio>`;
    } else if (file.preview_type === 'text' || file.preview_type === 'code') {
      const response = await fetch(`/api/file/${file.path}`);
      const text = await response.text();
      previewContent.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
    } else {
      previewContent.innerHTML = `
        <div class="muted">
          <p>Preview not available for this file type</p>
          <p>File: ${escapeHtml(file.name)}</p>
          <p>Size: ${formatFileSize(file.size)}</p>
          <p>Type: ${file.mime_type || 'unknown'}</p>
        </div>
      `;
    }
  } catch (error) {
    previewContent.innerHTML = `<p class="muted">Failed to load preview: ${error.message}</p>`;
  }
}

function closePreviewModalFn() {
  previewModal.classList.add('hidden');
  currentPreviewFile = null;
  previewContent.innerHTML = '';
}

function downloadCurrentFile() {
  if (currentPreviewFile) {
    window.location.href = `/api/file/${currentPreviewFile.path}?download=1`;
  }
}

async function deleteCurrentFile() {
  if (!currentPreviewFile) return;

  if (!confirm(`Delete "${currentPreviewFile.name}"?`)) return;

  try {
    const response = await fetch(`/api/file/${currentPreviewFile.path}`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      const data = await response.json();
      if (data.error === 'directory_not_empty') {
        // Ask for confirmation to force delete
        if (confirm(`Directory is not empty. Delete anyway? This will delete all contents.`)) {
          await deleteFileWithForce(currentPreviewFile.path);
        }
        return;
      }
      throw new Error(data.message || 'Delete failed');
    }

    showStatus('File deleted successfully', 'success');
    closePreviewModalFn();
    loadDirectory(currentPath); // Refresh
  } catch (error) {
    showStatus('Delete failed: ' + error.message, 'error');
  }
}

async function deleteFileWithForce(filepath) {
  try {
    const response = await fetch(`/api/file/${filepath}?force=1`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      throw new Error('Delete failed');
    }

    showStatus('Deleted successfully', 'success');
    closePreviewModalFn();
    loadDirectory(currentPath); // Refresh
  } catch (error) {
    showStatus('Delete failed: ' + error.message, 'error');
  }
}

// Direct download/delete (from list view buttons)
function downloadFileDirectly(filepath, filename) {
  window.location.href = `/api/file/${filepath}?download=1`;
}

async function deleteFileDirectly(filepath, filename) {
  if (!confirm(`Delete "${filename}"?`)) return;

  try {
    const response = await fetch(`/api/file/${filepath}`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      const data = await response.json();
      if (data.error === 'directory_not_empty') {
        if (confirm(`Directory is not empty. Delete anyway?`)) {
          await deleteFileWithForce(filepath);
        }
        return;
      }
      throw new Error('Delete failed');
    }

    showStatus('Deleted successfully', 'success');
    loadDirectory(currentPath);
  } catch (error) {
    showStatus('Delete failed: ' + error.message, 'error');
  }
}

// ===== Search =====
async function performSearch() {
  const query = searchInput.value.trim();
  if (!query) {
    showStatus('Enter a search query', 'error', 2000);
    return;
  }

  try {
    const params = new URLSearchParams({ q: query });
    const response = await fetch(`/api/search?${params}`);

    if (!response.ok) {
      throw new Error('Search failed');
    }

    const data = await response.json();
    showSearchResults(query, data.results);
  } catch (error) {
    showStatus('Search failed: ' + error.message, 'error');
  }
}

function showSearchResults(query, results) {
  searchQuery.textContent = query;
  searchResults.innerHTML = '';

  if (results.length === 0) {
    searchResults.classList.add('hidden');
    noResults.classList.remove('hidden');
  } else {
    searchResults.classList.remove('hidden');
    noResults.classList.add('hidden');

    results.forEach(file => {
      const item = document.createElement('div');
      item.className = 'search-result-item';

      const icon = getFileIcon(file.preview_type, file.extension);

      item.innerHTML = `
        <div class="search-result-icon">${icon}</div>
        <div class="search-result-info">
          <div class="search-result-name">${escapeHtml(file.name)}</div>
          <div class="search-result-path">/${escapeHtml(file.parent_path)}</div>
        </div>
      `;

      item.addEventListener('click', () => {
        searchModal.classList.add('hidden');
        navigateTo(file.parent_path).then(() => {
          // Optionally highlight the file or open preview
          openPreview(file);
        });
      });

      searchResults.appendChild(item);
    });
  }

  searchModal.classList.remove('hidden');
}

function closeSearchModalFn() {
  searchModal.classList.add('hidden');
}

// ===== New Folder =====
function openNewFolderModal() {
  newFolderParentPath.textContent = '/' + currentPath;
  newFolderName.value = '';
  newFolderModal.classList.remove('hidden');
  // Focus the input for better UX
  setTimeout(() => newFolderName.focus(), 100);
}

function closeNewFolderModalFn() {
  newFolderModal.classList.add('hidden');
  newFolderName.value = '';
}

async function performCreateFolder() {
  const folderName = newFolderName.value.trim();

  if (!folderName) {
    showStatus('Please enter a folder name', 'error', 2000);
    return;
  }

  try {
    const params = new URLSearchParams({
      path: currentPath,
      name: folderName
    });

    const response = await fetch(`/api/directory?${params}`, {
      method: 'POST'
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Failed to create folder');
    }

    const data = await response.json();
    showStatus(data.message, 'success');
    closeNewFolderModalFn();
    loadDirectory(currentPath); // Refresh current directory
  } catch (error) {
    showStatus('Failed to create folder: ' + error.message, 'error');
  }
}

// ===== Drag and Drop on Browser =====
function setupBrowserDragDrop() {
  const browser = document.querySelector('.file-browser');

  browser.addEventListener('dragover', (e) => {
    e.preventDefault();
    browser.style.outline = '3px dashed var(--primary-color)';
  });

  browser.addEventListener('dragleave', () => {
    browser.style.outline = 'none';
  });

  browser.addEventListener('drop', (e) => {
    e.preventDefault();
    browser.style.outline = 'none';

    if (e.dataTransfer.files.length > 0) {
      const dt = new DataTransfer();
      Array.from(e.dataTransfer.files).forEach(f => dt.items.add(f));
      fileInput.files = dt.files;
      storedFiles = Array.from(dt.files);
      updateFilePreview();
      openUploadModal();
    }
  });
}

// ===== Event Listeners =====
viewToggleBtn.addEventListener('click', toggleViewMode);
uploadBtn.addEventListener('click', openUploadModal);
uploadHereBtn.addEventListener('click', openUploadModal);
closeUploadModal.addEventListener('click', closeUploadModalFn);
cancelUpload.addEventListener('click', closeUploadModalFn);
startUpload.addEventListener('click', performUpload);
clearFiles.addEventListener('click', () => {
  fileInput.value = '';
  storedFiles = [];
  updateFilePreview();
});

// Upload modal dropzone
dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropzone.classList.add('dragover');
});
dropzone.addEventListener('dragleave', () => {
  dropzone.classList.remove('dragover');
});
dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');

  if (e.dataTransfer.files.length > 0) {
    const dt = new DataTransfer();
    storedFiles.forEach(f => dt.items.add(f));
    Array.from(e.dataTransfer.files).forEach(f => dt.items.add(f));
    fileInput.files = dt.files;
    storedFiles = Array.from(dt.files);
    updateFilePreview();
  }
});

fileInput.addEventListener('change', () => {
  if (fileInput.files && fileInput.files.length > 0) {
    const dt = new DataTransfer();
    storedFiles.forEach(f => dt.items.add(f));
    Array.from(fileInput.files).forEach(f => dt.items.add(f));
    fileInput.files = dt.files;
    storedFiles = Array.from(dt.files);
    updateFilePreview();
  }
});

// Preview modal
closePreviewModal.addEventListener('click', closePreviewModalFn);
downloadFile.addEventListener('click', downloadCurrentFile);
deleteFile.addEventListener('click', deleteCurrentFile);

// Search
searchBtn.addEventListener('click', performSearch);
searchInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') performSearch();
});
closeSearchModal.addEventListener('click', closeSearchModalFn);

// New Folder (button is created dynamically in renderBreadcrumbs)
closeNewFolderModal.addEventListener('click', closeNewFolderModalFn);
cancelNewFolder.addEventListener('click', closeNewFolderModalFn);
createNewFolder.addEventListener('click', performCreateFolder);
newFolderName.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') performCreateFolder();
});

// Close modals on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!uploadModal.classList.contains('hidden')) closeUploadModalFn();
    if (!previewModal.classList.contains('hidden')) closePreviewModalFn();
    if (!searchModal.classList.contains('hidden')) closeSearchModalFn();
    if (!newFolderModal.classList.contains('hidden')) closeNewFolderModalFn();
  }
});

// ===== Initialize =====
browserContent.className = `browser-content ${currentViewMode}-view`;
viewIcon.textContent = currentViewMode === 'list' ? '⊞' : '☰';
setupBrowserDragDrop();
navigateTo(currentPath);

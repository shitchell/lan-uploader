// Upload modal and file handling
import { state } from './state.js';
import { formatFileSize, showStatus, hideStatus } from './utils.js';

// DOM elements (cached)
let elements = null;

function getElements() {
  if (!elements) {
    elements = {
      modal: document.getElementById('upload_modal'),
      targetPath: document.getElementById('upload_target_path'),
      dropzone: document.getElementById('dropzone'),
      fileInput: document.getElementById('file_input'),
      filePreview: document.getElementById('file_preview'),
      fileList: document.getElementById('file_list'),
      fileCount: document.getElementById('file_count'),
      progressContainer: document.getElementById('progress_container'),
      progressBar: document.getElementById('progress_bar'),
      progressText: document.getElementById('progress_text'),
    };
  }
  return elements;
}

// Callback for after upload completes
let onUploadComplete = null;

export function setUploadCompleteHandler(handler) {
  onUploadComplete = handler;
}

// Wake Lock helpers
async function acquireWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      state.wakeLock = await navigator.wakeLock.request('screen');
      console.log('Wake Lock acquired');
    } catch (err) {
      console.warn('Wake Lock failed:', err);
    }
  }
}

async function releaseWakeLock() {
  if (state.wakeLock) {
    await state.wakeLock.release();
    state.wakeLock = null;
    console.log('Wake Lock released');
  }
}

// Re-acquire on visibility change
document.addEventListener('visibilitychange', async () => {
  if (state.wakeLock !== null && document.visibilityState === 'visible') {
    await acquireWakeLock();
  }
});

export function openUploadModal() {
  const { modal, targetPath } = getElements();
  targetPath.textContent = '/' + state.currentPath;
  modal.classList.remove('hidden');
}

export function closeUploadModal() {
  const { modal, fileInput, progressContainer } = getElements();
  modal.classList.add('hidden');
  fileInput.value = '';
  state.storedFiles = [];
  updateFilePreview();
  progressContainer.classList.add('hidden');
}

export function updateFilePreview() {
  const { filePreview, fileCount, fileList } = getElements();

  if (state.storedFiles.length === 0) {
    filePreview.classList.add('hidden');
    return;
  }

  filePreview.classList.remove('hidden');
  fileCount.textContent = state.storedFiles.length;
  fileList.innerHTML = '';

  state.storedFiles.forEach((file, index) => {
    const item = document.createElement('div');
    item.className = 'file-item flex-between';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'file-name truncate';
    nameSpan.textContent = file.name;
    nameSpan.title = file.name;

    const sizeSpan = document.createElement('span');
    sizeSpan.className = 'file-size text-sm';
    sizeSpan.textContent = formatFileSize(file.size);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'file-remove btn-xs danger-btn';
    removeBtn.textContent = 'Remove';
    removeBtn.addEventListener('click', () => removeFile(index));

    item.appendChild(nameSpan);
    item.appendChild(sizeSpan);
    item.appendChild(removeBtn);
    fileList.appendChild(item);
  });
}

function removeFile(index) {
  const { fileInput } = getElements();
  state.storedFiles.splice(index, 1);
  const dt = new DataTransfer();
  state.storedFiles.forEach(f => dt.items.add(f));
  fileInput.files = dt.files;
  updateFilePreview();
}

export function clearFiles() {
  const { fileInput } = getElements();
  fileInput.value = '';
  state.storedFiles = [];
  updateFilePreview();
}

export function addFiles(files) {
  const { fileInput } = getElements();
  const dt = new DataTransfer();
  state.storedFiles.forEach(f => dt.items.add(f));
  Array.from(files).forEach(f => dt.items.add(f));
  fileInput.files = dt.files;
  state.storedFiles = Array.from(dt.files);
  updateFilePreview();
}

export async function performUpload() {
  if (state.storedFiles.length === 0) {
    showStatus('No files selected', 'error');
    return;
  }

  // Check WebSocket support
  if (typeof UploadWebSocketClient !== 'undefined' && UploadWebSocketClient.isSupported()) {
    await performUploadWebSocket();
  } else {
    console.warn('WebSocket not supported, falling back to legacy upload');
    await performUploadLegacy();
  }
}

async function performUploadWebSocket() {
  const { progressContainer, progressBar, progressText } = getElements();

  try {
    showStatus('Connecting...', 'info', 0);
    state.uploadWsClient = new UploadWebSocketClient();

    state.uploadWsClient.on('upload_started', handleUploadStarted);
    state.uploadWsClient.on('progress', handleUploadProgress);
    state.uploadWsClient.on('file_complete', handleFileComplete);
    state.uploadWsClient.on('error', handleUploadError);
    state.uploadWsClient.on('complete', handleUploadComplete);

    const sessionId = await state.uploadWsClient.connect();
    console.log('Got session ID:', sessionId);

    await acquireWakeLock();

    const formData = new FormData();
    state.storedFiles.forEach(file => formData.append('files', file));
    formData.append('target_dir', state.currentPath);
    formData.append('session_id', sessionId);

    progressContainer.classList.remove('hidden');
    progressBar.style.width = '0%';
    progressText.textContent = '0%';
    hideStatus();

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100);
        progressBar.style.width = percent + '%';
        progressText.textContent = `${percent}% (${formatFileSize(e.loaded)} / ${formatFileSize(e.total)})`;
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status < 200 || xhr.status >= 300) {
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

    if (state.uploadWsClient) {
      state.uploadWsClient.close();
      state.uploadWsClient = null;
    }
    await releaseWakeLock();
  }
}

function handleUploadStarted(data) {
  console.log('Upload started:', data);
  showStatus(`Uploading ${data.total_files} file(s)...`, 'info', 0);
}

function handleUploadProgress(data) {
  const { progressBar, progressText } = getElements();
  console.log('Progress:', data);
  progressBar.style.width = data.percent + '%';
  progressText.textContent = `${data.percent}% (${data.files_done}/${data.total_files} files)`;
}

function handleFileComplete(data) {
  console.log('File complete:', data.filename);
}

function handleUploadError(data) {
  const { progressContainer } = getElements();
  console.error('Upload error:', data);

  showStatus(
    `Error: ${data.message}${data.filename ? ` (${data.filename})` : ''}`,
    'error',
    0
  );

  progressContainer.classList.add('hidden');

  if (state.uploadWsClient) {
    state.uploadWsClient.close();
    state.uploadWsClient = null;
  }
  releaseWakeLock();
}

function handleUploadComplete(data) {
  const { progressContainer } = getElements();
  console.log('Upload complete:', data);

  progressContainer.classList.add('hidden');

  const hasErrors = data.errors && data.errors.length > 0;
  const message = hasErrors
    ? `Uploaded ${data.total_files} file(s) with ${data.errors.length} error(s)`
    : `Uploaded ${data.total_files} file(s) successfully`;

  showStatus(message, hasErrors ? 'warning' : 'success');

  closeUploadModal();

  if (state.uploadWsClient) {
    state.uploadWsClient.close();
    state.uploadWsClient = null;
  }
  releaseWakeLock();

  if (onUploadComplete) {
    onUploadComplete();
  }
}

async function performUploadLegacy() {
  const { progressContainer, progressBar, progressText } = getElements();

  await acquireWakeLock();

  const formData = new FormData();
  state.storedFiles.forEach(file => formData.append('files', file));
  formData.append('target_dir', state.currentPath);

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
    releaseWakeLock();

    if (xhr.status >= 200 && xhr.status < 300) {
      const data = JSON.parse(xhr.responseText);
      showStatus(`Uploaded ${data.saved.length} file(s) successfully`, 'success');
      closeUploadModal();
      if (onUploadComplete) {
        onUploadComplete();
      }
    } else {
      showStatus('Upload failed: ' + xhr.statusText, 'error');
    }
  });

  xhr.addEventListener('error', () => {
    progressContainer.classList.add('hidden');
    releaseWakeLock();
    showStatus('Upload failed: Network error', 'error');
  });

  xhr.open('POST', '/upload');
  xhr.send(formData);
}

// Setup dropzone and file input handlers
export function setupUploadHandlers() {
  const { dropzone, fileInput } = getElements();

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
      addFiles(e.dataTransfer.files);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length > 0) {
      addFiles(fileInput.files);
    }
  });
}

// Browser-wide drag and drop
export function setupBrowserDragDrop() {
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
      addFiles(e.dataTransfer.files);
      openUploadModal();
    }
  });
}

// Pure utility functions - no dependencies on state or DOM

export function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

export function getFileIcon(previewType) {
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

export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Status message element (cached on first use)
let statusMessageEl = null;

export function showStatus(message, type = 'info', duration = 3000) {
  if (!statusMessageEl) {
    statusMessageEl = document.getElementById('status_message');
  }
  statusMessageEl.textContent = message;
  statusMessageEl.className = `status-message ${type}`;
  statusMessageEl.classList.remove('hidden');

  if (duration > 0) {
    setTimeout(() => {
      statusMessageEl.classList.add('hidden');
    }, duration);
  }
}

export function hideStatus() {
  if (!statusMessageEl) {
    statusMessageEl = document.getElementById('status_message');
  }
  statusMessageEl.classList.add('hidden');
}

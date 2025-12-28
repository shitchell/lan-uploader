// API wrapper functions

export async function fetchDirectory(path, limit, offset) {
  const params = new URLSearchParams({
    path: path || '',
    limit,
    offset,
  });
  const response = await fetch(`/api/browse?${params}`);
  if (!response.ok) {
    throw new Error('Failed to load directory');
  }
  return response.json();
}

export async function searchFiles(query) {
  const params = new URLSearchParams({ q: query });
  const response = await fetch(`/api/search?${params}`);
  if (!response.ok) {
    throw new Error('Search failed');
  }
  return response.json();
}

export async function fetchTextPreview(path) {
  const response = await fetch(`/api/preview/${path}`);
  if (!response.ok) {
    throw new Error('Failed to load preview');
  }
  return response.json();
}

export async function deleteFile(path) {
  const response = await fetch(`/api/file/${path}`, { method: 'DELETE' });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.message || 'Delete failed');
    error.code = data.error;
    throw error;
  }
  return data;
}

export async function deleteFileForce(path) {
  const response = await fetch(`/api/file/${path}?force=1`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error('Delete failed');
  }
  return response.json();
}

export async function createDirectory(parentPath, name) {
  const params = new URLSearchParams({ path: parentPath, name });
  const response = await fetch(`/api/directory?${params}`, { method: 'POST' });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Failed to create folder');
  }
  return response.json();
}

// URL builders (for downloads and direct file access)
export function getFileUrl(path, download = false) {
  return `/api/file/${path}${download ? '?download=1' : ''}`;
}

export function getThumbnailUrl(path) {
  return `/api/thumbnail/${path}`;
}

export function getDirectoryDownloadUrl(path) {
  return `/api/download-dir/${path}`;
}

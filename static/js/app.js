const dz = document.getElementById('dropzone');
const fi = document.getElementById('file_input');
const upBtn = document.getElementById('upload_btn');
const statusEl = document.getElementById('status');
const targetInput = document.getElementById('target_dir');
const browseBtn = document.getElementById('browse_btn');
const browser = document.getElementById('browser');
const crumbs = document.getElementById('crumbs');
const dirlist = document.getElementById('dirlist');
const useFolderBtn = document.getElementById('use_folder');
const filePreview = document.getElementById('file_preview');
const fileList = document.getElementById('file_list');
const clearFilesBtn = document.getElementById('clear_files');
const progressContainer = document.getElementById('progress_container');
const progressBar = document.getElementById('progress_bar');
const progressText = document.getElementById('progress_text');

let currentPath = (targetInput.value || "").replace(/^\/+|\/+$/g, "");

// Load last directory from localStorage on page load
const savedDir = localStorage.getItem('last_dir');
if (savedDir) {
  targetInput.value = savedDir;
  currentPath = savedDir.replace(/^\/+|\/+$/g, "");
}

function setStatus(msg, cls="muted") {
  statusEl.className = "center " + cls; statusEl.textContent = msg;
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function updateFilePreview() {
  if (!fi.files || fi.files.length === 0) {
    filePreview.classList.add('hidden');
    setStatus('');
    return;
  }

  filePreview.classList.remove('hidden');
  fileList.innerHTML = '';

  Array.from(fi.files).forEach((file, index) => {
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
    removeBtn.title = 'Remove file';
    removeBtn.addEventListener('click', () => removeFile(index));

    item.appendChild(nameSpan);
    item.appendChild(sizeSpan);
    item.appendChild(removeBtn);
    fileList.appendChild(item);
  });

  setStatus(`${fi.files.length} file(s) ready to upload.`);
}

function removeFile(index) {
  const dt = new DataTransfer();
  Array.from(fi.files).forEach((file, i) => {
    if (i !== index) dt.items.add(file);
  });
  fi.files = dt.files;
  storedFiles = Array.from(fi.files);
  updateFilePreview();
}

clearFilesBtn.addEventListener('click', () => {
  fi.value = '';
  storedFiles = [];
  updateFilePreview();
});

// Store previously selected files for cumulative selection
let storedFiles = [];

fi.addEventListener('change', () => {
  // Merge existing files with newly selected files (cumulative selection)
  if (fi.files && fi.files.length > 0) {
    const dt = new DataTransfer();

    // Add previously stored files first
    storedFiles.forEach(f => dt.items.add(f));

    // Add newly selected files
    Array.from(fi.files).forEach(f => dt.items.add(f));

    // Update the input's files with merged list
    fi.files = dt.files;

    // Store current files for next selection
    storedFiles = Array.from(fi.files);
  }

  updateFilePreview();
});

dz.addEventListener('click', () => fi.click());
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
dz.addEventListener('drop', e => {
  e.preventDefault(); dz.classList.remove('dragover');

  // Merge dropped files with existing files (cumulative)
  const dt = new DataTransfer();

  // Add existing files first
  storedFiles.forEach(f => dt.items.add(f));

  // Add newly dropped files
  Array.from(e.dataTransfer.files).forEach(f => dt.items.add(f));

  fi.files = dt.files;
  storedFiles = Array.from(fi.files);

  updateFilePreview();
});

browseBtn.addEventListener('click', async () => {
  browser.classList.toggle('hidden');
  if (!browser.classList.contains('hidden')) {
    await refreshDir(currentPath);
  }
});
useFolderBtn.addEventListener('click', () => {
  targetInput.value = currentPath;
  // Save to localStorage when folder is selected
  localStorage.setItem('last_dir', currentPath);
  browser.classList.add('hidden');
});

async function refreshDir(relpath) {
  const qp = new URLSearchParams({ path: relpath || "" });
  const r = await fetch(`/api/dirs?${qp.toString()}`);
  if (!r.ok) { setStatus("Failed to load directories.", "error"); return; }
  const data = await r.json();
  currentPath = data.path || "";
  // Breadcrumbs
  crumbs.innerHTML = "";
  data.breadcrumbs.forEach((c, idx) => {
    const a = document.createElement('a');
    a.href = "#";
    a.textContent = c.label;
    a.addEventListener('click', (e) => { e.preventDefault(); refreshDir(c.relpath); });
    crumbs.appendChild(a);
    if (idx < data.breadcrumbs.length - 1) {
      const s = document.createElement('span'); s.textContent = "›"; s.style.margin = "0 4px"; crumbs.appendChild(s);
    }
  });
  // Directories
  dirlist.innerHTML = "";
  // Up link (..)
  if (currentPath) {
    const up = currentPath.split('/').slice(0, -1).join('/');
    const upDiv = document.createElement('div');
    upDiv.className = 'dir';
    upDiv.textContent = '⬆︎ ..';
    upDiv.addEventListener('click', () => refreshDir(up));
    dirlist.appendChild(upDiv);
  }
  data.dirs.forEach(d => {
    const div = document.createElement('div');
    div.className = 'dir';
    div.textContent = '📁 ' + d.name;
    div.addEventListener('click', () => refreshDir(d.relpath));
    dirlist.appendChild(div);
  });
}

upBtn.addEventListener('click', () => {
  if (!fi.files || fi.files.length === 0) {
    // On mobile, if no files selected, trigger picker
    fi.click();
    setStatus("Choose files to upload.");
    return;
  }

  const form = new FormData();
  for (const f of fi.files) form.append('files', f);
  form.append('target_dir', targetInput.value || "");

  // Show progress bar and hide status
  progressContainer.classList.remove('hidden');
  statusEl.textContent = '';
  progressBar.style.width = '0%';
  progressText.textContent = '0%';

  const xhr = new XMLHttpRequest();

  // Track upload progress
  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      const percentComplete = Math.round((e.loaded / e.total) * 100);
      progressBar.style.width = percentComplete + '%';
      progressText.textContent = percentComplete + '%';
    }
  });

  // Handle completion
  xhr.addEventListener('load', () => {
    progressContainer.classList.add('hidden');

    if (xhr.status >= 200 && xhr.status < 300) {
      try {
        const data = JSON.parse(xhr.responseText);
        const count = data.saved.length;
        setStatus(`✅ Uploaded ${count} file(s) to /${data.target_dir || ""}`, "success");

        // Save last directory to localStorage
        localStorage.setItem('last_dir', data.target_dir || "");

        // Clear selection and preview after a brief delay so user sees success
        setTimeout(() => {
          fi.value = '';
          storedFiles = [];
          updateFilePreview();
        }, 2000);
      } catch (e) {
        setStatus("Upload succeeded but response parsing failed", "error");
      }
    } else {
      setStatus("Upload failed: " + (xhr.statusText || "Unknown error"), "error");
    }
  });

  // Handle errors
  xhr.addEventListener('error', () => {
    progressContainer.classList.add('hidden');
    setStatus("Upload failed: Network error", "error");
  });

  xhr.addEventListener('abort', () => {
    progressContainer.classList.add('hidden');
    setStatus("Upload cancelled", "error");
  });

  // Send the request
  xhr.open('POST', '/upload');
  xhr.send(form);
});

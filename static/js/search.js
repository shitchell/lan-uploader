// Search functionality
import { escapeHtml, getFileIcon, showStatus } from './utils.js';
import { searchFiles } from './api.js';

// DOM elements (cached)
let elements = null;

function getElements() {
  if (!elements) {
    elements = {
      modal: document.getElementById('search_modal'),
      input: document.getElementById('search_input'),
      queryDisplay: document.getElementById('search_query'),
      results: document.getElementById('search_results'),
      noResults: document.getElementById('no_results'),
      headerActions: document.querySelector('.header-actions'),
      cancelBtn: document.getElementById('search_cancel'),
    };
  }
  return elements;
}

// Callbacks
let onResultClick = null;

export function setSearchResultHandler(handler) {
  onResultClick = handler;
}

export async function performSearch() {
  const { input } = getElements();
  const query = input.value.trim();

  if (!query) {
    showStatus('Enter a search query', 'error', 2000);
    return;
  }

  try {
    const data = await searchFiles(query);
    showSearchResults(query, data.results);
  } catch (error) {
    showStatus('Search failed: ' + error.message, 'error');
  }
}

function showSearchResults(query, results) {
  const { modal, queryDisplay, results: resultsContainer, noResults } = getElements();

  queryDisplay.textContent = query;
  resultsContainer.innerHTML = '';

  if (results.length === 0) {
    resultsContainer.classList.add('hidden');
    noResults.classList.remove('hidden');
  } else {
    resultsContainer.classList.remove('hidden');
    noResults.classList.add('hidden');

    results.forEach(file => {
      const item = document.createElement('div');
      item.className = 'search-result-item card';

      const icon = getFileIcon(file.preview_type);

      item.innerHTML = `
        <div class="search-result-icon">${icon}</div>
        <div class="search-result-info">
          <div class="search-result-name">${escapeHtml(file.name)}</div>
          <div class="search-result-path text-sm">/${escapeHtml(file.parent_path)}</div>
        </div>
      `;

      item.addEventListener('click', () => {
        modal.classList.add('hidden');
        if (onResultClick) {
          onResultClick(file);
        }
      });

      resultsContainer.appendChild(item);
    });
  }

  modal.classList.remove('hidden');
}

export function closeSearchModal() {
  const { modal } = getElements();
  modal.classList.add('hidden');
}

export function expandSearch() {
  const { headerActions, cancelBtn, input } = getElements();
  headerActions.classList.add('mobile-search-active');
  cancelBtn.classList.remove('hidden');
  input.focus();
}

export function collapseSearch() {
  const { headerActions, cancelBtn, input } = getElements();
  headerActions.classList.remove('mobile-search-active');
  cancelBtn.classList.add('hidden');
  input.value = '';
}

export function isMobileSearchActive() {
  const { headerActions } = getElements();
  return headerActions.classList.contains('mobile-search-active');
}

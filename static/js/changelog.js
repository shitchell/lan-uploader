// Changelog modal functionality
import { state } from './state.js';
import { getServerVersion, getChangelog } from './api.js';

// DOM elements cache
let elements = null;

function getElements() {
  if (!elements) {
    elements = {
      modal: document.getElementById('changelog_modal'),
      version: document.getElementById('changelog_version'),
      content: document.getElementById('changelog_content'),
      closeBtn: document.getElementById('close_changelog_modal'),
      dismissBtn: document.getElementById('dismiss_changelog'),
    };
  }
  return elements;
}

/**
 * Simple markdown to HTML converter for changelog content.
 * Handles headers, lists, and basic formatting.
 */
function markdownToHtml(markdown) {
  let html = markdown
    // Escape HTML entities first
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Headers (## and # only, # is h2, ## is h3 to avoid oversized headers)
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // Bold and italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // List items
    .replace(/^- (.+)$/gm, '<li>$1</li>');

  // Wrap consecutive <li> elements in <ul>
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

  // Paragraphs - wrap lines that aren't already wrapped
  const lines = html.split('\n');
  const processed = lines.map(line => {
    const trimmed = line.trim();
    if (!trimmed) return '';
    if (trimmed.startsWith('<h') || trimmed.startsWith('<ul') ||
        trimmed.startsWith('<li') || trimmed.startsWith('</')) {
      return line;
    }
    return `<p>${trimmed}</p>`;
  });

  return processed.join('\n');
}

/**
 * Open the changelog modal with the specified content.
 */
export function openChangelog(version, content) {
  const { modal, version: versionEl, content: contentEl } = getElements();

  versionEl.textContent = "What's new!";
  contentEl.innerHTML = markdownToHtml(content);
  modal.classList.remove('hidden');
}

/**
 * Close the changelog modal.
 */
export function closeChangelog() {
  const { modal, content } = getElements();
  modal.classList.add('hidden');
  content.innerHTML = '';
}

/**
 * Dismiss the changelog and update last seen version.
 */
export function dismissChangelog(version) {
  localStorage.setItem('last_seen_version', version);
  state.lastSeenVersion = version;
  closeChangelog();
}

/**
 * Check if the server version is newer than the last seen version.
 * If so, display the changelog modal.
 */
export async function checkVersion() {
  try {
    const serverVersion = await getServerVersion();
    let showChangelog = false;

    // If no last seen version, this is first visit - save and don't show
    if (!state.lastSeenVersion) {
      localStorage.setItem('last_seen_version', serverVersion);
      state.lastSeenVersion = serverVersion;
      // Unless this is version 2.0.0, then show the version :p
      if (state.lastSeenVersion === "2.0.0") showChangelog = true;
    }

    // If versions match, nothing to do
    if (!showChangelog && state.lastSeenVersion === serverVersion) {
      return;
    }

    // Version changed - fetch and show changelog
    const data = await getChangelog(serverVersion);
    openChangelog(serverVersion, data.content);

  } catch (error) {
    console.error('Failed to check version:', error);
    // Don't show error to user - version check is non-critical
  }
}

/**
 * Initialize changelog event listeners.
 */
export function initChangelog() {
  const { closeBtn, dismissBtn } = getElements();

  if (closeBtn) {
    closeBtn.addEventListener('click', closeChangelog);
  }

  if (dismissBtn) {
    dismissBtn.addEventListener('click', () => {
      getServerVersion().then(version => {
        dismissChangelog(version);
      });
    });
  }
}

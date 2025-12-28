// Context menu (right-click / long-press)
import { state } from './state.js';

// Action handlers - set by app.js to avoid circular imports
let actionHandlers = {
  download: null,
  delete: null,
};

export function setContextMenuHandlers(handlers) {
  actionHandlers = { ...actionHandlers, ...handlers };
}

// Registry of context menu actions by item type
const CONTEXT_MENU_ACTIONS = {
  base: [
    { id: 'download', label: 'Download', icon: '⬇️', action: 'download' },
    { id: 'delete', label: 'Delete', icon: '🗑️', action: 'delete', danger: true },
  ],
  directory: [],
  image: [],
  video: [],
  text: [],
};

function getContextMenuItems(itemType) {
  const baseActions = [...CONTEXT_MENU_ACTIONS.base];
  const typeActions = CONTEXT_MENU_ACTIONS[itemType] || [];
  return [...typeActions, ...baseActions];
}

export function showContextMenu(itemData, x, y) {
  hideContextMenu();

  state.contextMenuTarget = itemData;
  const itemType = itemData.isDirectory ? 'directory' : (itemData.preview_type || 'file');
  const menuItems = getContextMenuItems(itemType);

  const menu = document.createElement('div');
  menu.className = 'context-menu';
  menu.id = 'context_menu';

  menuItems.forEach((action, index) => {
    if (action.danger && index > 0 && !menuItems[index - 1].danger) {
      const separator = document.createElement('div');
      separator.className = 'context-menu-separator';
      menu.appendChild(separator);
    }

    const item = document.createElement('div');
    item.className = 'menu-item' + (action.danger ? ' danger' : '');
    item.innerHTML = `<span class="context-menu-icon">${action.icon}</span>${action.label}`;
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const target = state.contextMenuTarget;
      hideContextMenu();
      if (actionHandlers[action.action]) {
        actionHandlers[action.action](target);
      }
    });
    menu.appendChild(item);
  });

  document.body.appendChild(menu);
  state.activeContextMenu = menu;

  // Position within viewport
  const menuRect = menu.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  let finalX = x;
  let finalY = y;

  if (x + menuRect.width > viewportWidth) {
    finalX = viewportWidth - menuRect.width - 10;
  }
  if (y + menuRect.height > viewportHeight) {
    finalY = viewportHeight - menuRect.height - 10;
  }

  menu.style.left = finalX + 'px';
  menu.style.top = finalY + 'px';

  setTimeout(() => {
    document.addEventListener('click', hideContextMenu);
    document.addEventListener('scroll', hideContextMenu, true);
  }, 0);
}

export function hideContextMenu() {
  if (state.activeContextMenu) {
    state.activeContextMenu.remove();
    state.activeContextMenu = null;
    state.contextMenuTarget = null;
    document.removeEventListener('click', hideContextMenu);
    document.removeEventListener('scroll', hideContextMenu, true);
  }
}

function startLongPress(itemData, e) {
  state.longPressTimer = setTimeout(() => {
    e.preventDefault();
    const touch = e.touches[0];
    showContextMenu(itemData, touch.clientX, touch.clientY);
  }, state.LONG_PRESS_DURATION);
}

function cancelLongPress() {
  if (state.longPressTimer) {
    clearTimeout(state.longPressTimer);
    state.longPressTimer = null;
  }
}

export function attachContextMenuEvents(element, itemData) {
  element.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    showContextMenu(itemData, e.clientX, e.clientY);
  });

  element.addEventListener('touchstart', (e) => {
    startLongPress(itemData, e);
  }, { passive: true });

  element.addEventListener('touchend', cancelLongPress);
  element.addEventListener('touchmove', cancelLongPress);
  element.addEventListener('touchcancel', cancelLongPress);
}

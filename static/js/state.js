// Global application state
export const state = {
  currentPath: '',
  currentViewMode: localStorage.getItem('view_mode') || 'list',
  storedFiles: [],
  currentPreviewFile: null,
  uploadWsClient: null,
  wakeLock: null,

  // Pagination for infinite scroll
  PAGE_SIZE: 50,
  currentOffset: 0,
  hasMoreItems: false,
  isLoadingMore: false,
  infiniteScrollObserver: null,

  // Context menu
  activeContextMenu: null,
  contextMenuTarget: null,
  longPressTimer: null,
  LONG_PRESS_DURATION: 500,

  // Kebab overflow
  currentlyOverflowed: new Set(),

  // Selection state
  selectedElement: null,
};

import './styles.css';

import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';
import { type Level, getLetterAt, getCellWalls, WALL_TOP, WALL_LEFT } from './types';
import { dataLoader } from './data-loader';
import {
  type WordResult,
  type LevelState,
  type RuntimeLevelGroup,
  type SavedSettings,
  type SavedGameState,
  normalizeWord,
  clamp,
  cellKey,
  buildOccupiedCells,
  buildRevealedCells,
  minSwipeLength,
  computeBoardSize,
  findGroupById,
  countSolvedInGroup,
  findFirstUnfinishedInGroup,
  formatCompletionSummary,
  buildLevelName,
  serializeLevelState,
  GameStateManager,
} from './game-engine';
import {
  hasDictionaryEntry as sharedHasDictionaryEntry,
  getDictionaryEntry as sharedGetDictionaryEntry,
  type DictionaryEntry,
} from './dictionary';
import {
  getUnguessedWordHint as sharedGetUnguessedWordHint,
  type HintResult,
} from './hint-service';

type ActiveLevelState = LevelState;

type FeedbackTone = 'good' | 'bad' | 'bonus' | 'muted';
type GridWallKind = 'soft' | 'strong';

interface GridWallsLayer {
  root: SVGSVGElement;
  soft: SVGGElement;
  strong: SVGGElement;
}

interface Point {
  x: number;
  y: number;
}

const STORAGE_KEY = 'wordtracer-state-v2';
const IS_ANDROID = Capacitor.getPlatform() === 'android';
const SVG_NS = 'http://www.w3.org/2000/svg';
const BASE_WHEEL_SIZE = 216;

const MOVE_DEADZONE_BY_POINTER: Record<string, number> = {
  mouse: 7,
  touch: 12,
  pen: 9,
};
const DEFAULT_SETTINGS: SavedSettings = {
  autoAdvance: false,
  theme: 'dark',
  alwaysShowHint: false,
};

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) {
  throw new Error('Missing #app root element');
}

app.innerHTML = `
  <main class="shell">
    <header class="topbar">
      <button id="level-pack-button" type="button" class="level-pack-button" aria-haspopup="dialog" aria-expanded="false"></button>
      <h1>Word Tracer</h1>
      <button id="menu-button" type="button" class="menu-button" aria-label="Open menu" aria-expanded="false">☰</button>
    </header>

    <section class="board-stack">
      <section id="grid" class="grid" aria-label="Puzzle grid"></section>

      <section class="board-status">
        <p id="completion-summary" class="completion-summary"></p>
        <section class="status-row">
          <p id="feedback" class="feedback"><span id="feedback-prefix" class="feedback-prefix"></span><span id="feedback-word" class="feedback-word"></span></p>
          <p id="persistent-hint" class="persistent-hint" hidden></p>
        </section>
      </section>
    </section>

    <section class="wheel-stack">
      <section class="wheel-wrap">
        <div id="wheel" class="wheel" aria-label="Letter wheel">
          <svg class="wheel-path" viewBox="0 0 ${BASE_WHEEL_SIZE} ${BASE_WHEEL_SIZE}" preserveAspectRatio="none">
            <polyline id="selection-line" fill="none" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <section class="wheel-controls">
          <div class="wheel-actions">
            <button id="swap-tokens" type="button" class="clear-btn" aria-label="Swap token order">
              <svg class="swap-icon" viewBox="0 0 20 14" aria-hidden="true" focusable="false">
                <path d="M2 4H18" />
                <path d="M18 4 14 1" />
                <path d="M18 4 14 7" />
                <path d="M18 10H2" />
                <path d="M2 10 6 7" />
                <path d="M2 10 6 13" />
              </svg>
            </button>
            <button id="next-level-inline" type="button" class="next-level-btn" aria-hidden="true" disabled>Next\nLevel</button>
            <button id="dictionary-button" type="button" class="dictionary-open-btn" aria-label="Look up word definition" aria-expanded="false" disabled>
              <svg class="dictionary-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v15M20 22H6.5a2.5 2.5 0 0 1 0-5H20" />
                <path d="M20 17v5" />
                <path d="M9 2v6l2-1.5L13 8V2" />
              </svg>
            </button>
            <button id="hint-button" type="button" class="hint-open-btn" aria-label="Get hint" aria-expanded="false">
              <svg class="hint-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M12 2a7 7 0 0 0-7 7c0 2.38 1.19 4.47 3 5.74V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.26c1.81-1.27 3-3.36 3-5.74a7 7 0 0 0-7-7z" />
                <path d="M9 21h6" />
                <path d="M10 17v4" />
                <path d="M14 17v4" />
              </svg>
            </button>
            <button id="bonus-button" type="button" class="bonus-open-btn" aria-label="Bonus words" aria-expanded="false">
              <svg class="bonus-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="m12 3.3 2.8 5.6 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2-4.5-4.4 6.2-.9z" />
              </svg>
            </button>
          </div>
        </section>
      </section>
    </section>

    <section id="settings-activity" class="confirm-modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title" hidden>
      <div class="confirm-card settings-card">
        <div class="settings-head">
          <h2 id="settings-title">Settings</h2>
          <button id="close-menu" type="button" class="close-menu" aria-label="Close settings">✕</button>
        </div>

        <div class="settings-content">
          <label class="setting-row setting-row-switch">
            <span class="setting-label">Always show hint</span>
            <span class="switch">
              <input id="always-show-hint" class="switch-input" type="checkbox" />
              <span class="switch-ui" aria-hidden="true"></span>
            </span>
          </label>
          <label class="setting-row setting-row-switch">
            <span class="setting-label">Light mode</span>
            <span class="switch">
              <input id="light-theme" class="switch-input" type="checkbox" />
              <span class="switch-ui" aria-hidden="true"></span>
            </span>
          </label>
          <label class="setting-row setting-row-switch">
            <span class="setting-label">Auto-advance after level completion</span>
            <span class="switch">
              <input id="auto-advance" class="switch-input" type="checkbox" />
              <span class="switch-ui" aria-hidden="true"></span>
            </span>
          </label>
          <hr class="settings-separator" />
          <div class="settings-debug">
            <button id="debug-copy-level" type="button" class="settings-button">Debug: copy level state</button>
            <button id="debug-copy-state" type="button" class="settings-button">Debug: copy game state</button>
          </div>
          <div class="settings-reset-actions">
            <button id="reset-level" type="button" class="settings-button reset-level-btn">Reset level</button>
            <button id="reset-progress" type="button" class="settings-button reset-progress-btn">Reset all progress</button>
          </div>
          <hr class="settings-separator" />
          <p class="settings-about">
            Word Tracer v${__APP_VERSION__}<br />
            <a href="https://github.com/plhosk/wordtracer" target="_blank" rel="noopener noreferrer">https://github.com/plhosk/wordtracer</a>
          </p>
        </div>
      </div>
    </section>

    <section
      id="reset-level-modal"
      class="confirm-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-level-title"
      hidden
    >
      <div class="confirm-card">
        <h2 id="reset-level-title">Reset this level?</h2>
        <p class="small">This clears solved words, bonus words, and hint state for the current level.</p>
        <div class="confirm-actions">
          <button id="cancel-reset-level" type="button">Cancel</button>
          <button id="confirm-reset-level" type="button">Reset level</button>
        </div>
      </div>
    </section>

    <section
      id="reset-progress-modal"
      class="confirm-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-progress-title"
      hidden
    >
      <div class="confirm-card">
        <h2 id="reset-progress-title">Reset all progress?</h2>
        <p class="small">This clears solved words, bonus words, and unlocked levels.</p>
        <div class="confirm-actions">
          <button id="cancel-reset-progress" type="button">Cancel</button>
          <button id="confirm-reset-progress" type="button" class="danger-btn" disabled><span class="timer-text">5s</span> Reset all progress</button>
        </div>
      </div>
    </section>

    <section id="bonus-modal" class="confirm-modal bonus-modal" role="dialog" aria-modal="true" aria-labelledby="bonus-title" hidden>
      <div class="confirm-card bonus-card">
        <div class="settings-head bonus-head">
          <h2 id="bonus-title">Bonus Words</h2>
          <button id="close-bonus-modal" type="button" class="close-menu" aria-label="Close bonus">✕</button>
        </div>
        <p id="bonus-count" class="small"></p>
        <ul id="bonus-list"></ul>
      </div>
    </section>

    <section id="dictionary-modal" class="confirm-modal dictionary-modal" role="dialog" aria-modal="true" aria-labelledby="dictionary-title" hidden>
      <div class="confirm-card dictionary-card">
<div class="settings-head dictionary-head">
          <h2 id="dictionary-title">Dictionary</h2>
          <button id="close-dictionary-modal" type="button" class="close-menu" aria-label="Close dictionary">✕</button>
        </div>
        <p id="dictionary-word" class="dictionary-word"></p>
        <div id="dictionary-definitions" class="dictionary-definitions"></div>
      </div>
    </section>

    <section id="hint-modal" class="confirm-modal hint-modal" role="dialog" aria-modal="true" aria-labelledby="hint-title" hidden>
      <div class="confirm-card hint-card">
        <div class="settings-head hint-head">
          <h2 id="hint-title">Hint</h2>
          <button id="close-hint-modal" type="button" class="close-menu" aria-label="Close hint">✕</button>
        </div>
        <p id="hint-text" class="hint-text"></p>
        <button id="modal-refresh-hint-button" type="button" class="modal-refresh-hint-btn" aria-label="Refresh hint" disabled>
          <svg class="refresh-hint-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
            <path d="M3 21v-5h5" />
          </svg>
        </button>
      </div>
    </section>

    <section id="refresh-hint-modal" class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="refresh-hint-title" hidden>
      <div class="confirm-card">
        <h2 id="refresh-hint-title">Refresh hint?</h2>
        <p id="refresh-hint-subtitle" class="small">Can only be refreshed once per level.</p>
        <div id="refresh-hint-actions" class="confirm-actions">
          <button id="cancel-refresh-hint" type="button">Cancel</button>
          <button id="confirm-refresh-hint" type="button">Refresh</button>
        </div>
      </div>
    </section>

    <section id="level-pack-modal" class="confirm-modal level-pack-modal" role="dialog" aria-modal="true" aria-labelledby="level-pack-title" hidden>
      <div class="confirm-card level-pack-card">
        <div class="settings-head level-pack-head">
          <h2 id="level-pack-title">Level Packs</h2>
          <button id="close-level-pack-modal" type="button" class="close-menu" aria-label="Close level packs">✕</button>
        </div>
        <p id="level-pack-summary" class="small"></p>
        <ul id="level-pack-list" class="level-pack-list"></ul>
      </div>
    </section>
  </main>
`;

const levelPackButton = required('#level-pack-button') as HTMLButtonElement;
const feedback = required('#feedback');
const feedbackPrefix = required('#feedback-prefix');
const feedbackWord = required('#feedback-word');
const dictionaryButton = required('#dictionary-button') as HTMLButtonElement;
const completionSummary = required('#completion-summary');
const gridEl = required('#grid');
const wheelEl = required('#wheel');
const selectionLine = document.querySelector<SVGPolylineElement>('#selection-line')!;
const bonusList = required('#bonus-list');
const bonusCount = required('#bonus-count');
const menuButton = required('#menu-button') as HTMLButtonElement;
const closeMenuButton = required('#close-menu') as HTMLButtonElement;
const settingsActivity = required('#settings-activity');
const nextLevelInlineButton = required('#next-level-inline') as HTMLButtonElement;
const swapTokensButton = required('#swap-tokens') as HTMLButtonElement;
const bonusButton = required('#bonus-button') as HTMLButtonElement;
const bonusModal = required('#bonus-modal');
const closeBonusModalButton = required('#close-bonus-modal') as HTMLButtonElement;
const dictionaryModal = required('#dictionary-modal');
const closeDictionaryModalButton = required('#close-dictionary-modal') as HTMLButtonElement;
const dictionaryWord = required('#dictionary-word');
const dictionaryDefinitions = required('#dictionary-definitions');
const hintButton = required('#hint-button') as HTMLButtonElement;
const hintModal = required('#hint-modal');
const closeHintModalButton = required('#close-hint-modal') as HTMLButtonElement;
const hintText = required('#hint-text');
const modalRefreshHintButton = required('#modal-refresh-hint-button') as HTMLButtonElement;
const refreshHintModal = required('#refresh-hint-modal');
const refreshHintActions = required('#refresh-hint-actions');
const cancelRefreshHintButton = required('#cancel-refresh-hint') as HTMLButtonElement;
const confirmRefreshHintButton = required('#confirm-refresh-hint') as HTMLButtonElement;
const autoAdvanceInput = required('#auto-advance') as HTMLInputElement;
const lightThemeInput = required('#light-theme') as HTMLInputElement;
const alwaysShowHintInput = required('#always-show-hint') as HTMLInputElement;
const persistentHintEl = required('#persistent-hint') as HTMLParagraphElement;
const resetLevelButton = required('#reset-level') as HTMLButtonElement;
const resetLevelModal = required('#reset-level-modal');
const cancelResetLevelButton = required('#cancel-reset-level') as HTMLButtonElement;
const confirmResetLevelButton = required('#confirm-reset-level') as HTMLButtonElement;
const resetProgressButton = required('#reset-progress') as HTMLButtonElement;
const resetProgressModal = required('#reset-progress-modal');
const cancelResetProgressButton = required('#cancel-reset-progress') as HTMLButtonElement;
const confirmResetProgressButton = required('#confirm-reset-progress') as HTMLButtonElement;
const confirmResetTimerText = required('#confirm-reset-progress .timer-text');
const debugCopyStateButton = required('#debug-copy-state') as HTMLButtonElement;
const debugCopyLevelButton = required('#debug-copy-level') as HTMLButtonElement;
const levelPackModal = required('#level-pack-modal');
const closeLevelPackModalButton = required('#close-level-pack-modal') as HTMLButtonElement;
const levelPackSummary = required('#level-pack-summary');
const levelPackList = required('#level-pack-list');

let levelGroups: RuntimeLevelGroup[] = [];
let boardRows = 1;
let boardCols = 1;
let gameManager: GameStateManager;
let settings: SavedSettings = { ...DEFAULT_SETTINGS };
let letterCenters: Point[] = [];
let activeSelection: number[] = [];
let resetProgressTimer: ReturnType<typeof setInterval> | null = null;
let activePointerId: number | null = null;
let activePointerType = 'mouse';
let pointerPoint: Point | null = null;
let lastTrackedPoint: Point | null = null;
let wheelRect: DOMRect | null = null;
let wheelInitialized = false;
let feedbackText = '';
let feedbackWordText = '';
let feedbackToneClass = '';
let feedbackLookupWord = '';
let completionSummaryCarryover = '';
let recentSolvedCells = new Set<string>();
let previewingSelection = false;
let wheelSize = BASE_WHEEL_SIZE;

void init();

async function init(): Promise<void> {
  let initialGroupId: string;
  let initialLevels: Level[];
  
  try {
    const saved = await loadState();
    const preferredGroupId = saved?.currentGroupId;
    
    const data = await dataLoader.loadInitialLevels(preferredGroupId);
    levelGroups = data.groups;
    initialGroupId = data.initialGroupId;
    initialLevels = data.initialLevels;
  } catch (err) {
    setFeedback(`Failed to load game data: ${err}`, 'muted');
    return;
  }

  const groupDefinitions = dataLoader.getGroupDefinitions();
  gameManager = new GameStateManager(groupDefinitions, initialGroupId, initialLevels);

  const saved = await loadState();
  if (saved) {
    settings = loadSettings(saved.settings);

    const savedGroupId = saved.currentGroupId;
    if (savedGroupId && savedGroupId !== initialGroupId) {
      const savedLevels = await dataLoader.loadGroupLevels(savedGroupId);
      gameManager.setGroupLevels(savedGroupId, savedLevels);
    }
    
    gameManager = GameStateManager.hydrate(groupDefinitions, initialGroupId, initialLevels, saved);
  }

  const allLoadedLevels = dataLoader.getAllCachedLevels();
  if (allLoadedLevels.length > 0) {
    ({ rows: boardRows, cols: boardCols } = computeBoardSize(allLoadedLevels));
  }

  bindStaticEvents();
  preloadAdjacentGroups();
  render();
}

function bindStaticEvents(): void {
  document.addEventListener('selectstart', (event) => {
    event.preventDefault();
  });

  document.addEventListener('dragstart', (event) => {
    event.preventDefault();
  });

  document.addEventListener('pointermove', onDocumentPointerMove);
  document.addEventListener('pointerup', onDocumentPointerUp);
  document.addEventListener('pointercancel', onDocumentPointerCancel);

  window.addEventListener('resize', () => {
    cancelCurrentSwipe();
    render();
  });

  menuButton.addEventListener('click', () => {
    closeLevelPackModal(false);
    openSettingsActivity();
  });

  levelPackButton.addEventListener('click', () => {
    openLevelPackModal();
  });

  closeLevelPackModalButton.addEventListener('click', () => {
    closeLevelPackModal(true);
  });

  levelPackModal.addEventListener('click', (event) => {
    if (event.target === levelPackModal) {
      closeLevelPackModal(true);
    }
  });

  closeMenuButton.addEventListener('click', () => {
    closeSettingsActivity();
  });

  settingsActivity.addEventListener('click', (event) => {
    if (event.target === settingsActivity) {
      closeSettingsActivity();
    }
  });

  resetProgressModal.addEventListener('click', (event) => {
    if (event.target === resetProgressModal) {
      closeResetProgressModal(true);
    }
  });

  resetLevelModal.addEventListener('click', (event) => {
    if (event.target === resetLevelModal) {
      closeResetLevelModal(true);
    }
  });

  bonusModal.addEventListener('click', (event) => {
    if (event.target === bonusModal) {
      closeBonusModal(true);
    }
  });

  dictionaryModal.addEventListener('click', (event) => {
    if (event.target === dictionaryModal) {
      closeDictionaryModal(true);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (!resetLevelModal.hidden) {
        closeResetLevelModal(true);
        return;
      }
      if (!resetProgressModal.hidden) {
        closeResetProgressModal(true);
        return;
      }
      if (!levelPackModal.hidden) {
        closeLevelPackModal(true);
        return;
      }
      if (!bonusModal.hidden) {
        closeBonusModal(true);
        return;
      }
      if (!dictionaryModal.hidden) {
        closeDictionaryModal(true);
        return;
      }
      if (!hintModal.hidden) {
        closeHintModal(true);
        return;
      }
      if (!refreshHintModal.hidden) {
        closeRefreshHintModal(true);
        return;
      }
      closeSettingsActivity();
    }
  });

  swapTokensButton.addEventListener('click', () => {
    swapTokenOrder();
  });

  nextLevelInlineButton.addEventListener('click', async () => {
    const advanced = await advanceToNextLevelEnsuringLoaded();
    if (!advanced) return;
    
    clearCompletionSummaryCarryover();
    clearFeedback();
    clearRecentSolvedCells();
    clearSelection();
    preloadAdjacentGroups();
    render();
    saveState();
  });

  bonusButton.addEventListener('click', () => {
    openBonusModal();
  });

  closeBonusModalButton.addEventListener('click', () => {
    closeBonusModal(true);
  });

  dictionaryButton.addEventListener('click', () => {
    openDictionaryModal();
  });

  closeDictionaryModalButton.addEventListener('click', () => {
    closeDictionaryModal(true);
  });

  hintModal.addEventListener('click', (event) => {
    if (event.target === hintModal) {
      closeHintModal(true);
    }
  });

  hintButton.addEventListener('click', () => {
    openHintModal();
  });

  closeHintModalButton.addEventListener('click', () => {
    closeHintModal(true);
  });

  refreshHintModal.addEventListener('click', (event) => {
    if (event.target === refreshHintModal) {
      closeRefreshHintModal(true);
    }
  });

  modalRefreshHintButton.addEventListener('click', () => {
    openRefreshHintModal();
  });

  cancelRefreshHintButton.addEventListener('click', () => {
    closeRefreshHintModal(true);
  });

  confirmRefreshHintButton.addEventListener('click', () => {
    closeRefreshHintModal(false);
    refreshHint();
  });

  autoAdvanceInput.addEventListener('change', () => {
    settings.autoAdvance = autoAdvanceInput.checked;
    setFeedback(`Auto-advance ${settings.autoAdvance ? 'enabled' : 'disabled'}.`, 'muted');
    saveState();
  });

  lightThemeInput.addEventListener('change', () => {
    settings.theme = lightThemeInput.checked ? 'light' : 'dark';
    applyTheme();
    saveState();
  });

  alwaysShowHintInput.addEventListener('change', () => {
    settings.alwaysShowHint = alwaysShowHintInput.checked;
    if (!settings.alwaysShowHint) {
      persistentHintEl.hidden = true;
    } else {
      updatePersistentHint();
    }
    saveState();
  });

  resetLevelButton.addEventListener('click', () => {
    openResetLevelModal();
  });

  cancelResetLevelButton.addEventListener('click', () => {
    closeResetLevelModal(true);
  });

  confirmResetLevelButton.addEventListener('click', () => {
    closeResetLevelModal(false);
    resetCurrentLevelProgress();
    setFeedback('Level reset.', 'muted');
    render();
    saveState();
  });

  resetProgressButton.addEventListener('click', () => {
    openResetProgressModal();
  });

  cancelResetProgressButton.addEventListener('click', () => {
    closeResetProgressModal(true);
  });

  confirmResetProgressButton.addEventListener('click', async () => {
    closeResetProgressModal(false);
    await resetAllProgress();
    setFeedback('All progress reset.', 'muted');
    render();
    saveState();
  });

  debugCopyStateButton.addEventListener('click', async () => {
    const state = gameManager.serialize();
    state.settings = settings;
    const json = JSON.stringify(state, null, 2);
    await copyToClipboard(encodeBase64Utf8(json));
    setFeedback('Game state (base64) copied to clipboard.', 'muted');
  });

  debugCopyLevelButton.addEventListener('click', async () => {
    const level = gameManager.getCurrentLevel();
    const levelState = gameManager.getCurrentLevelState();
    const stateData = {
      levelId: level.id,
      groupId: gameManager.getCurrentGroupId(),
      indexInGroup: gameManager.getCurrentIndexInGroup(),
      letterWheel: level.letterWheel,
      ...serializeLevelState(levelState),
      tokenOrderMode: gameManager.getTokenOrderMode(),
    };
    const json = JSON.stringify(stateData, null, 2);
    await copyToClipboard(encodeBase64Utf8(json));
    setFeedback('Level state (base64) copied to clipboard.', 'muted');
  });
}

function render(): void {
  const level = gameManager.getCurrentLevel();
  const state = gameManager.getCurrentLevelState();
  const solvedCount = state.solved.size;
  const totalCount = level.answers.length;
  const levelDone = solvedCount >= totalCount;

  levelPackButton.textContent = `Level: ${buildLevelName(level)}`;
  levelPackButton.disabled = levelGroups.length <= 1;

  renderCompletionSummary(state, levelDone);
  renderSettings();
  renderTokenOrderToggle(levelDone);
  renderGrid(level, state);
  renderBonus(state);
  renderWheel(level);
  refreshDictionaryButton();
  updatePersistentHint();
  if (!levelPackModal.hidden) {
    renderLevelPackModal();
  }
}

function renderSettings(): void {
  autoAdvanceInput.checked = settings.autoAdvance;
  lightThemeInput.checked = settings.theme === 'light';
  alwaysShowHintInput.checked = settings.alwaysShowHint;
  applyTheme();
}

function currentGroupStatus(): { group: RuntimeLevelGroup; groupIndex: number } | null {
  return findGroupById(levelGroups, gameManager.getCurrentGroupId());
}

function groupSolvedLevels(group: RuntimeLevelGroup): number {
  const groupLevels = dataLoader.getCachedGroupLevels(group.id);
  if (!groupLevels) return 0;
  return countSolvedInGroup(groupLevels, gameManager.getAllLevelStates());
}

function firstUnfinishedGroupLevelIndex(group: RuntimeLevelGroup): number {
  const groupLevels = dataLoader.getCachedGroupLevels(group.id);
  if (!groupLevels) return 0;
  return findFirstUnfinishedInGroup(groupLevels, gameManager.getAllLevelStates());
}

function renderLevelPackModal(): void {
  const status = currentGroupStatus();
  const currentGroupIndex = status?.groupIndex ?? -1;
  levelPackSummary.textContent = `Packs: ${levelGroups.length}`;
  levelPackList.innerHTML = '';

  for (const group of levelGroups) {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'level-pack-item';
    const solved = groupSolvedLevels(group);
    const total = group.levelCount;
    button.textContent = `${group.id}\n${solved}/${total}`;
    if (total > 0 && solved >= total) {
      button.classList.add('level-pack-item-complete');
    } else if (solved > 0) {
      button.classList.add('level-pack-item-in-progress');
      if (group.index === currentGroupIndex) {
        button.classList.add('level-pack-item-current');
        button.setAttribute('aria-current', 'true');
      }
    } else if (group.index === currentGroupIndex) {
      button.setAttribute('aria-current', 'true');
    } else {
      button.classList.add('level-pack-item-unstarted');
    }
    button.addEventListener('click', () => {
      void jumpToGroup(group.index);
    });
    item.appendChild(button);
    levelPackList.appendChild(item);
  }
}

function renderTokenOrderToggle(levelDone: boolean): void {
  const swapped = gameManager.getTokenOrderMode() === 'reverse';
  swapTokensButton.setAttribute('aria-pressed', swapped ? 'true' : 'false');
  const canGoNext = levelDone && !settings.autoAdvance && gameManager.canAdvanceToNextLevel();
  nextLevelInlineButton.classList.toggle('next-level-btn-visible', canGoNext);
  nextLevelInlineButton.disabled = !canGoNext;
  nextLevelInlineButton.setAttribute('aria-hidden', canGoNext ? 'false' : 'true');
}

function swapTokenOrder(): void {
  gameManager.toggleTokenOrder();
  clearSelection();
  render();
}

function preloadAdjacentGroups(): void {
  const currentGroupId = gameManager.getCurrentGroupId();
  const currentGroupIndex = levelGroups.findIndex(g => g.id === currentGroupId);
  if (currentGroupIndex < 0) return;

  const nextIndex = currentGroupIndex + 1;
  if (nextIndex >= levelGroups.length) return;
  const group = levelGroups[nextIndex];
  if (!gameManager.hasGroupLoaded(group.id)) {
    dataLoader.loadGroupLevels(group.id).then((levels) => {
      gameManager.setGroupLevels(group.id, levels);
    }).catch(() => {});
  }
}

function renderCompletionSummary(state: ActiveLevelState, done: boolean): void {
  if (!done) {
    completionSummary.textContent = completionSummaryCarryover;
    return;
  }

  completionSummary.textContent = formatCompletionSummary(state);
}

function clearCompletionSummaryCarryover(): void {
  completionSummaryCarryover = '';
}

function renderGrid(level: Level, state: ActiveLevelState): void {
  gridEl.innerHTML = '';
  const maxDim = Math.max(boardRows, boardCols);
  const fontSizeRem = Math.max(1.02, 1.64 - (maxDim - 4) * 0.07);
  const occupied = buildOccupiedCells(level);
  const rowBounds = occupiedRowBounds(level, occupied);
  const visibleRows = Math.max(1, rowBounds.max - rowBounds.min + 1);
  const rowStart = rowBounds.min;
  const colOffset = centeredColOffset(level, occupied);
  gridEl.setAttribute(
    'style',
    `--rows:${visibleRows};--cols:${boardCols};--max-dim:${maxDim};--cell-font-size:${fontSizeRem.toFixed(2)}rem;`,
  );
  const wallsLayer = createGridWallsLayer(visibleRows, boardCols);
  gridEl.appendChild(wallsLayer.root);

  const revealed = buildRevealedCells(level, state.solved);

  for (let row = 0; row < visibleRows; row += 1) {
    for (let col = 0; col < boardCols; col += 1) {
      const cell = document.createElement('div');
      cell.className = 'cell';
      const levelRow = row + rowStart;
      const levelCol = col - colOffset;
      const currentOccupied = isOccupiedLevelCell(level, occupied, levelRow, levelCol);

      if (levelRow < 0 || levelRow >= level.rows || levelCol < 0 || levelCol >= level.cols) {
        cell.classList.add('cell-empty');
        gridEl.appendChild(cell);
        continue;
      }

      const key = cellKey(levelRow, levelCol);
      if (!currentOccupied) {
        cell.classList.add('cell-empty');
        gridEl.appendChild(cell);
        continue;
      }

      const topOccupied = isOccupiedLevelCell(level, occupied, levelRow - 1, levelCol);
      const leftOccupied = isOccupiedLevelCell(level, occupied, levelRow, levelCol - 1);
      const bottomOccupied = isOccupiedLevelCell(level, occupied, levelRow + 1, levelCol);
      const rightOccupied = isOccupiedLevelCell(level, occupied, levelRow, levelCol + 1);
      const cellWalls = getCellWalls(level.walls, levelRow, levelCol);
      const topHasPuzzleWall = topOccupied && cellWalls[WALL_TOP] === 1;
      const leftHasPuzzleWall = leftOccupied && cellWalls[WALL_LEFT] === 1;
      appendWallSegments(
        wallsLayer,
        row,
        col,
        topOccupied ? (topHasPuzzleWall ? 'strong' : 'soft') : 'strong',
        leftOccupied ? (leftHasPuzzleWall ? 'strong' : 'soft') : 'strong',
        bottomOccupied ? null : 'strong',
        rightOccupied ? null : 'strong',
      );

      if (revealed.has(key)) {
        const letter = getLetterAt(level, levelRow, levelCol);
        cell.textContent = letter?.toUpperCase() ?? '';
        cell.classList.add('cell-revealed');
      } else {
        cell.textContent = '';
        cell.classList.add('cell-hidden');
      }
      if (recentSolvedCells.has(key)) {
        cell.classList.add('cell-recent-solved');
      }
      gridEl.appendChild(cell);
    }
  }
}

function createGridWallsLayer(rows: number, cols: number): GridWallsLayer {
  const layer = document.createElementNS(SVG_NS, 'svg');
  layer.classList.add('grid-walls');
  layer.setAttribute('viewBox', `0 0 ${cols} ${rows}`);
  layer.setAttribute('preserveAspectRatio', 'none');
  layer.setAttribute('aria-hidden', 'true');
  const soft = document.createElementNS(SVG_NS, 'g');
  const strong = document.createElementNS(SVG_NS, 'g');
  layer.appendChild(soft);
  layer.appendChild(strong);
  return { root: layer, soft, strong };
}

function appendWallSegments(
  layer: GridWallsLayer,
  row: number,
  col: number,
  topWall: GridWallKind | null,
  leftWall: GridWallKind | null,
  bottomWall: GridWallKind | null,
  rightWall: GridWallKind | null,
): void {
  if (topWall) {
    appendWallLine(layer, col, row, col + 1, row, topWall);
  }
  if (leftWall) {
    appendWallLine(layer, col, row, col, row + 1, leftWall);
  }
  if (bottomWall) {
    appendWallLine(layer, col, row + 1, col + 1, row + 1, bottomWall);
  }
  if (rightWall) {
    appendWallLine(layer, col + 1, row, col + 1, row + 1, rightWall);
  }
}

function appendWallLine(
  layer: GridWallsLayer,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  kind: GridWallKind,
): void {
  const line = document.createElementNS(SVG_NS, 'line');
  line.classList.add('grid-wall-line', `grid-wall-line-${kind}`);
  line.setAttribute('x1', String(x1));
  line.setAttribute('y1', String(y1));
  line.setAttribute('x2', String(x2));
  line.setAttribute('y2', String(y2));
  if (kind === 'strong') {
    layer.strong.appendChild(line);
    return;
  }
  layer.soft.appendChild(line);
}

function isOccupiedLevelCell(level: Level, occupied: Set<string>, levelRow: number, levelCol: number): boolean {
  if (levelRow < 0 || levelRow >= level.rows || levelCol < 0 || levelCol >= level.cols) {
    return false;
  }
  return occupied.has(cellKey(levelRow, levelCol));
}

function centeredColOffset(level: Level, occupied: Set<string>): number {
  const targetCenter = (boardCols - 1) / 2;
  const bounds = occupiedColBounds(level, occupied);
  const occupiedCenter = (bounds.min + bounds.max) / 2;
  const desiredOffset = Math.round(targetCenter - occupiedCenter);
  return clamp(desiredOffset, -bounds.min, boardCols - 1 - bounds.max);
}

function occupiedRowBounds(level: Level, occupied: Set<string>): { min: number; max: number } {
  if (!occupied.size) {
    return { min: 0, max: level.rows - 1 };
  }
  let min = level.rows - 1;
  let max = 0;
  for (const key of occupied) {
    const [rowText] = key.split(':');
    const row = Number(rowText);
    min = Math.min(min, row);
    max = Math.max(max, row);
  }
  return { min, max };
}

function occupiedColBounds(level: Level, occupied: Set<string>): { min: number; max: number } {
  if (!occupied.size) {
    return { min: 0, max: level.cols - 1 };
  }
  let min = level.cols - 1;
  let max = 0;
  for (const key of occupied) {
    const [, colText] = key.split(':');
    const col = Number(colText);
    min = Math.min(min, col);
    max = Math.max(max, col);
  }
  return { min, max };
}

function renderBonus(state: ActiveLevelState): void {
  const known = [...state.bonus].sort((a, b) => a.localeCompare(b));
  bonusList.innerHTML = '';

  if (known.length) {
    for (const word of known) {
      const item = document.createElement('li');
      item.textContent = word.toUpperCase();
      bonusList.appendChild(item);
    }
  }

  bonusCount.textContent = `${known.length} found`;
}

function currentDictionaryWord(): string {
  return feedbackLookupWord;
}

function hasDictionaryEntry(word: string): boolean {
  const lookup = dataLoader.getDictionaryLookup();
  return sharedHasDictionaryEntry(lookup, word);
}

async function getDictionaryEntry(word: string): Promise<DictionaryEntry | null> {
  const lookup = dataLoader.getDictionaryLookup();
  return sharedGetDictionaryEntry(lookup, (letter) => dataLoader.loadDictionaryLetter(letter), word);
}

function refreshDictionaryButton(): void {
  const word = currentDictionaryWord();
  dictionaryButton.disabled = !hasDictionaryEntry(word);
}

async function renderDictionaryModal(lookupWord: string): Promise<void> {
  const entry = await getDictionaryEntry(lookupWord);
  if (!entry) {
    dictionaryWord.textContent = '';
    dictionaryDefinitions.innerHTML = '';
    return;
  }

  const { canonical, definition } = entry;
  const shownCanonical = canonical && canonical !== lookupWord
    ? canonical.toUpperCase()
    : lookupWord.toUpperCase();

  dictionaryWord.textContent = shownCanonical;
  dictionaryDefinitions.innerHTML = '';

  const chunks = definition
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk.length > 0);
  const items = chunks.length > 0 ? chunks : [definition.trim()];
  for (const item of items) {
    const paragraph = document.createElement('p');
    paragraph.className = 'dictionary-definition';
    paragraph.textContent = item;
    dictionaryDefinitions.appendChild(paragraph);
  }
}

function renderWheel(level: Level): void {
  wheelSize = wheelEl.offsetWidth;

  const wheelSvg = selectionLine.ownerSVGElement;
  if (wheelSvg) {
    wheelSvg.setAttribute('viewBox', `0 0 ${wheelSize} ${wheelSize}`);
  }

  if (!wheelInitialized) {
    wheelEl.addEventListener('pointerdown', onWheelPointerDown);
    wheelEl.addEventListener('pointermove', onWheelPointerMove);
    wheelEl.addEventListener('pointerup', onWheelPointerUp);
    wheelEl.addEventListener('pointercancel', onWheelPointerCancel);
    wheelInitialized = true;
  }

  const tokenCount = level.letterWheel.length;
  wheelEl.dataset.count = String(tokenCount);
  activeSelection = activeSelection.filter((index) => index >= 0 && index < tokenCount);

  wheelEl.querySelectorAll('.wheel-letter').forEach((node) => node.remove());
  for (let index = 0; index < tokenCount; index += 1) {
    const token = gameManager.displayToken(level.letterWheel[index]);
    const node = document.createElement('div');
    node.className = 'wheel-letter';
    node.textContent = token.toUpperCase();
    if (token.length >= 3) {
      node.classList.add('wheel-letter-compact');
    } else if (token.length === 2) {
      node.classList.add('wheel-letter-wide');
    }
    if (activeSelection.includes(index)) {
      node.classList.add('selected');
    }
    wheelEl.appendChild(node);
  }

  letterCenters = computeLetterCentersFromCount(tokenCount);

  updateSelectionPreview();
  drawSelectionPath();
}

// Keep wheel radius in sync with CSS: --wheel-radius: calc(var(--wheel-size) * 82 / 216)
function computeLetterCentersFromCount(count: number): Point[] {
  if (count <= 0) {
    return [];
  }

  const center = wheelSize / 2;
  const wheelRadius = wheelSize * 82 / 216;
  const points: Point[] = [];
  const offset = -Math.PI / 2;

  for (let idx = 0; idx < count; idx += 1) {
    const angle = offset + (Math.PI * 2 * idx) / count;
    points.push({
      x: center + Math.cos(angle) * wheelRadius,
      y: center + Math.sin(angle) * wheelRadius,
    });
  }

  return points;
}

function onWheelPointerDown(event: PointerEvent): void {
  if (!letterCenters.length || !event.isPrimary) {
    return;
  }
  if (event.pointerType === 'mouse' && event.button !== 0) {
    return;
  }

  beginSwipe(event);
}

function onDocumentPointerMove(event: PointerEvent): void {
  if (
    !settingsActivity.hidden
    || !bonusModal.hidden
    || !dictionaryModal.hidden
    || !levelPackModal.hidden
    || !resetLevelModal.hidden
    || !resetProgressModal.hidden
  ) {
    return;
  }
  if (activePointerId !== null || !letterCenters.length || !isPrimaryPointerPressed(event)) {
    return;
  }
  if (!isPointInsideWheel(event.clientX, event.clientY)) {
    return;
  }

  beginSwipe(event);
}

function onDocumentPointerUp(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) {
    return;
  }
  onWheelPointerUp(event);
}

function onDocumentPointerCancel(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) {
    return;
  }
  onWheelPointerCancel(event);
}

function beginSwipe(event: PointerEvent): void {
  cancelCurrentSwipe();
  activePointerId = event.pointerId;
  activePointerType = event.pointerType || 'mouse';
  wheelRect = wheelEl.getBoundingClientRect();
  pointerPoint = toWheelPoint(event);
  lastTrackedPoint = pointerPoint;
  wheelEl.setPointerCapture(event.pointerId);
  appendNearestLetter(event.clientX, event.clientY);
  updateSelectionPreview();
  drawSelectionPath();
}

function isPrimaryPointerPressed(event: PointerEvent): boolean {
  if (!event.isPrimary) {
    return false;
  }
  if (event.pointerType === 'mouse') {
    return (event.buttons & 1) === 1;
  }
  return event.buttons !== 0 || event.pressure > 0;
}

function isPointInsideWheel(clientX: number, clientY: number): boolean {
  const rect = wheelEl.getBoundingClientRect();
  return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
}

function onWheelPointerMove(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) {
    return;
  }
  pointerPoint = toWheelPoint(event);
  if (lastTrackedPoint) {
    const deadzone = pointerDeadzone(activePointerType);
    const moved = Math.hypot(pointerPoint.x - lastTrackedPoint.x, pointerPoint.y - lastTrackedPoint.y);
    if (moved < deadzone) {
      drawSelectionPath();
      return;
    }
  }
  lastTrackedPoint = pointerPoint;
  appendNearestLetter(event.clientX, event.clientY);
  updateSelectionPreview();
  drawSelectionPath();
}

function onWheelPointerUp(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) {
    return;
  }

  const submitted = activeWord();
  cancelCurrentSwipe();
  updateSelectionPreview();
  drawSelectionPath();
  if (submitted.length > 0) {
    clearCompletionSummaryCarryover();
    clearRecentSolvedCells();
    const result = submitted.length < minSwipeLength(gameManager.getCurrentLevel()) ? 'not-accepted' : submitWord(submitted);
    handleWordResult(result, submitted);
    render();
    saveState();
    if (result === 'solved' || result === 'bonus') {
      updatePersistentHint();
    }
  }
}

function onWheelPointerCancel(event: PointerEvent): void {
  if (event.pointerId !== activePointerId) {
    return;
  }
  cancelCurrentSwipe();
  updateSelectionPreview();
  drawSelectionPath();
}

function clearSelection(): void {
  cancelCurrentSwipe();
  updateSelectionPreview();
  drawSelectionPath();
}

function cancelCurrentSwipe(): void {
  releasePointerCaptureSafe(activePointerId);
  activeSelection = [];
  pointerPoint = null;
  activePointerId = null;
  activePointerType = 'mouse';
  lastTrackedPoint = null;
  wheelRect = null;
}

function releasePointerCaptureSafe(pointerId: number | null): void {
  if (pointerId === null) {
    return;
  }
  try {
    if (wheelEl.hasPointerCapture(pointerId)) {
      wheelEl.releasePointerCapture(pointerId);
    }
  } catch {
    // Browser may report invalid pointer ids during cancel/up races
  }
}

function appendNearestLetter(clientX: number, clientY: number): void {
  const nearest = findNearestIndex(clientX, clientY);
  if (nearest === null) {
    return;
  }
  if (activeSelection.includes(nearest)) {
    return;
  }
  activeSelection.push(nearest);
}

function findNearestIndex(clientX: number, clientY: number): number | null {
  const element = document.elementFromPoint(clientX, clientY);
  if (element && element.classList.contains('wheel-letter')) {
    const letters = wheelEl.querySelectorAll('.wheel-letter');
    return Array.from(letters).indexOf(element);
  }
  return null;
}

function toWheelPoint(event: PointerEvent): Point {
  const rect = wheelRect!;
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

function activeWord(): string {
  const letters = gameManager.getCurrentLevel().letterWheel;
  return activeSelection.map((index) => gameManager.displayToken(letters[index] ?? '')).join('').toLowerCase();
}

function renderFeedback(text: string, trailingWord = ''): void {
  if (trailingWord) {
    feedbackPrefix.textContent = text;
    feedbackWord.textContent = trailingWord;
    return;
  }

  feedbackPrefix.textContent = '';
  feedbackWord.textContent = text;
}

function updateSelectionPreview(): void {
  const word = activeWord();
  if (word) {
    previewingSelection = true;
    renderFeedback(word.toUpperCase());
    feedback.className = 'feedback feedback-preview';
    return;
  }

  if (!previewingSelection) {
    return;
  }

  previewingSelection = false;
  renderFeedback(feedbackText, feedbackWordText);
  const splitClass = feedbackWordText ? ' feedback-split' : '';
  feedback.className = feedbackToneClass
    ? `feedback${splitClass} ${feedbackToneClass}`
    : `feedback${splitClass}`;
  refreshDictionaryButton();
}

function drawSelectionPath(): void {
  if (!activeSelection.length) {
    selectionLine.setAttribute('points', '');
    return;
  }

  const points: Point[] = activeSelection.map((index) => letterCenters[index]);
  if (pointerPoint) {
    points.push(pointerPoint);
  }

  selectionLine.setAttribute('points', points.map((point) => `${point.x},${point.y}`).join(' '));
}

function submitWord(rawWord: string): WordResult {
  const result = gameManager.submitWord(rawWord);

  if (result.result === 'solved' && result.solvedCells.length > 0) {
    recentSolvedCells = new Set(result.solvedCells.map(([row, col]: [number, number]) => cellKey(row, col)));
  }

  if (result.levelComplete) {
    completeCurrentLevel();
  }

  return result.result;
}

function handleWordResult(result: WordResult, word: string): void {
  const upperWord = word.toUpperCase();
  switch (result) {
    case 'solved':
      setFeedback('Solved:', 'good', upperWord);
      break;
    case 'already-solved':
      setFeedback('Already solved:', 'muted', upperWord);
      break;
    case 'bonus':
      setFeedback('Bonus word:', 'bonus', upperWord);
      break;
    case 'already-bonus':
      setFeedback('Already found bonus:', 'muted', upperWord);
      break;
    case 'wrong-direction':
      setFeedback('Wrong token direction:', 'bad', upperWord);
      break;
    case 'not-spellable':
      setFeedback('Cannot spell:', 'bad', upperWord);
      break;
    case 'not-accepted':
      setFeedback('Not accepted:', 'bad', upperWord);
      break;
    default:
      break;
  }
}

function setFeedback(text: string, tone: FeedbackTone, trailingWord = ''): void {
  previewingSelection = false;
  feedbackText = text;
  feedbackWordText = trailingWord;
  feedbackLookupWord = trailingWord ? normalizeWord(trailingWord) : '';
  feedbackToneClass = `feedback-${tone}`;
  renderFeedback(text, trailingWord);
  const motionClass = tone === 'good' || tone === 'bonus' ? 'feedback-pop' : '';
  const splitClass = trailingWord ? ' feedback-split' : '';
  feedback.className = `feedback${splitClass}`;
  void feedback.offsetWidth;
  feedback.className = motionClass
    ? `feedback${splitClass} ${feedbackToneClass} ${motionClass}`
    : `feedback${splitClass} ${feedbackToneClass}`;
  refreshDictionaryButton();
}

function clearFeedback(): void {
  previewingSelection = false;
  feedbackText = '';
  feedbackWordText = '';
  feedbackLookupWord = '';
  feedbackToneClass = '';
  renderFeedback('');
  feedback.className = 'feedback';
  refreshDictionaryButton();
}

function clearRecentSolvedCells(): void {
  recentSolvedCells = new Set<string>();
}

async function completeCurrentLevel(): Promise<void> {
  if (!settings.autoAdvance) {
    return;
  }

  completionSummaryCarryover = formatCompletionSummary(gameManager.getCurrentLevelState());
  const advanced = await advanceToNextLevelEnsuringLoaded();
  if (!advanced) return;
  
  clearRecentSolvedCells();
  preloadAdjacentGroups();
}

function saveState(): void {
  const payload = gameManager.serialize();
  payload.settings = settings;
  void persistState(payload as SavedGameState);
}

async function persistState(payload: SavedGameState): Promise<void> {
  try {
    const value = JSON.stringify(payload);
    if (IS_ANDROID) {
      await Preferences.set({ key: STORAGE_KEY, value });
      return;
    }
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Storage unavailable in restricted environments
  }
}

async function loadState(): Promise<SavedGameState | null> {
  try {
    const raw = IS_ANDROID
      ? (await Preferences.get({ key: STORAGE_KEY })).value
      : localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as SavedGameState;
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function loadSettings(raw: SavedGameState['settings']): SavedSettings {
  const theme = raw?.theme === 'light' || raw?.theme === 'dark' ? raw.theme : DEFAULT_SETTINGS.theme;
  return {
    autoAdvance: typeof raw?.autoAdvance === 'boolean' ? raw.autoAdvance : DEFAULT_SETTINGS.autoAdvance,
    theme,
    alwaysShowHint: typeof raw?.alwaysShowHint === 'boolean' ? raw.alwaysShowHint : DEFAULT_SETTINGS.alwaysShowHint,
  };
}

function applyTheme(): void {
  document.documentElement.setAttribute('data-theme', settings.theme);
  document.body.style.removeProperty('background-color');
}

function openSettingsActivity(): void {
  closeDictionaryModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);
  settingsActivity.hidden = false;
  menuButton.setAttribute('aria-expanded', 'true');
}

function closeSettingsActivity(): void {
  closeResetProgressModal(false);
  settingsActivity.hidden = true;
  menuButton.setAttribute('aria-expanded', 'false');
}

function openLevelPackModal(): void {
  closeDictionaryModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  renderLevelPackModal();
  levelPackModal.hidden = false;
  levelPackButton.setAttribute('aria-expanded', 'true');
  closeLevelPackModalButton.focus();
}

function closeLevelPackModal(restoreFocus: boolean): void {
  if (levelPackModal.hidden) {
    return;
  }
  levelPackModal.hidden = true;
  levelPackButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) {
    levelPackButton.focus();
  }
}

async function jumpToGroup(groupIndex: number): Promise<void> {
  const targetGroup = levelGroups.find((group) => group.index === groupIndex);
  if (!targetGroup) {
    return;
  }
  const targetIndex = firstUnfinishedGroupLevelIndex(targetGroup);
  const jumped = await jumpToLevelEnsuringLoaded(targetGroup.id, targetIndex);
  if (!jumped) {
    return;
  }

  clearCompletionSummaryCarryover();
  clearFeedback();
  clearRecentSolvedCells();
  clearSelection();
  closeLevelPackModal(false);
  preloadAdjacentGroups();
  render();
  saveState();
}

function openBonusModal(): void {
  closeDictionaryModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);
  bonusModal.hidden = false;
  bonusButton.setAttribute('aria-expanded', 'true');
  closeBonusModalButton.focus();
}

function closeBonusModal(restoreFocus: boolean): void {
  if (bonusModal.hidden) {
    return;
  }
  bonusModal.hidden = true;
  bonusButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) {
    bonusButton.focus();
  }
}

async function openDictionaryModal(): Promise<void> {
  const lookupWord = currentDictionaryWord();
  if (!lookupWord || !hasDictionaryEntry(lookupWord)) {
    return;
  }

  closeBonusModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);
  await renderDictionaryModal(lookupWord);
  dictionaryModal.hidden = false;
  dictionaryButton.setAttribute('aria-expanded', 'true');
  closeDictionaryModalButton.focus();
}

function closeDictionaryModal(restoreFocus: boolean): void {
  if (dictionaryModal.hidden) {
    return;
  }

  dictionaryModal.hidden = true;
  dictionaryButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) {
    dictionaryButton.focus();
  }
}

async function getUnguessedWordHint(): Promise<HintResult | null> {
  const level = gameManager.getCurrentLevel();
  const state = gameManager.getCurrentLevelState();
  const solvedWords = new Set(state.solved);
  const lookup = dataLoader.getDictionaryLookup();

  return sharedGetUnguessedWordHint(
    level,
    solvedWords,
    state.hints.excludedHintCanonicals,
    state.hints.currentHintCanonical,
    lookup,
    dataLoader.getDictionaryHintRelatedForms(),
    getDictionaryEntry,
    (letter) => dataLoader.loadDictionaryLetter(letter)
  );
}

async function updatePersistentHint(): Promise<void> {
  if (!settings.alwaysShowHint) {
    persistentHintEl.hidden = true;
    return;
  }

  const hint = await getUnguessedWordHint();
  if (!hint) {
    persistentHintEl.hidden = true;
    return;
  }

  const state = gameManager.getCurrentLevelState();
  state.hints.currentHintCanonical = hint.canonical;

  if (!state.hints.hintedCanonicals.has(hint.canonical)) {
    state.hints.hintedCanonicals.add(hint.canonical);
    state.hints.hintCount += 1;
  }

  const e = hint.excerpt;
  persistentHintEl.textContent = (e.truncatedStart ? '...' : '') + e.text + (e.truncatedEnd ? '...' : '');
  persistentHintEl.hidden = false;
  saveState();
}

async function openHintModal(): Promise<void> {
  closeBonusModal(false);
  closeDictionaryModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);

  const state = gameManager.getCurrentLevelState();
  const hint = await getUnguessedWordHint();
  if (!hint) {
    hintText.textContent = 'No hints available.';
    modalRefreshHintButton.disabled = true;
    hintModal.hidden = false;
    hintButton.setAttribute('aria-expanded', 'true');
    closeHintModalButton.focus();
    return;
  }

  state.hints.currentHintCanonical = hint.canonical;

  if (!state.hints.hintedCanonicals.has(hint.canonical)) {
    state.hints.hintedCanonicals.add(hint.canonical);
    state.hints.hintCount += 1;
  }

  const e = hint.excerpt;
  const displayExcerpt = (e.truncatedStart ? '...' : '') + e.text + (e.truncatedEnd ? '...' : '');
  hintText.textContent = displayExcerpt;

  modalRefreshHintButton.disabled = state.hints.hintRefreshUsed;

  hintModal.hidden = false;
  hintButton.setAttribute('aria-expanded', 'true');
  closeHintModalButton.focus();
  saveState();
}

function closeHintModal(restoreFocus: boolean): void {
  if (hintModal.hidden) {
    return;
  }

  hintModal.hidden = true;
  hintButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) {
    hintButton.focus();
  }
}

function openRefreshHintModal(): void {
  closeHintModal(false);
  refreshHintActions.hidden = false;
  refreshHintModal.hidden = false;
  modalRefreshHintButton.setAttribute('aria-expanded', 'true');
  cancelRefreshHintButton.focus();
}

function closeRefreshHintModal(returnToHint: boolean): void {
  if (refreshHintModal.hidden) {
    return;
  }

  refreshHintModal.hidden = true;
  modalRefreshHintButton.setAttribute('aria-expanded', 'false');
  if (returnToHint) {
    hintModal.hidden = false;
    hintButton.setAttribute('aria-expanded', 'true');
    closeHintModalButton.focus();
  }
}

async function refreshHint(): Promise<void> {
  const state = gameManager.getCurrentLevelState();

  if (state.hints.hintRefreshUsed || !state.hints.currentHintCanonical) {
    return;
  }

  state.hints.excludedHintCanonicals.add(state.hints.currentHintCanonical);
  state.hints.hintRefreshUsed = true;
  state.hints.currentHintCanonical = null;

  const newHint = await getUnguessedWordHint();
  if (!newHint) {
    hintText.textContent = 'No hints available.';
    persistentHintEl.hidden = true;
    modalRefreshHintButton.disabled = true;
    hintModal.hidden = false;
    hintButton.setAttribute('aria-expanded', 'true');
    closeHintModalButton.focus();
    saveState();
    return;
  }

  state.hints.currentHintCanonical = newHint.canonical;

  if (!state.hints.hintedCanonicals.has(newHint.canonical)) {
    state.hints.hintedCanonicals.add(newHint.canonical);
    state.hints.hintCount += 1;
  }

  const e = newHint.excerpt;
  const displayExcerpt = (e.truncatedStart ? '...' : '') + e.text + (e.truncatedEnd ? '...' : '');
  hintText.textContent = displayExcerpt;
  if (settings.alwaysShowHint) {
    persistentHintEl.textContent = displayExcerpt;
  }

  modalRefreshHintButton.disabled = true;
  hintModal.hidden = false;
  hintButton.setAttribute('aria-expanded', 'true');
  closeHintModalButton.focus();
  saveState();
}

function openResetProgressModal(): void {
  settingsActivity.hidden = true;
  resetProgressModal.hidden = false;
  confirmResetProgressButton.disabled = true;
  confirmResetTimerText.textContent = '5s';
  let countdown = 5;
  resetProgressTimer = setInterval(() => {
    countdown--;
    if (countdown <= 0) {
      clearInterval(resetProgressTimer!);
      resetProgressTimer = null;
      confirmResetProgressButton.disabled = false;
      confirmResetTimerText.textContent = '';
    } else {
      confirmResetTimerText.textContent = `${countdown}s`;
    }
  }, 1000);
}

function openResetLevelModal(): void {
  settingsActivity.hidden = true;
  resetLevelModal.hidden = false;
  cancelResetLevelButton.focus();
}

function closeResetLevelModal(restoreFocus: boolean): void {
  if (resetLevelModal.hidden) {
    return;
  }
  resetLevelModal.hidden = true;
  if (restoreFocus) {
    resetLevelButton.focus();
  }
}

function closeResetProgressModal(restoreFocus: boolean): void {
  if (resetProgressTimer) {
    clearInterval(resetProgressTimer);
    resetProgressTimer = null;
  }
  if (resetProgressModal.hidden) {
    return;
  }
  resetProgressModal.hidden = true;
  confirmResetProgressButton.disabled = true;
  confirmResetTimerText.textContent = '5s';
  if (restoreFocus) {
    resetProgressButton.focus();
  }
}

async function resetAllProgress(): Promise<void> {
  gameManager.resetAllProgress();

  const jumpedToA1 = await jumpToLevelEnsuringLoaded('A', 0);
  if (!jumpedToA1) {
    const firstGroupId = gameManager.getCurrentGroupId();
    if (firstGroupId) {
      await ensureGroupLoaded(firstGroupId);
    }
  }

  clearCompletionSummaryCarryover();
  clearRecentSolvedCells();
  clearSelection();
  preloadAdjacentGroups();
}

function resetCurrentLevelProgress(): void {
  gameManager.resetCurrentLevelProgress();
  clearCompletionSummaryCarryover();
  clearRecentSolvedCells();
  clearSelection();
}

async function ensureGroupLoaded(groupId: string): Promise<void> {
  if (gameManager.hasGroupLoaded(groupId)) {
    return;
  }

  const levels = await dataLoader.loadGroupLevels(groupId);
  gameManager.setGroupLevels(groupId, levels);
}

async function advanceToNextLevelEnsuringLoaded(): Promise<boolean> {
  const result = gameManager.advanceToNextLevel();
  if (!result.advanced) {
    return false;
  }

  if (result.needsGroupLoad && result.nextGroupId) {
    await ensureGroupLoaded(result.nextGroupId);
  }

  return true;
}

async function jumpToLevelEnsuringLoaded(groupId: string, indexInGroup: number): Promise<boolean> {
  const result = gameManager.jumpToLevel(groupId, indexInGroup);
  if (!result.jumped) {
    return false;
  }

  await ensureGroupLoaded(groupId);
  return true;
}

function pointerDeadzone(pointerType: string): number {
  return MOVE_DEADZONE_BY_POINTER[pointerType] ?? MOVE_DEADZONE_BY_POINTER.mouse;
}

function required(selector: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(selector);
  if (!node) {
    throw new Error(`Missing element: ${selector}`);
  }
  return node;
}

function encodeBase64Utf8(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const parts: string[] = [];
  const chunkSize = 0x8000;

  for (let i = 0; i < bytes.length; i += chunkSize) {
    const end = Math.min(i + chunkSize, bytes.length);
    let chunk = '';
    for (let j = i; j < end; j += 1) {
      chunk += String.fromCharCode(bytes[j]);
    }
    parts.push(chunk);
  }

  return btoa(parts.join(''));
}

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }
}

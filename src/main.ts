import './styles.css';
import appShellHtml from './app-shell.html?raw';

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
  GAME_STATE_SCHEMA_VERSION,
  MAX_HINT_REFRESHES_PER_LEVEL,
} from './game-engine';
import {
  hasDictionaryEntry as sharedHasDictionaryEntry,
  getDictionaryEntry as sharedGetDictionaryEntry,
  type DictionaryEntry,
} from './dictionary';
import {
  getUnguessedWordHint as sharedGetUnguessedWordHint,
  canonicalHasUnsolvedWords,
  type HintResult,
} from './hint-service';

type ActiveLevelState = LevelState;
type ModalHintEntry = ActiveLevelState['hints']['modalHintStack'][number];

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
const DEFAULT_TOKEN_SWAP_ANIMATION_MS = 100;
const NO_HINTS_AVAILABLE_TEXT = 'No more hints available.';
const MAX_MODAL_HINT_STACK_SIZE = MAX_HINT_REFRESHES_PER_LEVEL + 1;

const MOVE_DEADZONE_BY_POINTER: Record<string, number> = {
  mouse: 7,
  touch: 12,
  pen: 9,
};
const DEFAULT_SETTINGS: SavedSettings = {
  autoAdvance: false,
  theme: 'dark',
  alwaysShowHint: false,
  preferModernHints: false,
  disableLetterRevealHint: false,
  disableSwapAnimation: false,
};

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) {
  throw new Error('Missing #app root element');
}

app.innerHTML = appShellHtml;
const appVersion = required('#app-version');
appVersion.textContent = __APP_VERSION__;

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
const helpButton = required('#help-button') as HTMLButtonElement;
const helpModal = required('#help-modal');
const closeHelpModalButton = required('#close-help-modal') as HTMLButtonElement;
const bonusModal = required('#bonus-modal');
const closeBonusModalButton = required('#close-bonus-modal') as HTMLButtonElement;
const dictionaryModal = required('#dictionary-modal');
const closeDictionaryModalButton = required('#close-dictionary-modal') as HTMLButtonElement;
const dictionaryWord = required('#dictionary-word');
const dictionaryDefinitions = required('#dictionary-definitions');
const hintButton = required('#hint-button') as HTMLButtonElement;
const hintModal = required('#hint-modal');
const closeHintModalButton = required('#close-hint-modal') as HTMLButtonElement;
const hintTextStack = required('#hint-text-stack') as HTMLDivElement;
const modalRefreshHintButton = required('#modal-refresh-hint-button') as HTMLButtonElement;
const refreshHintModal = required('#refresh-hint-modal');
const refreshHintSubtitle = required('#refresh-hint-subtitle');
const refreshHintNote = required('#refresh-hint-note') as HTMLParagraphElement;
const refreshHintActions = required('#refresh-hint-actions');
const cancelRefreshHintButton = required('#cancel-refresh-hint') as HTMLButtonElement;
const confirmRefreshHintButton = required('#confirm-refresh-hint') as HTMLButtonElement;
const revealLetterHintButton = required('#reveal-letter-hint') as HTMLButtonElement;
const autoAdvanceInput = required('#auto-advance') as HTMLInputElement;
const lightThemeInput = required('#light-theme') as HTMLInputElement;
const alwaysShowHintInput = required('#always-show-hint') as HTMLInputElement;
const preferModernHintsInput = required('#prefer-modern-hints') as HTMLInputElement;
const disableLetterRevealHintInput = required('#disable-letter-reveal-hint') as HTMLInputElement;
const disableSwapAnimationInput = required('#disable-swap-animation') as HTMLInputElement;
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
let refreshHintModalCheckSequence = 0;
let previewingSelection = false;
let wheelSize = BASE_WHEEL_SIZE;
let tokenSwapAnimationTimer: ReturnType<typeof window.setTimeout> | null = null;
let tokenSwapAnimationSequence = 0;
let suppressSwapButtonClickUntil = 0;
let revealLetterSelectionMode = false;
let revealModeFeedbackSnapshot: {
  text: string;
  trailingWord: string;
  toneClass: string;
  lookupWord: string;
} | null = null;

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
  if (!hasSolvedAnyWords()) {
    openHelpModal();
  }
}

function bindStaticEvents(): void {
  document.addEventListener('selectstart', (event) => {
    const target = event.target;
    let element: Element | null = null;
    if (target instanceof Element) {
      element = target;
    } else if (target instanceof Node) {
      element = target.parentElement;
    }
    if (
      element?.closest('#hint-text-stack')
      || element?.closest('#dictionary-word')
      || element?.closest('#dictionary-definitions')
    ) {
      return;
    }
    event.preventDefault();
  });

  document.addEventListener('dragstart', (event) => {
    event.preventDefault();
  });

  document.addEventListener('pointermove', onDocumentPointerMove);
  document.addEventListener('pointerup', onDocumentPointerUp);
  document.addEventListener('pointercancel', onDocumentPointerCancel);
  document.addEventListener('pointerdown', onDocumentPointerDown, true);

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

  helpModal.addEventListener('click', (event) => {
    if (event.target === helpModal) {
      closeHelpModal(true);
    }
  });

  dictionaryModal.addEventListener('click', (event) => {
    if (event.target === dictionaryModal) {
      closeDictionaryModal(true);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (revealLetterSelectionMode) {
        cancelRevealLetterSelectionMode();
        return;
      }
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
      if (!helpModal.hidden) {
        closeHelpModal(true);
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

  swapTokensButton.addEventListener('pointerdown', (event) => {
    if (event.pointerType === 'mouse') {
      return;
    }
    event.preventDefault();
    suppressSwapButtonClickUntil = performance.now() + 500;
    swapTokenOrder();
  });

  swapTokensButton.addEventListener('click', () => {
    if (performance.now() < suppressSwapButtonClickUntil) {
      return;
    }
    swapTokenOrder();
  });

  gridEl.addEventListener('pointerdown', () => {
    if (recentSolvedCells.size > 0) {
      gridEl.querySelectorAll('.cell-recent-solved').forEach((el) => {
        el.classList.remove('cell-recent-solved');
      });
      clearRecentSolvedCells();
    }
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

  helpButton.addEventListener('click', () => {
    openHelpModal();
  });

  closeHelpModalButton.addEventListener('click', () => {
    closeHelpModal(true);
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
    void openRefreshHintModal();
  });

  cancelRefreshHintButton.addEventListener('click', () => {
    closeRefreshHintModal(true);
  });

  confirmRefreshHintButton.addEventListener('click', () => {
    closeRefreshHintModal(false);
    refreshHint();
  });

  revealLetterHintButton.addEventListener('click', () => {
    closeRefreshHintModal(false);
    enterRevealLetterSelectionMode();
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

  preferModernHintsInput.addEventListener('change', () => {
    settings.preferModernHints = preferModernHintsInput.checked;
    if (settings.alwaysShowHint) {
      updatePersistentHint();
    }
    saveState();
  });

  disableLetterRevealHintInput.addEventListener('change', () => {
    settings.disableLetterRevealHint = disableLetterRevealHintInput.checked;
    if (settings.disableLetterRevealHint) {
      cancelRevealLetterSelectionMode();
    }
    saveState();
  });

  disableSwapAnimationInput.addEventListener('change', () => {
    settings.disableSwapAnimation = disableSwapAnimationInput.checked;
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
  preferModernHintsInput.checked = settings.preferModernHints;
  disableLetterRevealHintInput.checked = settings.disableLetterRevealHint;
  disableSwapAnimationInput.checked = settings.disableSwapAnimation;
  applyTheme();
}

function hasSolvedAnyWords(): boolean {
  for (const [levelId, levelState] of gameManager.getAllLevelStates()) {
    if (levelState.solved.size > 0 || gameManager.isLevelMarkedComplete(levelId)) {
      return true;
    }
  }
  return false;
}

function currentGroupStatus(): { group: RuntimeLevelGroup; groupIndex: number } | null {
  return findGroupById(levelGroups, gameManager.getCurrentGroupId());
}

function groupSolvedLevels(group: RuntimeLevelGroup): number {
  const groupLevels = dataLoader.getCachedGroupLevels(group.id);
  if (groupLevels) {
    return Math.min(group.levelCount, countSolvedInGroup(groupLevels, gameManager.getAllLevelStates()));
  }
  return Math.min(group.levelCount, countSavedCompletedInGroup(group));
}

function countSavedCompletedInGroup(group: RuntimeLevelGroup): number {
  const sortedGroupIds = levelGroups
    .map(levelGroup => levelGroup.id)
    .sort((a, b) => b.length - a.length);

  let solved = 0;
  for (const levelId of gameManager.getAllLevelStates().keys()) {
    if (!gameManager.isLevelMarkedComplete(levelId)) {
      continue;
    }
    if (inferGroupIdFromLevelId(levelId, sortedGroupIds) !== group.id) {
      continue;
    }
    solved += 1;
  }
  return solved;
}

function inferGroupIdFromLevelId(levelId: string, sortedGroupIds: string[]): string | null {
  for (const groupId of sortedGroupIds) {
    if (!levelId.startsWith(groupId)) {
      continue;
    }
    const suffix = levelId.slice(groupId.length);
    if (/^\d+$/.test(suffix)) {
      return groupId;
    }
  }
  return null;
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
    const isCurrentGroup = group.index === currentGroupIndex;
    const solved = groupSolvedLevels(group);
    const total = group.levelCount;
    button.textContent = `${group.id}\n${solved}/${total}`;
    if (isCurrentGroup) {
      button.classList.add('level-pack-item-current');
      button.setAttribute('aria-current', 'true');
    }
    if (total > 0 && solved >= total) {
      button.classList.add('level-pack-item-complete');
    } else if (solved > 0) {
      button.classList.add('level-pack-item-in-progress');
    } else {
      if (!isCurrentGroup) {
        button.classList.add('level-pack-item-unstarted');
      }
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
  stopTokenSwapAnimation();
  gameManager.toggleTokenOrder();
  clearSelection();
  render();
  runTokenSwapAnimation();
}

function runTokenSwapAnimation(): void {
  if (settings.disableSwapAnimation) {
    return;
  }

  stopTokenSwapAnimation();
  tokenSwapAnimationSequence += 1;
  const sequence = tokenSwapAnimationSequence;

  wheelEl.classList.remove('wheel-swapping');
  finalizeWheelTokenSwapAnimation();
  prepareWheelTokenSwapAnimation();
  void wheelEl.offsetWidth;
  wheelEl.classList.add('wheel-swapping');

  tokenSwapAnimationTimer = window.setTimeout(() => {
    if (sequence !== tokenSwapAnimationSequence) {
      return;
    }
    wheelEl.classList.remove('wheel-swapping');
    finalizeWheelTokenSwapAnimation();
    tokenSwapAnimationTimer = null;
  }, getTokenSwapAnimationMs());
}

function stopTokenSwapAnimation(): void {
  tokenSwapAnimationSequence += 1;
  if (tokenSwapAnimationTimer !== null) {
    window.clearTimeout(tokenSwapAnimationTimer);
    tokenSwapAnimationTimer = null;
  }
  wheelEl.classList.remove('wheel-swapping');
  finalizeWheelTokenSwapAnimation();
}

function getTokenSwapAnimationMs(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--token-swap-ms').trim();
  if (!raw) {
    return DEFAULT_TOKEN_SWAP_ANIMATION_MS;
  }
  if (raw.endsWith('ms')) {
    const value = Number.parseFloat(raw);
    return Number.isFinite(value) ? value : DEFAULT_TOKEN_SWAP_ANIMATION_MS;
  }
  if (raw.endsWith('s')) {
    const value = Number.parseFloat(raw);
    return Number.isFinite(value) ? value * 1000 : DEFAULT_TOKEN_SWAP_ANIMATION_MS;
  }
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : DEFAULT_TOKEN_SWAP_ANIMATION_MS;
}

function prepareWheelTokenSwapAnimation(): void {
  wheelEl.querySelectorAll<HTMLElement>('.wheel-letter').forEach((node) => {
    const finalToken = node.textContent?.trim() ?? '';
    if (finalToken.length < 2) {
      return;
    }

    const startToken = finalToken.split('').reverse().join('');
    if (startToken === finalToken) {
      return;
    }

    node.dataset.swapFinalToken = finalToken;
    node.textContent = '';
    node.classList.add('wheel-letter-swap-active');

    const layer = document.createElement('span');
    layer.className = 'wheel-letter-glyph-layer';

    for (let index = 0; index < startToken.length; index += 1) {
      const glyph = document.createElement('span');
      glyph.className = 'wheel-letter-glyph';
      glyph.textContent = startToken[index];
      layer.appendChild(glyph);
    }

    node.appendChild(layer);

    const finalMeasureLayer = document.createElement('span');
    finalMeasureLayer.className = 'wheel-letter-glyph-layer wheel-letter-glyph-layer-measure';
    for (let index = 0; index < finalToken.length; index += 1) {
      const glyph = document.createElement('span');
      glyph.className = 'wheel-letter-glyph';
      glyph.textContent = finalToken[index];
      finalMeasureLayer.appendChild(glyph);
    }
    node.appendChild(finalMeasureLayer);

    const glyphs = Array.from(layer.querySelectorAll<HTMLElement>('.wheel-letter-glyph'));
    const finalGlyphs = Array.from(finalMeasureLayer.querySelectorAll<HTMLElement>('.wheel-letter-glyph'));
    const startCenters = glyphs.map((glyph) => {
      const rect = glyph.getBoundingClientRect();
      return rect.left + rect.width / 2;
    });
    const finalCenters = finalGlyphs.map((glyph) => {
      const rect = glyph.getBoundingClientRect();
      return rect.left + rect.width / 2;
    });

    finalMeasureLayer.remove();

    for (let index = 0; index < glyphs.length; index += 1) {
      const targetCenter = finalCenters[glyphs.length - 1 - index];
      const shiftPx = targetCenter - startCenters[index];
      glyphs[index].style.setProperty('--swap-shift', `${shiftPx.toFixed(2)}px`);
    }
  });
}

function finalizeWheelTokenSwapAnimation(): void {
  wheelEl.querySelectorAll<HTMLElement>('.wheel-letter-swap-active').forEach((node) => {
    const finalToken = node.dataset.swapFinalToken ?? '';
    node.classList.remove('wheel-letter-swap-active');
    delete node.dataset.swapFinalToken;
    node.textContent = finalToken;
  });
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

  const revealed = buildRevealedCells(level, state.solved, state.revealedCells);

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

      cell.dataset.levelRow = String(levelRow);
      cell.dataset.levelCol = String(levelCol);

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
        if (revealLetterSelectionMode) {
          cell.classList.add('cell-reveal-target');
        }
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

function splitDefinitionChunks(definition: string): string[] {
  const chunks = definition
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk.length > 0);
  return chunks.length > 0 ? chunks : [definition.trim()];
}

function appendDefinitionSection(container: HTMLElement, definition: string): void {
  for (const item of splitDefinitionChunks(definition)) {
    const paragraph = document.createElement('p');
    paragraph.className = 'dictionary-definition';
    paragraph.textContent = item;
    container.appendChild(paragraph);
  }
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

  const orderedDefinitions: string[] = [];
  if (entry.definitions.wordnet) {
    orderedDefinitions.push(entry.definitions.wordnet);
  }
  if (entry.definitions.webster) {
    orderedDefinitions.push(entry.definitions.webster);
  }
  if (orderedDefinitions.length === 0 && definition.trim().length > 0) {
    orderedDefinitions.push(definition);
  }

  for (let index = 0; index < orderedDefinitions.length; index += 1) {
    const sourceDefinition = orderedDefinitions[index];
    if (!sourceDefinition) {
      continue;
    }
    appendDefinitionSection(dictionaryDefinitions, sourceDefinition);
    if (index < orderedDefinitions.length - 1) {
      const separator = document.createElement('hr');
      separator.className = 'settings-separator';
      dictionaryDefinitions.appendChild(separator);
    }
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

function enterRevealLetterSelectionMode(): void {
  if (revealLetterSelectionMode) {
    return;
  }

  const state = gameManager.getCurrentLevelState();
  if (!canRefreshHint(state)) {
    return;
  }

  revealModeFeedbackSnapshot = {
    text: feedbackText,
    trailingWord: feedbackWordText,
    toneClass: feedbackToneClass,
    lookupWord: feedbackLookupWord,
  };
  revealLetterSelectionMode = true;
  setFeedback('Choose an unrevealed cell...', 'good');
  render();
}

function cancelRevealLetterSelectionMode(): void {
  if (!revealLetterSelectionMode) {
    return;
  }

  revealLetterSelectionMode = false;
  restoreFeedbackSnapshot(revealModeFeedbackSnapshot);
  revealModeFeedbackSnapshot = null;
  render();
}

function restoreFeedbackSnapshot(snapshot: {
  text: string;
  trailingWord: string;
  toneClass: string;
  lookupWord: string;
} | null): void {
  previewingSelection = false;

  if (!snapshot) {
    clearFeedback();
    return;
  }

  feedbackText = snapshot.text;
  feedbackWordText = snapshot.trailingWord;
  feedbackToneClass = snapshot.toneClass;
  feedbackLookupWord = snapshot.lookupWord;
  renderFeedback(feedbackText, feedbackWordText);
  const splitClass = feedbackWordText ? ' feedback-split' : '';
  feedback.className = feedbackToneClass
    ? `feedback${splitClass} ${feedbackToneClass}`
    : `feedback${splitClass}`;
  refreshDictionaryButton();
}

function markRecentSolvedWords(words: string[]): void {
  const level = gameManager.getCurrentLevel();
  const solvedWords = new Set(words.map(normalizeWord));
  const solvedCells = new Set<string>();

  for (const answer of level.answers) {
    const normalized = normalizeWord(answer.text);
    if (!solvedWords.has(normalized)) {
      continue;
    }
    for (const [row, col] of answer.path) {
      solvedCells.add(cellKey(row, col));
    }
  }

  recentSolvedCells = solvedCells;
}

async function revealCellFromSelectionMode(row: number, col: number): Promise<void> {
  const state = gameManager.getCurrentLevelState();
  if (!canRefreshHint(state)) {
    cancelRevealLetterSelectionMode();
    return;
  }

  const revealResult = gameManager.revealCell(row, col);
  if (!revealResult.revealed) {
    cancelRevealLetterSelectionMode();
    return;
  }

  revealLetterSelectionMode = false;
  revealModeFeedbackSnapshot = null;
  clearCompletionSummaryCarryover();
  state.hints.hintRefreshCount += 1;

  if (revealResult.autoSolved.length > 0) {
    markRecentSolvedWords(revealResult.autoSolved);
    if (revealResult.autoSolved.length === 1) {
      setFeedback('Solved:', 'good', revealResult.autoSolved[0].toUpperCase());
    } else {
      setFeedback(`Solved ${revealResult.autoSolved.length} words.`, 'good');
    }
    void updatePersistentHint();
  } else {
    clearRecentSolvedCells();
    setFeedback('Letter revealed.', 'muted');
  }

  if (revealResult.levelComplete) {
    await completeCurrentLevel();
  }

  render();
  saveState();
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (!revealLetterSelectionMode) {
    return;
  }

  const target = event.target;
  const cell = target instanceof Element
    ? target.closest<HTMLElement>('.cell[data-level-row][data-level-col]')
    : null;

  if (!cell || !cell.classList.contains('cell-hidden')) {
    cancelRevealLetterSelectionMode();
    event.preventDefault();
    event.stopPropagation();
    return;
  }

  const row = Number(cell.dataset.levelRow);
  const col = Number(cell.dataset.levelCol);
  if (!Number.isInteger(row) || !Number.isInteger(col)) {
    cancelRevealLetterSelectionMode();
    event.preventDefault();
    event.stopPropagation();
    return;
  }

  void revealCellFromSelectionMode(row, col);
  event.preventDefault();
  event.stopPropagation();
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
    || !helpModal.hidden
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
  syncWheelSelectionClasses();
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

function syncWheelSelectionClasses(): void {
  const selected = new Set(activeSelection);
  const letters = wheelEl.querySelectorAll<HTMLElement>('.wheel-letter');
  letters.forEach((node, index) => {
    node.classList.toggle('selected', selected.has(index));
  });
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
  void persistState(payload);
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sanitizeStoredModalHintStack(raw: unknown): ModalHintEntry[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  const seenCanonicals = new Set<string>();
  const sanitized: ModalHintEntry[] = [];
  for (const rawEntry of raw) {
    if (!isRecord(rawEntry)) {
      continue;
    }

    const canonicalRaw = rawEntry.canonical;
    const textRaw = rawEntry.text;
    if (typeof canonicalRaw !== 'string' || typeof textRaw !== 'string') {
      continue;
    }

    const canonical = normalizeWord(canonicalRaw);
    const text = textRaw.trim();
    if (!canonical || !text || seenCanonicals.has(canonical)) {
      continue;
    }

    seenCanonicals.add(canonical);
    sanitized.push({ canonical, text });
    if (sanitized.length >= MAX_MODAL_HINT_STACK_SIZE) {
      break;
    }
  }

  return sanitized;
}

function sanitizeStoredHintRefreshCount(rawHints: Record<string, unknown>): number {
  const rawCount = rawHints.hintRefreshCount;
  if (typeof rawCount === 'number' && Number.isFinite(rawCount)) {
    const rounded = Math.floor(rawCount);
    return clamp(rounded, 0, MAX_HINT_REFRESHES_PER_LEVEL);
  }

  if (rawHints.hintRefreshUsed === true) {
    return 1;
  }

  return 0;
}

function sanitizeStoredRevealedCells(raw: unknown): string[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  const sanitized: string[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    if (typeof item !== 'string') {
      continue;
    }
    if (!/^\d+:\d+$/.test(item) || seen.has(item)) {
      continue;
    }
    seen.add(item);
    sanitized.push(item);
  }

  return sanitized;
}

function isStoredRevealedCellsSanitized(raw: unknown, sanitized: string[]): boolean {
  if (!Array.isArray(raw) || raw.length !== sanitized.length) {
    return false;
  }

  for (let index = 0; index < sanitized.length; index += 1) {
    if (raw[index] !== sanitized[index]) {
      return false;
    }
  }

  return true;
}

function isStoredModalHintStackSanitized(raw: unknown, sanitized: ModalHintEntry[]): boolean {
  if (!Array.isArray(raw) || raw.length !== sanitized.length) {
    return false;
  }

  for (let index = 0; index < sanitized.length; index += 1) {
    const rawEntry = raw[index];
    if (!isRecord(rawEntry)) {
      return false;
    }
    if (rawEntry.canonical !== sanitized[index].canonical || rawEntry.text !== sanitized[index].text) {
      return false;
    }
  }

  return true;
}

function migrateLoadedState(raw: unknown): { state: SavedGameState | null; didMigrate: boolean } {
  if (!isRecord(raw)) {
    return { state: null, didMigrate: false };
  }

  const currentGroupId = raw.currentGroupId;
  const currentIndexInGroup = raw.currentIndexInGroup;
  const levels = raw.levels;
  if (typeof currentGroupId !== 'string' || typeof currentIndexInGroup !== 'number' || !isRecord(levels)) {
    return { state: null, didMigrate: false };
  }

  let didMigrate = raw.schemaVersion !== GAME_STATE_SCHEMA_VERSION;
  const migratedLevels: SavedGameState['levels'] = {};
  for (const [levelId, rawLevelState] of Object.entries(levels)) {
    if (!isRecord(rawLevelState)) {
      didMigrate = true;
      continue;
    }

    const levelState = rawLevelState as Record<string, unknown>;

    const originalRevealedCells = levelState.revealedCells;
    const sanitizedRevealedCells = sanitizeStoredRevealedCells(originalRevealedCells);
    if (!isStoredRevealedCellsSanitized(originalRevealedCells, sanitizedRevealedCells)) {
      didMigrate = true;
    }
    if (sanitizedRevealedCells.length > 0) {
      levelState.revealedCells = sanitizedRevealedCells;
    } else if ('revealedCells' in levelState) {
      delete levelState.revealedCells;
      didMigrate = true;
    }

    const hints = isRecord(levelState.hints) ? levelState.hints : null;
    if (hints) {
      const sanitizedRefreshCount = sanitizeStoredHintRefreshCount(hints);
      if (hints.hintRefreshCount !== sanitizedRefreshCount) {
        didMigrate = true;
      }
      hints.hintRefreshCount = sanitizedRefreshCount;
      if ('hintRefreshUsed' in hints) {
        delete hints.hintRefreshUsed;
        didMigrate = true;
      }

      const originalStack = hints.modalHintStack;
      const sanitizedStack = sanitizeStoredModalHintStack(originalStack);
      if (!isStoredModalHintStackSanitized(originalStack, sanitizedStack)) {
        didMigrate = true;
      }
      hints.modalHintStack = sanitizedStack;
    }

    migratedLevels[levelId] = levelState as unknown as SavedGameState['levels'][string];
  }

  const migratedState: SavedGameState = {
    schemaVersion: GAME_STATE_SCHEMA_VERSION,
    currentGroupId,
    currentIndexInGroup,
    settings: isRecord(raw.settings) ? (raw.settings as Partial<SavedSettings>) : undefined,
    levels: migratedLevels,
  };

  return { state: migratedState, didMigrate };
}

async function loadState(): Promise<SavedGameState | null> {
  try {
    const raw = IS_ANDROID
      ? (await Preferences.get({ key: STORAGE_KEY })).value
      : localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    const { state, didMigrate } = migrateLoadedState(parsed);
    if (!state) {
      return null;
    }
    if (didMigrate) {
      await persistState(state);
    }
    return state;
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
    preferModernHints:
      typeof raw?.preferModernHints === 'boolean'
        ? raw.preferModernHints
        : DEFAULT_SETTINGS.preferModernHints,
    disableLetterRevealHint:
      typeof raw?.disableLetterRevealHint === 'boolean'
        ? raw.disableLetterRevealHint
        : DEFAULT_SETTINGS.disableLetterRevealHint,
    disableSwapAnimation:
      typeof raw?.disableSwapAnimation === 'boolean'
        ? raw.disableSwapAnimation
        : DEFAULT_SETTINGS.disableSwapAnimation,
  };
}

function applyTheme(): void {
  document.documentElement.setAttribute('data-theme', settings.theme);
  document.body.style.removeProperty('background-color');
}

function openSettingsActivity(): void {
  closeHelpModal(false);
  closeDictionaryModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);
  settingsActivity.hidden = false;
  menuButton.setAttribute('aria-expanded', 'true');
  closeMenuButton.focus();
}

function closeSettingsActivity(): void {
  closeResetProgressModal(false);
  settingsActivity.hidden = true;
  menuButton.setAttribute('aria-expanded', 'false');
}

function openHelpModal(): void {
  closeSettingsActivity();
  closeBonusModal(false);
  closeDictionaryModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);
  helpModal.hidden = false;
  helpButton.setAttribute('aria-expanded', 'true');
  closeHelpModalButton.focus();
}

function closeHelpModal(restoreFocus: boolean): void {
  if (helpModal.hidden) {
    return;
  }
  helpModal.hidden = true;
  helpButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) {
    helpButton.focus();
  }
}

function openLevelPackModal(): void {
  closeHelpModal(false);
  closeDictionaryModal(false);
  closeHintModal(false);
  closeRefreshHintModal(false);
  renderLevelPackModal();
  levelPackModal.hidden = false;
  levelPackButton.setAttribute('aria-expanded', 'true');
  const currentGroupButton = levelPackList.querySelector<HTMLButtonElement>('button[aria-current="true"]');
  if (currentGroupButton) {
    currentGroupButton.focus();
    return;
  }
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
  closeHelpModal(false);
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

  closeHelpModal(false);
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

async function getUnguessedWordHintForState(
  state: ActiveLevelState,
  excludedCanonicals: Set<string>,
  currentHintCanonical: string | null
): Promise<HintResult | null> {
  const level = gameManager.getCurrentLevel();
  const solvedWords = new Set(state.solved);
  const lookup = dataLoader.getDictionaryLookup();

  return sharedGetUnguessedWordHint(
    level,
    solvedWords,
    excludedCanonicals,
    currentHintCanonical,
    lookup,
    dataLoader.getDictionaryHintRelatedForms(),
    getDictionaryEntry,
    (letter) => dataLoader.loadDictionaryLetter(letter),
    settings.preferModernHints
  );
}

async function getUnguessedWordHint(): Promise<HintResult | null> {
  const state = gameManager.getCurrentLevelState();
  return getUnguessedWordHintForState(state, state.hints.excludedHintCanonicals, state.hints.currentHintCanonical);
}

function formatHintExcerptForDisplay(hint: HintResult): string {
  const e = hint.excerpt;
  return (e.truncatedStart ? '...' : '') + e.text + (e.truncatedEnd ? '...' : '');
}

function trackHintUsage(state: ActiveLevelState, canonical: string): void {
  state.hints.currentHintCanonical = canonical;

  if (!state.hints.hintedCanonicals.has(canonical)) {
    state.hints.hintedCanonicals.add(canonical);
    state.hints.hintCount += 1;
  }
}

function canRefreshHint(state: ActiveLevelState): boolean {
  return state.hints.hintRefreshCount < MAX_HINT_REFRESHES_PER_LEVEL;
}

function isLevelComplete(state: ActiveLevelState): boolean {
  const level = gameManager.getCurrentLevel();
  return state.solved.size >= level.answers.length;
}

function shouldDisableHintModalRefreshButton(state: ActiveLevelState): boolean {
  return !canRefreshHint(state) || isLevelComplete(state);
}

async function hasRefreshableWordHint(state: ActiveLevelState): Promise<boolean> {
  const currentCanonical = state.hints.currentHintCanonical;
  if (!currentCanonical) {
    return false;
  }

  const excludedCanonicals = new Set(state.hints.excludedHintCanonicals);
  excludedCanonicals.add(currentCanonical);
  const hint = await getUnguessedWordHintForState(state, excludedCanonicals, null);
  return hint !== null;
}

function renderRefreshHintNoMoreMessage(show: boolean): void {
  refreshHintNote.hidden = !show;
}

function remainingHintRefreshes(state: ActiveLevelState): number {
  return clamp(MAX_HINT_REFRESHES_PER_LEVEL - state.hints.hintRefreshCount, 0, MAX_HINT_REFRESHES_PER_LEVEL);
}

function updateRefreshHintSubtitle(state: ActiveLevelState): void {
  refreshHintSubtitle.textContent = `Refreshes available this level: ${remainingHintRefreshes(state)}`;
}

function getCurrentLevelModalHintEntries(state: ActiveLevelState): ModalHintEntry[] {
  const level = gameManager.getCurrentLevel();
  const lookup = dataLoader.getDictionaryLookup();
  const existing = state.hints.modalHintStack;
  const activeEntries = existing.filter((entry) =>
    canonicalHasUnsolvedWords(level, state.solved, lookup, entry.canonical)
  );

  if (activeEntries.length === 0) {
    state.hints.modalHintStack = [];
    return [];
  }

  if (activeEntries.length !== existing.length) {
    state.hints.modalHintStack = activeEntries;
  }

  return activeEntries;
}

function setCurrentLevelModalHintEntries(state: ActiveLevelState, entries: ModalHintEntry[]): ModalHintEntry[] {
  if (entries.length === 0) {
    state.hints.modalHintStack = [];
    return [];
  }

  const limitedEntries = entries.slice(0, MAX_MODAL_HINT_STACK_SIZE);
  state.hints.modalHintStack = limitedEntries;
  return limitedEntries;
}

function prependCurrentLevelModalHintEntry(state: ActiveLevelState, entry: ModalHintEntry): ModalHintEntry[] {
  const existingEntries = getCurrentLevelModalHintEntries(state).filter(
    (existing) => existing.canonical !== entry.canonical
  );
  return setCurrentLevelModalHintEntries(state, [entry, ...existingEntries]);
}

function renderHintModalEntries(primaryHintText: string, olderEntries: ModalHintEntry[] = []): void {
  const visibleOlderEntries = olderEntries.slice(0, Math.max(0, MAX_MODAL_HINT_STACK_SIZE - 1));
  const textEntries = [primaryHintText, ...visibleOlderEntries.map((entry) => entry.text)];

  hintTextStack.replaceChildren();
  for (let index = 0; index < textEntries.length; index += 1) {
    if (index > 0) {
      const separator = document.createElement('hr');
      separator.className = 'settings-separator';
      hintTextStack.append(separator);
    }

    const hintTextEl = document.createElement('p');
    hintTextEl.className = 'hint-text';
    hintTextEl.textContent = textEntries[index];
    hintTextStack.append(hintTextEl);
  }
}

async function updatePersistentHint(): Promise<void> {
  if (!settings.alwaysShowHint) {
    persistentHintEl.hidden = true;
    return;
  }

  const state = gameManager.getCurrentLevelState();
  const hint = await getUnguessedWordHint();
  if (!hint) {
    state.hints.currentHintCanonical = null;
    persistentHintEl.hidden = true;
    return;
  }

  trackHintUsage(state, hint.canonical);
  persistentHintEl.textContent = formatHintExcerptForDisplay(hint);
  persistentHintEl.hidden = false;
  saveState();
}

async function openHintModal(): Promise<void> {
  closeHelpModal(false);
  closeBonusModal(false);
  closeDictionaryModal(false);
  closeRefreshHintModal(false);
  closeLevelPackModal(false);

  const state = gameManager.getCurrentLevelState();
  const existingModalHints = getCurrentLevelModalHintEntries(state);
  const hint = await getUnguessedWordHint();
  if (!hint) {
    state.hints.currentHintCanonical = null;
    renderHintModalEntries(NO_HINTS_AVAILABLE_TEXT, existingModalHints);
    modalRefreshHintButton.disabled = shouldDisableHintModalRefreshButton(state);
    hintModal.hidden = false;
    hintButton.setAttribute('aria-expanded', 'true');
    closeHintModalButton.focus();
    return;
  }

  trackHintUsage(state, hint.canonical);
  const stackedHints = prependCurrentLevelModalHintEntry(state, {
    canonical: hint.canonical,
    text: formatHintExcerptForDisplay(hint),
  });
  renderHintModalEntries(stackedHints[0].text, stackedHints.slice(1));

  modalRefreshHintButton.disabled = shouldDisableHintModalRefreshButton(state);

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

async function openRefreshHintModal(): Promise<void> {
  const state = gameManager.getCurrentLevelState();
  const canRefresh = canRefreshHint(state);
  const checkSequence = ++refreshHintModalCheckSequence;
  updateRefreshHintSubtitle(state);
  renderRefreshHintNoMoreMessage(false);
  closeHintModal(false);
  refreshHintActions.hidden = false;
  refreshHintModal.hidden = false;
  modalRefreshHintButton.setAttribute('aria-expanded', 'true');
  confirmRefreshHintButton.disabled = !canRefresh;
  revealLetterHintButton.hidden = settings.disableLetterRevealHint;
  revealLetterHintButton.disabled = settings.disableLetterRevealHint || !canRefresh;
  cancelRefreshHintButton.focus();

  if (!canRefresh) {
    return;
  }

  const noMoreHints = !(await hasRefreshableWordHint(state));
  if (checkSequence !== refreshHintModalCheckSequence || refreshHintModal.hidden) {
    return;
  }

  confirmRefreshHintButton.disabled = noMoreHints;
  renderRefreshHintNoMoreMessage(noMoreHints);
}

function closeRefreshHintModal(returnToHint: boolean): void {
  refreshHintModalCheckSequence += 1;
  if (refreshHintModal.hidden) {
    return;
  }

  refreshHintModal.hidden = true;
  renderRefreshHintNoMoreMessage(false);
  modalRefreshHintButton.setAttribute('aria-expanded', 'false');
  if (returnToHint) {
    hintModal.hidden = false;
    hintButton.setAttribute('aria-expanded', 'true');
    closeHintModalButton.focus();
  }
}

async function refreshHint(): Promise<void> {
  const state = gameManager.getCurrentLevelState();

  if (!canRefreshHint(state) || !state.hints.currentHintCanonical) {
    return;
  }

  state.hints.excludedHintCanonicals.add(state.hints.currentHintCanonical);
  state.hints.hintRefreshCount += 1;
  state.hints.currentHintCanonical = null;

  const existingModalHints = getCurrentLevelModalHintEntries(state);
  const newHint = await getUnguessedWordHint();
  if (!newHint) {
    renderHintModalEntries(NO_HINTS_AVAILABLE_TEXT, existingModalHints);
    persistentHintEl.hidden = true;
    modalRefreshHintButton.disabled = shouldDisableHintModalRefreshButton(state);
    hintModal.hidden = false;
    hintButton.setAttribute('aria-expanded', 'true');
    closeHintModalButton.focus();
    saveState();
    return;
  }

  trackHintUsage(state, newHint.canonical);
  const stackedHints = prependCurrentLevelModalHintEntry(state, {
    canonical: newHint.canonical,
    text: formatHintExcerptForDisplay(newHint),
  });
  renderHintModalEntries(stackedHints[0].text, stackedHints.slice(1));
  if (settings.alwaysShowHint) {
    persistentHintEl.textContent = stackedHints[0].text;
  }

  modalRefreshHintButton.disabled = shouldDisableHintModalRefreshButton(state);
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
  const previousGroupId = gameManager.getCurrentGroupId();
  const previousIndexInGroup = gameManager.getCurrentIndexInGroup();
  const previousTokenOrderMode = gameManager.getTokenOrderMode();
  const result = gameManager.advanceToNextLevel();
  if (!result.advanced) {
    return false;
  }

  try {
    if (result.needsGroupLoad && result.nextGroupId) {
      await ensureGroupLoaded(result.nextGroupId);
    }
    return true;
  } catch {
    gameManager.jumpToLevel(previousGroupId, previousIndexInGroup);
    gameManager.setTokenOrderMode(previousTokenOrderMode);
    return false;
  }
}

async function jumpToLevelEnsuringLoaded(groupId: string, indexInGroup: number): Promise<boolean> {
  const previousGroupId = gameManager.getCurrentGroupId();
  const previousIndexInGroup = gameManager.getCurrentIndexInGroup();
  const previousTokenOrderMode = gameManager.getTokenOrderMode();
  const result = gameManager.jumpToLevel(groupId, indexInGroup);
  if (!result.jumped) {
    return false;
  }

  try {
    await ensureGroupLoaded(groupId);
    return true;
  } catch {
    gameManager.jumpToLevel(previousGroupId, previousIndexInGroup);
    gameManager.setTokenOrderMode(previousTokenOrderMode);
    return false;
  }
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

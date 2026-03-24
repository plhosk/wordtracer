import { type Level, type LevelGroupDefinition, type TokenOrderMode, type LevelWalls, type LevelAnswer, getLetterAt } from './types.js';

export type WordResult =
  | 'solved'
  | 'already-solved'
  | 'bonus'
  | 'already-bonus'
  | 'wrong-direction'
  | 'not-spellable'
  | 'not-accepted';

export interface SavedModalHintEntry {
  canonical: string;
  text: string;
}

export interface HintState {
  hintedCanonicals: Set<string>;
  excludedHintCanonicals: Set<string>;
  hintCount: number;
  hintRefreshCount: number;
  currentHintCanonical: string | null;
  modalHintStack: SavedModalHintEntry[];
}

export interface LevelState {
  solved: Set<string>;
  bonus: Set<string>;
  revealedCells: Set<string>;
  hints: HintState;
}

export interface SavedHintState {
  hintedCanonicals?: string[];
  excludedHintCanonicals?: string[];
  hintCount?: number;
  hintRefreshCount?: number;
  hintRefreshUsed?: boolean;
  currentHintCanonical?: string | null;
  modalHintStack?: SavedModalHintEntry[];
}

export interface SavedLevelState {
  solved: string[];
  bonus: string[];
  revealedCells?: string[];
  hints?: SavedHintState;
  completed?: boolean;
}

export interface SavedSettings {
  autoAdvance: boolean;
  theme: 'dark' | 'light';
  alwaysShowHint: boolean;
  preferModernHints: boolean;
  disableLetterRevealHint: boolean;
  disableSwapAnimation: boolean;
}

export interface SavedGameState {
  schemaVersion: number;
  currentGroupId: string;
  currentIndexInGroup: number;
  settings?: Partial<SavedSettings>;
  levels: Record<string, SavedLevelState>;
}

export interface GridStrings {
  rows: string[];
  cols: string[];
}

export interface RuntimeLevelGroup {
  id: string;
  index: number;
  wheelSize?: number;
  levelCount: number;
}

export interface SubmitWordResult {
  result: WordResult;
  solvedCells: Array<[number, number]>;
  autoSolved: string[];
  levelComplete: boolean;
  completionMessage?: string;
}

export interface RevealCellResult {
  revealed: boolean;
  autoSolved: string[];
  levelComplete: boolean;
}

export interface GridCell {
  row: number;
  col: number;
  revealed: boolean;
  letter: string | null;
  isWordStart: boolean;
}

export interface GridBounds {
  minRow: number;
  maxRow: number;
  minCol: number;
  maxCol: number;
}

export interface GridState {
  rows: number;
  cols: number;
  bounds: GridBounds;
  cells: GridCell[];
  walls: LevelWalls;
}

export const DEFAULT_MIN_SWIPE_LENGTH = 3;
export const REQUIRED_SCHEMA_VERSION = 5;
export const GAME_STATE_SCHEMA_VERSION = 2;
export const MAX_HINT_REFRESHES_PER_LEVEL = 3;
export const DEFAULT_TOKEN_ORDER_MODE: TokenOrderMode = 'forward';
export const DEFAULT_SETTINGS: SavedSettings = {
  autoAdvance: false,
  theme: 'dark',
  alwaysShowHint: false,
  preferModernHints: false,
  disableLetterRevealHint: false,
  disableSwapAnimation: false,
};

export function normalizeWord(word: string): string {
  return word.trim().toLowerCase();
}

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function displayToken(token: string, mode: TokenOrderMode): string {
  if (mode === 'reverse' && token.length >= 2) {
    return token.split('').reverse().join('');
  }
  return token;
}

export function answerAllowedModes(
  answer: Level['answers'][number],
  defaultMode: TokenOrderMode = DEFAULT_TOKEN_ORDER_MODE
): TokenOrderMode[] {
  const modes = answer.allowedModes ?? [defaultMode];
  return modes.length > 0 ? modes : [defaultMode];
}

export function cellKey(row: number, col: number): string {
  return `${row}:${col}`;
}

export function canSpellWithTokens(word: string, tokens: string[]): boolean {
  const normalized = normalizeWord(word);

  function matchFrom(position: number, used: Set<number>): boolean {
    if (position === normalized.length) {
      return true;
    }

    for (let i = 0; i < tokens.length; i++) {
      if (used.has(i)) continue;

      const token = normalizeWord(tokens[i]);
      if (normalized.slice(position, position + token.length) === token) {
        used.add(i);
        if (matchFrom(position + token.length, used)) {
          return true;
        }
        used.delete(i);
      }
    }

    return false;
  }

  return matchFrom(0, new Set());
}

export function getTokensForMode(letterWheel: string[], mode: TokenOrderMode): string[] {
  if (mode === 'forward') {
    return letterWheel;
  }
  return letterWheel.map((t) => (t.length >= 2 ? t.split('').reverse().join('') : t));
}

export function createEmptyLevelState(): LevelState {
  return {
    solved: new Set(),
    bonus: new Set(),
    revealedCells: new Set(),
    hints: {
      hintedCanonicals: new Set(),
      excludedHintCanonicals: new Set(),
      hintCount: 0,
      hintRefreshCount: 0,
      currentHintCanonical: null,
      modalHintStack: [],
    },
  };
}

function sanitizeHintRefreshCount(savedHints: SavedHintState | undefined): number {
  const rawCount = savedHints?.hintRefreshCount;
  if (typeof rawCount === 'number' && Number.isFinite(rawCount)) {
    return Math.max(0, Math.floor(rawCount));
  }
  return savedHints?.hintRefreshUsed ? 1 : 0;
}

function sanitizeModalHintStack(entries: SavedHintState['modalHintStack']): SavedModalHintEntry[] {
  if (!entries || entries.length === 0) {
    return [];
  }

  const seenCanonicals = new Set<string>();
  const sanitized: SavedModalHintEntry[] = [];
  for (const entry of entries) {
    if (!entry) {
      continue;
    }
    const canonical = normalizeWord(entry.canonical ?? '');
    const text = typeof entry.text === 'string' ? entry.text.trim() : '';
    if (!canonical || !text || seenCanonicals.has(canonical)) {
      continue;
    }
    seenCanonicals.add(canonical);
    sanitized.push({ canonical, text });
  }
  return sanitized;
}

function sanitizeRevealedCells(cells: SavedLevelState['revealedCells']): Set<string> {
  if (!cells || cells.length === 0) {
    return new Set<string>();
  }

  const sanitized = new Set<string>();
  for (const key of cells) {
    if (typeof key !== 'string') {
      continue;
    }
    if (!/^\d+:\d+$/.test(key)) {
      continue;
    }
    sanitized.add(key);
  }
  return sanitized;
}

export function hydrateLevelState(saved: SavedLevelState): LevelState {
  return {
    solved: new Set(saved.solved.map(normalizeWord)),
    bonus: new Set(saved.bonus.map(normalizeWord)),
    revealedCells: sanitizeRevealedCells(saved.revealedCells),
    hints: {
      hintedCanonicals: new Set(saved.hints?.hintedCanonicals?.map(normalizeWord) ?? []),
      excludedHintCanonicals: new Set(saved.hints?.excludedHintCanonicals?.map(normalizeWord) ?? []),
      hintCount: saved.hints?.hintCount ?? 0,
      hintRefreshCount: sanitizeHintRefreshCount(saved.hints),
      currentHintCanonical: saved.hints?.currentHintCanonical ?? null,
      modalHintStack: sanitizeModalHintStack(saved.hints?.modalHintStack),
    },
  };
}

export function serializeLevelState(state: LevelState, completed?: boolean): SavedLevelState {
  const hasHintData = 
    state.hints.hintCount > 0 || 
    state.hints.hintRefreshCount > 0 ||
    state.hints.excludedHintCanonicals.size > 0 || 
    state.hints.currentHintCanonical !== null ||
    state.hints.modalHintStack.length > 0;

  const serialized: SavedLevelState = {
    solved: [...state.solved],
    bonus: [...state.bonus],
    revealedCells: state.revealedCells.size > 0 ? [...state.revealedCells] : undefined,
    hints: hasHintData ? {
      hintedCanonicals: [...state.hints.hintedCanonicals],
      excludedHintCanonicals: [...state.hints.excludedHintCanonicals],
      hintCount: state.hints.hintCount,
      hintRefreshCount: state.hints.hintRefreshCount,
      currentHintCanonical: state.hints.currentHintCanonical,
      modalHintStack: state.hints.modalHintStack.map((entry) => ({
        canonical: normalizeWord(entry.canonical),
        text: entry.text,
      })),
    } : undefined,
  };

  if (completed === true) {
    serialized.completed = true;
  }

  return serialized;
}

export function buildOccupiedCells(level: Level): Set<string> {
  const occupied = new Set<string>();
  for (const answer of level.answers) {
    for (const [row, col] of answer.path) {
      occupied.add(cellKey(row, col));
    }
  }
  return occupied;
}

export function buildRevealedCells(
  level: Level,
  solved: Set<string>,
  revealedCells: Set<string> = new Set()
): Set<string> {
  const revealed = new Set<string>();
  for (const answer of level.answers) {
    if (!solved.has(normalizeWord(answer.text))) {
      continue;
    }
    for (const [row, col] of answer.path) {
      revealed.add(cellKey(row, col));
    }
  }
  for (const key of revealedCells) {
    revealed.add(key);
  }
  return revealed;
}

export function isLevelComplete(level: Level, solved: Set<string>): boolean {
  for (const answer of level.answers) {
    if (!solved.has(normalizeWord(answer.text))) {
      return false;
    }
  }
  return true;
}

export function minSwipeLength(level: Level): number {
  const lengths = level.answers.map((answer) => answer.text.length).filter((len) => len > 0);
  if (!lengths.length) {
    return DEFAULT_MIN_SWIPE_LENGTH;
  }
  return Math.max(1, Math.min(DEFAULT_MIN_SWIPE_LENGTH, Math.min(...lengths)));
}

export function autoSolveFullyRevealedAnswers(level: Level, state: LevelState): number {
  let added = 0;
  let changed = true;
  while (changed) {
    changed = false;
    const revealed = buildRevealedCells(level, state.solved, state.revealedCells);
    for (const answer of level.answers) {
      const word = normalizeWord(answer.text);
      if (state.solved.has(word)) {
        continue;
      }
      const fullyRevealed = answer.path.every(([row, col]) => revealed.has(cellKey(row, col)));
      if (!fullyRevealed) {
        continue;
      }
      state.solved.add(word);
      added += 1;
      changed = true;
    }
  }
  return added;
}

export function revealCell(level: Level, state: LevelState, row: number, col: number): RevealCellResult {
  const target = cellKey(row, col);
  const occupied = buildOccupiedCells(level);
  if (!occupied.has(target)) {
    return {
      revealed: false,
      autoSolved: [],
      levelComplete: isLevelComplete(level, state.solved),
    };
  }

  const currentlyRevealed = buildRevealedCells(level, state.solved, state.revealedCells);
  if (currentlyRevealed.has(target)) {
    return {
      revealed: false,
      autoSolved: [],
      levelComplete: isLevelComplete(level, state.solved),
    };
  }

  const solvedBefore = new Set(state.solved);
  state.revealedCells.add(target);
  autoSolveFullyRevealedAnswers(level, state);

  const autoSolved: string[] = [];
  for (const answer of level.answers) {
    const normalized = normalizeWord(answer.text);
    if (!solvedBefore.has(normalized) && state.solved.has(normalized)) {
      autoSolved.push(normalized);
    }
  }

  return {
    revealed: true,
    autoSolved,
    levelComplete: isLevelComplete(level, state.solved),
  };
}

export function submitWord(
  word: string,
  level: Level,
  state: LevelState,
  tokenOrderMode: TokenOrderMode = DEFAULT_TOKEN_ORDER_MODE
): SubmitWordResult {
  const normalizedWord = normalizeWord(word);

  const forwardTokens = getTokensForMode(level.letterWheel, 'forward');
  const reverseTokens = getTokensForMode(level.letterWheel, 'reverse');
  const canSpellForward = canSpellWithTokens(normalizedWord, forwardTokens);
  const canSpellReverse = canSpellWithTokens(normalizedWord, reverseTokens);

  const canSpellCurrent =
    tokenOrderMode === 'forward' ? canSpellForward : canSpellReverse;
  const canSpellOther =
    tokenOrderMode === 'forward' ? canSpellReverse : canSpellForward;

  if (!canSpellCurrent && canSpellOther) {
    return {
      result: 'wrong-direction',
      solvedCells: [],
      autoSolved: [],
      levelComplete: false,
    };
  }

  if (!canSpellCurrent && !canSpellOther) {
    return {
      result: 'not-spellable',
      solvedCells: [],
      autoSolved: [],
      levelComplete: false,
    };
  }

  const matchingAnswer = level.answers.find((answer) => {
    if (normalizeWord(answer.text) !== normalizedWord) {
      return false;
    }
    return answerAllowedModes(answer).includes(tokenOrderMode);
  });

  if (matchingAnswer) {
    if (state.solved.has(normalizedWord)) {
      return {
        result: 'already-solved',
        solvedCells: [],
        autoSolved: [],
        levelComplete: false,
      };
    }

    state.solved.add(normalizedWord);
    const solvedCells = matchingAnswer.path;

    const autoSolved: string[] = [];
    autoSolveFullyRevealedAnswers(level, state);
    for (const answer of level.answers) {
      const w = normalizeWord(answer.text);
      if (w !== normalizedWord && state.solved.has(w)) {
        autoSolved.push(w);
      }
    }

    const levelComplete = isLevelComplete(level, state.solved);

    return {
      result: 'solved',
      solvedCells,
      autoSolved,
      levelComplete,
      completionMessage: levelComplete ? formatCompletionSummary(state) : undefined,
    };
  }

  const bonusSet = new Set(level.bonusWords.map(normalizeWord));

  if (bonusSet.has(normalizedWord)) {
    if (state.bonus.has(normalizedWord)) {
      return {
        result: 'already-bonus',
        solvedCells: [],
        autoSolved: [],
        levelComplete: false,
      };
    }
    state.bonus.add(normalizedWord);
    return {
      result: 'bonus',
      solvedCells: [],
      autoSolved: [],
      levelComplete: false,
    };
  }

  return {
    result: 'not-accepted',
    solvedCells: [],
    autoSolved: [],
    levelComplete: false,
  };
}

export function buildRuntimeGroupsFromDefinitions(
  groupDefinitions: LevelGroupDefinition[]
): RuntimeLevelGroup[] {
  const groupsFromDefinitions: RuntimeLevelGroup[] = [];
  const seenGroupIndices = new Set<number>();

  for (const group of groupDefinitions) {
    const id = group.id.trim();
    if (!id) {
      throw new Error('Group definition has no id');
    }
    if (!Number.isInteger(group.index) || group.index < 0) {
      throw new Error(`Group definition ${id} has invalid index`);
    }
    if (seenGroupIndices.has(group.index)) {
      throw new Error(`Group definition has duplicate group index ${group.index}`);
    }
    seenGroupIndices.add(group.index);
    if (!Number.isInteger(group.wheelSize) || group.wheelSize <= 0) {
      throw new Error(`Group definition ${id} has invalid wheelSize`);
    }

    groupsFromDefinitions.push({
      id,
      index: group.index,
      wheelSize: group.wheelSize,
      levelCount: group.levelCount,
    });
  }

  groupsFromDefinitions.sort((a, b) => a.index - b.index);
  return groupsFromDefinitions;
}

export function computeBoardSize(allLevels: Level[]): { rows: number; cols: number } {
  let rows = 1;
  let cols = 1;
  for (const level of allLevels) {
    rows = Math.max(rows, level.rows);
    cols = Math.max(cols, level.cols);
  }
  return { rows, cols };
}

export function computeOccupiedBounds(level: Level): GridBounds {
  let minRow = Infinity;
  let maxRow = -Infinity;
  let minCol = Infinity;
  let maxCol = -Infinity;

  for (const answer of level.answers) {
    for (const [row, col] of answer.path) {
      minRow = Math.min(minRow, row);
      maxRow = Math.max(maxRow, row);
      minCol = Math.min(minCol, col);
      maxCol = Math.max(maxCol, col);
    }
  }

  if (minRow === Infinity) {
    return { minRow: 0, maxRow: 0, minCol: 0, maxCol: 0 };
  }

  return { minRow, maxRow, minCol, maxCol };
}

export function buildGridState(
  level: Level,
  solvedWords: Set<string>,
  revealedCells: Set<string> = new Set()
): GridState {
  const occupied = buildOccupiedCells(level);
  const revealed = buildRevealedCells(level, solvedWords, revealedCells);
  const bounds = computeOccupiedBounds(level);

  const wordStarts = new Set<string>();
  for (const answer of level.answers) {
    const normalizedText = normalizeWord(answer.text);
    if (!solvedWords.has(normalizedText) && answer.path.length > 0) {
      const [startRow, startCol] = answer.path[0];
      wordStarts.add(`${startRow}:${startCol}`);
    }
  }

  const cells: GridCell[] = [];
  for (const key of occupied) {
    const [rowStr, colStr] = key.split(':');
    const row = parseInt(rowStr, 10);
    const col = parseInt(colStr, 10);
    const isRevealed = revealed.has(key);
    const letter = isRevealed ? getLetterAt(level, row, col) : null;
    cells.push({
      row,
      col,
      revealed: isRevealed,
      letter: letter?.toUpperCase() ?? null,
      isWordStart: wordStarts.has(key),
    });
  }

  cells.sort((a, b) => {
    if (a.row !== b.row) return a.row - b.row;
    return a.col - b.col;
  });

  return {
    rows: level.rows,
    cols: level.cols,
    bounds,
    cells,
    walls: level.walls,
  };
}

export interface AllGridStrings {
  current: GridStrings;
  start: GridStrings;
}

export function buildAllGridStrings(
  rows: number,
  cols: number,
  answers: LevelAnswer[],
  solvedWords: Set<string>,
  revealedCells: Set<string> = new Set()
): AllGridStrings {
  const allOccupied = new Set<string>();
  const allWordStarts = new Set<string>();
  const letterByCell = new Map<string, string>();
  
  for (const answer of answers) {
    if (answer.path.length > 0) {
      const [startRow, startCol] = answer.path[0];
      allWordStarts.add(`${startRow}:${startCol}`);
    }
    for (let i = 0; i < answer.path.length; i += 1) {
      const [row, col] = answer.path[i];
      const key = `${row}:${col}`;
      allOccupied.add(key);
      if (!letterByCell.has(key)) {
        letterByCell.set(key, answer.text[i]?.toUpperCase() ?? '');
      }
    }
  }
  
  const revealedLetters = new Map<string, string>();
  const currentWordStarts = new Set<string>();
  
  for (const answer of answers) {
    const normalizedText = normalizeWord(answer.text);
    const isSolved = solvedWords.has(normalizedText);
    
    if (answer.path.length > 0 && !isSolved) {
      const [startRow, startCol] = answer.path[0];
      currentWordStarts.add(`${startRow}:${startCol}`);
    }
    
    if (isSolved) {
      for (let i = 0; i < answer.path.length; i++) {
        const [row, col] = answer.path[i];
        const key = `${row}:${col}`;
        revealedLetters.set(key, answer.text[i].toUpperCase());
      }
    }
  }

  for (const key of revealedCells) {
    if (!allOccupied.has(key) || revealedLetters.has(key)) {
      continue;
    }
    const letter = letterByCell.get(key);
    if (letter) {
      revealedLetters.set(key, letter);
    }
  }
  
  return {
    start: buildGridStringsFromSets(rows, cols, allOccupied, allWordStarts, new Map()),
    current: buildGridStringsFromSets(rows, cols, allOccupied, currentWordStarts, revealedLetters),
  };
}

function buildGridStringsFromSets(
  rows: number,
  cols: number,
  occupiedCells: Set<string>,
  wordStartPositions: Set<string>,
  revealedLetters: Map<string, string>
): GridStrings {
  const getCellChar = (row: number, col: number): string => {
    const key = `${row}:${col}`;
    if (!occupiedCells.has(key)) return ' ';
    if (revealedLetters.has(key)) return revealedLetters.get(key)!;
    if (wordStartPositions.has(key)) return '*';
    return '.';
  };
  
  const gridRows: string[] = [];
  for (let rowIdx = 0; rowIdx < rows; rowIdx++) {
    let rowStr = '';
    for (let colIdx = 0; colIdx < cols; colIdx++) {
      rowStr += getCellChar(rowIdx, colIdx);
    }
    gridRows.push(rowStr);
  }
  
  const gridCols: string[] = [];
  for (let colIdx = 0; colIdx < cols; colIdx++) {
    let colStr = '';
    for (let rowIdx = 0; rowIdx < rows; rowIdx++) {
      colStr += getCellChar(rowIdx, colIdx);
    }
    gridCols.push(colStr);
  }
  
  return { rows: gridRows, cols: gridCols };
}

export interface WordStart {
  pos: [number, number];
  dir: 'down' | 'right';
  len: number;
}

export function extractWordStarts(answers: LevelAnswer[]): WordStart[] {
  return answers.map((answer) => {
    const [startRow, startCol] = answer.path[0];
    let dir: 'down' | 'right' = 'right';
    if (answer.path.length > 1) {
      const [nextRow] = answer.path[1];
      dir = nextRow !== startRow ? 'down' : 'right';
    }
    return {
      pos: [startRow, startCol] as [number, number],
      dir,
      len: answer.path.length,
    };
  }).sort((a, b) => {
    if (a.pos[0] !== b.pos[0]) return a.pos[0] - b.pos[0];
    return a.pos[1] - b.pos[1];
  });
}

export function buildLevelName(level: Level): string {
  return `${level.groupId ?? ''}${(level.indexInGroup ?? 0) + 1}`;
}

export function findGroupById(
  groups: RuntimeLevelGroup[],
  groupId: string
): { group: RuntimeLevelGroup; groupIndex: number } | null {
  for (let groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
    if (groups[groupIndex].id === groupId) {
      return { group: groups[groupIndex], groupIndex };
    }
  }
  return null;
}

export function countSolvedInGroup(
  groupLevels: Level[],
  levelStates: Map<string, LevelState>
): number {
  let solved = 0;
  for (const level of groupLevels) {
    const state = levelStates.get(level.id);
    if (state && isLevelComplete(level, state.solved)) {
      solved += 1;
    }
  }
  return solved;
}

export function findFirstUnfinishedInGroup(
  groupLevels: Level[],
  levelStates: Map<string, LevelState>
): number {
  for (let indexInGroup = 0; indexInGroup < groupLevels.length; indexInGroup += 1) {
    const level = groupLevels[indexInGroup];
    const state = levelStates.get(level.id);
    if (!state || !isLevelComplete(level, state.solved)) {
      return indexInGroup;
    }
  }
  return 0;
}

export function formatCompletionSummary(state: LevelState): string {
  let base = `Level complete - ${state.solved.size} words`;
  if (state.bonus.size > 0) {
    base = `${base}, ${state.bonus.size} bonus`;
  }
  if (state.hints.hintCount > 0) {
    base = `${base}, ${state.hints.hintCount} hint${state.hints.hintCount !== 1 ? 's' : ''} used`;
  }
  return base;
}

export class GameStateManager {
  private levelStates: Map<string, LevelState> = new Map();
  private completedLevelIds: Set<string> = new Set();
  private currentGroupId: string;
  private currentIndexInGroup: number;
  private tokenOrderMode: TokenOrderMode;
  private groupLevels: Map<string, Level[]> = new Map();
  private groupDefinitions: LevelGroupDefinition[];
  
  constructor(
    groupDefinitions: LevelGroupDefinition[],
    initialGroupId: string,
    initialLevels: Level[],
    initialState?: {
      levelStates?: Map<string, LevelState>;
      completedLevelIds?: Set<string>;
      tokenOrderMode?: TokenOrderMode;
      currentGroupId?: string;
      currentIndexInGroup?: number;
    }
  ) {
    this.groupDefinitions = groupDefinitions;
    this.groupLevels.set(initialGroupId, initialLevels);
    this.currentGroupId = initialState?.currentGroupId ?? initialGroupId;
    this.currentIndexInGroup = initialState?.currentIndexInGroup ?? 0;
    this.tokenOrderMode = initialState?.tokenOrderMode ?? DEFAULT_TOKEN_ORDER_MODE;
    
    if (initialState?.levelStates) {
      this.levelStates = initialState.levelStates;
    }
    if (initialState?.completedLevelIds) {
      this.completedLevelIds = initialState.completedLevelIds;
    }
  }

  setGroupLevels(groupId: string, levels: Level[]): void {
    this.groupLevels.set(groupId, levels);
  }

  hasGroupLoaded(groupId: string): boolean {
    return this.groupLevels.has(groupId);
  }
  
  getCurrentLevel(): Level {
    const levels = this.groupLevels.get(this.currentGroupId);
    if (!levels || levels.length === 0) {
      throw new Error(`No levels loaded for group ${this.currentGroupId}`);
    }
    return levels[this.currentIndexInGroup] ?? levels[0];
  }

  getCurrentGroupId(): string {
    return this.currentGroupId;
  }

  getCurrentIndexInGroup(): number {
    return this.currentIndexInGroup;
  }

  getCurrentGroupLevels(): Level[] {
    return this.groupLevels.get(this.currentGroupId) ?? [];
  }
  
  getLevelState(levelId: string): LevelState {
    let state = this.levelStates.get(levelId);
    if (!state) {
      state = createEmptyLevelState();
      this.levelStates.set(levelId, state);
    }
    return state;
  }
  
  getCurrentLevelState(): LevelState {
    return this.getLevelState(this.getCurrentLevel().id);
  }
  
  getTokenOrderMode(): TokenOrderMode {
    return this.tokenOrderMode;
  }
  
  setTokenOrderMode(mode: TokenOrderMode): void {
    this.tokenOrderMode = mode;
  }
  
  toggleTokenOrder(): TokenOrderMode {
    this.tokenOrderMode = this.tokenOrderMode === 'forward' ? 'reverse' : 'forward';
    return this.tokenOrderMode;
  }
  
  submitWord(word: string): SubmitWordResult {
    const level = this.getCurrentLevel();
    const state = this.getCurrentLevelState();
    const result = submitWord(word, level, state, this.tokenOrderMode);
    if (isLevelComplete(level, state.solved)) {
      this.completedLevelIds.add(level.id);
    }
    return result;
  }

  revealCell(row: number, col: number): RevealCellResult {
    const level = this.getCurrentLevel();
    const state = this.getCurrentLevelState();
    const result = revealCell(level, state, row, col);
    if (result.levelComplete) {
      this.completedLevelIds.add(level.id);
    }
    return result;
  }
  
  isCurrentLevelComplete(): boolean {
    const level = this.getCurrentLevel();
    const state = this.getCurrentLevelState();
    return isLevelComplete(level, state.solved);
  }

  canAdvanceToNextLevel(): boolean {
    if (!this.isCurrentLevelComplete()) {
      return false;
    }
    const currentLevels = this.groupLevels.get(this.currentGroupId);
    const currentGroupDef = this.groupDefinitions.find(g => g.id === this.currentGroupId);

    if (currentLevels && this.currentIndexInGroup < currentLevels.length - 1) {
      return true;
    }

    if (currentGroupDef && currentGroupDef.index < this.groupDefinitions.length - 1) {
      return true;
    }
    
    return false;
  }
  
  advanceToNextLevel(): { advanced: boolean; needsGroupLoad: boolean; nextGroupId?: string } {
    if (!this.isCurrentLevelComplete()) {
      return { advanced: false, needsGroupLoad: false };
    }
    
    const currentLevels = this.groupLevels.get(this.currentGroupId);
    const currentGroupDef = this.groupDefinitions.find(g => g.id === this.currentGroupId);

    if (currentLevels && this.currentIndexInGroup < currentLevels.length - 1) {
      this.currentIndexInGroup += 1;
      this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
      return { advanced: true, needsGroupLoad: false };
    }

    if (currentGroupDef && currentGroupDef.index < this.groupDefinitions.length - 1) {
      const nextGroupDef = this.groupDefinitions[currentGroupDef.index + 1];
      this.currentGroupId = nextGroupDef.id;
      this.currentIndexInGroup = 0;
      this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
      
      const needsLoad = !this.groupLevels.has(nextGroupDef.id);
      return { advanced: true, needsGroupLoad: needsLoad, nextGroupId: nextGroupDef.id };
    }
    
    return { advanced: false, needsGroupLoad: false };
  }
  
  jumpToLevel(groupId: string, indexInGroup: number): { jumped: boolean; needsGroupLoad: boolean } {
    const groupDef = this.groupDefinitions.find(g => g.id === groupId);
    if (!groupDef) {
      return { jumped: false, needsGroupLoad: false };
    }

    if (indexInGroup < 0 || indexInGroup >= groupDef.levelCount) {
      return { jumped: false, needsGroupLoad: false };
    }
    
    this.currentGroupId = groupId;
    this.currentIndexInGroup = indexInGroup;
    this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
    
    const needsLoad = !this.groupLevels.has(groupId);
    return { jumped: true, needsGroupLoad: needsLoad };
  }

  jumpToFirstUnfinishedInGroup(groupId: string): { jumped: boolean; needsGroupLoad: boolean } {
    const levels = this.groupLevels.get(groupId);
    if (!levels) {
      return this.jumpToLevel(groupId, 0);
    }
    
    const indexInGroup = findFirstUnfinishedInGroup(levels, this.levelStates);
    return this.jumpToLevel(groupId, indexInGroup);
  }

  jumpToLevelById(levelId: string): boolean {
    for (const [groupId, levels] of this.groupLevels) {
      const index = levels.findIndex(l => l.id === levelId);
      if (index >= 0) {
        this.currentGroupId = groupId;
        this.currentIndexInGroup = index;
        this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
        return true;
      }
    }
    return false;
  }
 
  resetAllProgress(): void {
    this.levelStates.clear();
    this.completedLevelIds.clear();
    const firstGroup = this.groupDefinitions[0];
    this.currentGroupId = firstGroup?.id ?? '';
    this.currentIndexInGroup = 0;
    this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
  }

  resetCurrentLevelProgress(): void {
    const levelId = this.getCurrentLevel().id;
    this.levelStates.delete(levelId);
    this.completedLevelIds.delete(levelId);
    this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
  }
  
  getSolvedWords(): string[] {
    return [...this.getCurrentLevelState().solved];
  }
  
  getBonusWords(): string[] {
    return [...this.getCurrentLevelState().bonus];
  }
  
  getAllLevelStates(): Map<string, LevelState> {
    return this.levelStates;
  }

  isLevelMarkedComplete(levelId: string): boolean {
    return this.completedLevelIds.has(levelId);
  }
  
  getGridState(): GridState {
    const state = this.getCurrentLevelState();
    return buildGridState(this.getCurrentLevel(), state.solved, state.revealedCells);
  }
  
  getWheelState(): string[] {
    return getTokensForMode(this.getCurrentLevel().letterWheel, this.tokenOrderMode);
  }
  
  displayToken(token: string): string {
    return displayToken(token, this.tokenOrderMode);
  }

  serialize(): SavedGameState {
    const serializedLevels: Record<string, SavedLevelState> = {};
    for (const [levelId, state] of this.levelStates.entries()) {
      const level = this.findLoadedLevelById(levelId);
      const completed = level ? isLevelComplete(level, state.solved) : this.completedLevelIds.has(levelId);

      if (completed) {
        this.completedLevelIds.add(levelId);
      } else {
        this.completedLevelIds.delete(levelId);
      }

      if (
        state.solved.size > 0
        || state.bonus.size > 0
        || state.revealedCells.size > 0
        || state.hints.hintCount > 0
        || state.hints.hintRefreshCount > 0
        || state.hints.excludedHintCanonicals.size > 0
        || state.hints.currentHintCanonical !== null
        || state.hints.modalHintStack.length > 0
        || completed
      ) {
        serializedLevels[levelId] = serializeLevelState(state, completed);
      }
    }
    
    return {
      schemaVersion: GAME_STATE_SCHEMA_VERSION,
      currentGroupId: this.currentGroupId,
      currentIndexInGroup: this.currentIndexInGroup,
      settings: undefined,
      levels: serializedLevels,
    };
  }
  
  static hydrate(
    groupDefinitions: LevelGroupDefinition[],
    initialGroupId: string,
    initialLevels: Level[],
    saved: SavedGameState
  ): GameStateManager {
    const levelStates = new Map<string, LevelState>();
    const completedLevelIds = new Set<string>();
    for (const [key, value] of Object.entries(saved.levels)) {
      levelStates.set(key, hydrateLevelState(value));
      if (value.completed === true) {
        completedLevelIds.add(key);
      }
    }
    
    return new GameStateManager(groupDefinitions, initialGroupId, initialLevels, {
      currentGroupId: saved.currentGroupId,
      currentIndexInGroup: saved.currentIndexInGroup,
      levelStates,
      completedLevelIds,
      tokenOrderMode: DEFAULT_TOKEN_ORDER_MODE,
    });
  }

  private findLoadedLevelById(levelId: string): Level | null {
    for (const levels of this.groupLevels.values()) {
      const level = levels.find((entry) => entry.id === levelId);
      if (level) {
        return level;
      }
    }
    return null;
  }
}

export class GameSession {
  private level: Level;
  private state: LevelState;
  private tokenOrderMode: TokenOrderMode;

  constructor(level: Level, initialState?: Partial<LevelState>) {
    this.level = level;
    this.state = {
      solved: initialState?.solved ?? new Set(),
      bonus: initialState?.bonus ?? new Set(),
      revealedCells: initialState?.revealedCells ?? new Set(),
      hints: {
        hintedCanonicals: initialState?.hints?.hintedCanonicals ?? new Set(),
        excludedHintCanonicals: initialState?.hints?.excludedHintCanonicals ?? new Set(),
        hintCount: initialState?.hints?.hintCount ?? 0,
        hintRefreshCount: initialState?.hints?.hintRefreshCount ?? 0,
        currentHintCanonical: initialState?.hints?.currentHintCanonical ?? null,
        modalHintStack: initialState?.hints?.modalHintStack ?? [],
      },
    };
    this.tokenOrderMode = DEFAULT_TOKEN_ORDER_MODE;
  }

  getTokenOrderMode(): TokenOrderMode {
    return this.tokenOrderMode;
  }

  setTokenOrderMode(mode: TokenOrderMode): void {
    this.tokenOrderMode = mode;
  }

  toggleTokenOrder(): TokenOrderMode {
    this.tokenOrderMode = this.tokenOrderMode === 'forward' ? 'reverse' : 'forward';
    return this.tokenOrderMode;
  }

  getState(): Readonly<LevelState> {
    return this.state;
  }

  getSolvedWords(): string[] {
    return [...this.state.solved];
  }

  getBonusWords(): string[] {
    return [...this.state.bonus];
  }

  getRevealedCells(): Set<string> {
    return buildRevealedCells(this.level, this.state.solved, this.state.revealedCells);
  }

  isLevelComplete(): boolean {
    return isLevelComplete(this.level, this.state.solved);
  }

  getRemainingWordCount(): number {
    let count = 0;
    for (const answer of this.level.answers) {
      if (!this.state.solved.has(normalizeWord(answer.text))) {
        count += 1;
      }
    }
    return count;
  }

  submitWord(word: string): SubmitWordResult {
    return submitWord(word, this.level, this.state, this.tokenOrderMode);
  }

  getLevel(): Readonly<Level> {
    return this.level;
  }

  displayToken(token: string): string {
    return displayToken(token, this.tokenOrderMode);
  }

  getGridState(): GridState {
    return buildGridState(this.level, this.state.solved, this.state.revealedCells);
  }

  getWheelState(): string[] {
    return getTokensForMode(this.level.letterWheel, this.tokenOrderMode);
  }
}

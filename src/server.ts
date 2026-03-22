import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { type Level, type LevelWalls, type LevelAnswer, type LevelGroupDefinition, type LevelsMeta, type DictionaryMeta, type DictionaryLetterFile } from './types.js';
import {
  type RuntimeLevelGroup,
  type GridState,
  type WordStart,
  type LevelState,
  type SavedLevelState,
  normalizeWord,
  buildRuntimeGroupsFromDefinitions,
  buildLevelName,
  extractWordStarts,
  buildAllGridStrings,
  createEmptyLevelState,
  isLevelComplete,
  serializeLevelState,
  GameStateManager,
} from './game-engine.js';
import {
  listSessions,
  loadSession,
  saveSession,
  deleteSession,
  setSessionsDirectory,
} from './persistence.js';
import {
  hasDictionaryEntry as sharedHasDictionaryEntry,
  getDictionaryEntry as sharedGetDictionaryEntry,
  type DictionaryEntry,
  type DictionaryLookup,
  type DictionaryHintRelatedForms,
} from './dictionary.js';
import {
  getUnguessedWordHint as sharedGetUnguessedWordHint,
} from './hint-service.js';

interface ApiError {
  error: string;
  message: string;
}

interface LevelInfoResponse {
  name: string;
  rows: number;
  cols: number;
  wheel: string[];
  wordCount: number;
  wordLengths: number[];
  walls: LevelWalls;
  gridRowsStart: string[];
  gridColsStart: string[];
  wordStarts: WordStart[];
}

interface SessionLevelResponse extends Omit<LevelInfoResponse, 'walls'> {
  gridRowsCurrent: string[];
  gridColsCurrent: string[];
  solvedWords: string[];
  bonusWords: string[];
  isComplete: boolean;
  wordLengthsRemaining: number[];
  tokenDirection: 'forward' | 'reverse';
}

interface LevelPackProgress {
  id: string;
  levelCount: number;
  firstUncompleted: string | null;
}

interface GameStateResponse {
  version: number;
  level: string;
  levelPacks: LevelPackProgress[];
}

interface GridSimpleResponse {
  rows: number;
  cols: number;
  bounds: {
    minRow: number;
    maxRow: number;
    minCol: number;
    maxCol: number;
  };
  gridRowsStart: string[];
  gridColsStart: string[];
  gridRowsCurrent: string[];
  gridColsCurrent: string[];
  wordStarts: WordStart[];
}

let levels: Level[] = [];
let levelGroups: RuntimeLevelGroup[] = [];
let groupDefinitions: LevelGroupDefinition[] = [];

let dictionaryLookup: DictionaryLookup = {};
let dictionaryHintRelatedForms: DictionaryHintRelatedForms = {};
const dictionaryCache = new Map<string, DictionaryLetterFile>();

interface CachedSession {
  gameManager: GameStateManager;
  version: number;
}
const sessionCache = new Map<string, CachedSession>();

async function loadLevelData(): Promise<void> {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const projectRoot = join(__dirname, '..', '..');
  const dataDir = join(projectRoot, 'src', 'data');

  const metaPath = join(dataDir, 'levels._meta.json');
  let metaRaw: string;
  try {
    metaRaw = await readFile(metaPath, 'utf-8');
  } catch (e) {
    console.error(`Failed to load levels meta from ${metaPath}:`, e);
    throw e;
  }

  const meta: LevelsMeta = JSON.parse(metaRaw);
  groupDefinitions = meta.groups ?? [];

  const allLevels: Level[] = [];
  for (const groupDef of groupDefinitions) {
    const groupPath = join(dataDir, groupDef.file);
    let groupRaw: string;
    try {
      groupRaw = await readFile(groupPath, 'utf-8');
    } catch (e) {
      console.error(`Failed to load levels from ${groupPath}:`, e);
      throw e;
    }
    const groupData = JSON.parse(groupRaw);
    if (Array.isArray(groupData.levels)) {
      allLevels.push(...groupData.levels);
    }
  }

  levels = allLevels;
  levelGroups = buildRuntimeGroupsFromDefinitions(groupDefinitions);

  console.log(`Loaded ${levels.length} levels in ${levelGroups.length} groups`);
}

async function loadDictionaryData(): Promise<void> {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const projectRoot = join(__dirname, '..', '..');
  const dataDir = join(projectRoot, 'src', 'data');

  const dictMetaPath = join(dataDir, 'dictionary._meta.json');
  let dictMetaRaw: string;
  try {
    dictMetaRaw = await readFile(dictMetaPath, 'utf-8');
  } catch (e) {
    console.error(`Failed to load dictionary meta from ${dictMetaPath}:`, e);
    throw e;
  }

  const dictMeta: DictionaryMeta = JSON.parse(dictMetaRaw);
  dictionaryLookup = dictMeta.lookup ?? {};
  dictionaryHintRelatedForms = dictMeta.hintRelatedForms ?? {};

  console.log(`Loaded dictionary with ${Object.keys(dictionaryLookup).length} lookup entries`);
}

async function loadDictionaryLetter(letter: string): Promise<DictionaryLetterFile> {
  const upperLetter = letter.toUpperCase();
  const cached = dictionaryCache.get(upperLetter);
  if (cached) return cached;

  const __dirname = dirname(fileURLToPath(import.meta.url));
  const projectRoot = join(__dirname, '..', '..');
  const dataDir = join(projectRoot, 'src', 'data');

  const path = join(dataDir, `dictionary.${upperLetter}.json`);
  const data: DictionaryLetterFile = JSON.parse(await readFile(path, 'utf-8'));
  dictionaryCache.set(upperLetter, data);
  return data;
}

async function getDictionaryEntry(word: string): Promise<DictionaryEntry | null> {
  return sharedGetDictionaryEntry(dictionaryLookup, loadDictionaryLetter, word);
}

function getLevelById(id: string): Level | undefined {
  return levels.find((level) => level.id === id);
}

function getLevelByName(name: string): Level | undefined {
  const match = name.match(/^([A-Za-z]+)(\d+)$/);
  if (!match) return undefined;
  const [, groupId, indexStr] = match;
  const indexInGroup = parseInt(indexStr, 10) - 1;
  return levels.find((l) => l.groupId === groupId && l.indexInGroup === indexInGroup);
}

function generateSessionId(): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return `sess_${timestamp}_${random}`;
}

function buildGroupLevelsMap(): Map<string, Level[]> {
  const groupLevels = new Map<string, Level[]>();
  for (const level of levels) {
    const groupId = level.groupId;
    if (!groupId) continue;
    const group = groupLevels.get(groupId);
    if (group) {
      group.push(level);
    } else {
      groupLevels.set(groupId, [level]);
    }
  }
  return groupLevels;
}

function createGameManagerWithAllLevels(
  initialGroupId: string,
  initialState?: {
    levelStates?: Map<string, LevelState>;
    tokenOrderMode?: 'forward' | 'reverse';
    currentGroupId?: string;
    currentIndexInGroup?: number;
  }
): GameStateManager {
  const groupLevels = buildGroupLevelsMap();
  const initialLevels = groupLevels.get(initialGroupId) ?? [];
  
  const gm = new GameStateManager(groupDefinitions, initialGroupId, initialLevels, initialState);

  for (const [groupId, groupLevelList] of groupLevels) {
    if (groupId !== initialGroupId) {
      gm.setGroupLevels(groupId, groupLevelList);
    }
  }
  
  return gm;
}

async function createSession(): Promise<string> {
  if (levels.length === 0 || groupDefinitions.length === 0) {
    throw new Error('No levels available');
  }

  const sessionId = generateSessionId();
  const initialGroupId = groupDefinitions[0].id;
  const gameManager = createGameManagerWithAllLevels(initialGroupId);

  const persisted = await saveSession({
    id: sessionId,
    levelId: gameManager.getCurrentLevel().id,
    tokenOrderMode: 'forward',
    levelStates: {},
    version: 0,
  });

  sessionCache.set(sessionId, { 
    gameManager, 
    version: persisted.version,
  });

  return sessionId;
}

async function getSession(sessionId: string): Promise<CachedSession | null> {
  const cached = sessionCache.get(sessionId);
  if (cached) {
    return cached;
  }

  const persisted = await loadSession(sessionId);
  if (!persisted) {
    return null;
  }

  const levelStates = new Map<string, LevelState>();
  if (persisted.levelStates) {
    for (const [levelId, state] of Object.entries(persisted.levelStates)) {
      const levelState = createEmptyLevelState();
      levelState.solved = new Set(state.solved.map(normalizeWord));
      levelState.bonus = new Set(state.bonus.map(normalizeWord));
      levelState.hints.hintedCanonicals = new Set((state.hints?.hintedCanonicals ?? []).map(normalizeWord));
      levelState.hints.excludedHintCanonicals = new Set((state.hints?.excludedHintCanonicals ?? []).map(normalizeWord));
      levelState.hints.hintCount = state.hints?.hintCount ?? 0;
      levelState.hints.hintRefreshUsed = state.hints?.hintRefreshUsed ?? false;
      levelState.hints.currentHintCanonical = state.hints?.currentHintCanonical ?? null;
      levelStates.set(levelId, levelState);
    }
  }

  const currentLevelId = persisted.levelId;
  if (!levelStates.has(currentLevelId)) {
    levelStates.set(currentLevelId, createEmptyLevelState());
  }

  const currentLevel = levels.find(l => l.id === persisted.levelId);
  const currentGroupId = currentLevel?.groupId ?? groupDefinitions[0]?.id ?? '';
  const currentIndexInGroup = currentLevel?.indexInGroup ?? 0;

  const gameManager = createGameManagerWithAllLevels(currentGroupId, {
    currentGroupId,
    currentIndexInGroup,
    levelStates,
    tokenOrderMode: persisted.tokenOrderMode,
  });

  const cachedSession: CachedSession = { 
    gameManager, 
    version: persisted.version,
  };
  sessionCache.set(sessionId, cachedSession);
  return cachedSession;
}

async function persistSession(sessionId: string, cached: CachedSession): Promise<void> {
  const gm = cached.gameManager;
  const level = gm.getCurrentLevel();

  const levelStatesRecord: Record<string, SavedLevelState> = {};
  for (const [levelId, state] of gm.getAllLevelStates()) {
    levelStatesRecord[String(levelId)] = serializeLevelState(state);
  }
  
  const persisted = await saveSession({
    id: sessionId,
    levelId: level.id,
    tokenOrderMode: gm.getTokenOrderMode(),
    levelStates: levelStatesRecord,
    version: cached.version,
  });

  cached.version = persisted.version;
}

function parseJsonBody<T>(req: import('node:http').IncomingMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk.toString();
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(body));
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
    req.on('error', reject);
  });
}

function sendJson<T>(
  res: import('node:http').ServerResponse,
  status: number,
  data: T
): void {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(JSON.stringify(data));
}

function sendError(
  res: import('node:http').ServerResponse,
  status: number,
  error: string,
  message: string
): void {
  sendJson<ApiError>(res, status, { error, message });
}

function buildLevelInfo(level: Level): LevelInfoResponse {
  const wordLengths = level.answers.map((a) => a.path.length).sort((a, b) => a - b);
  const gridStrings = buildAllGridStrings(level.rows, level.cols, level.answers, new Set());
  const wordStarts = extractWordStarts(level.answers);
  
  return {
    name: buildLevelName(level),
    rows: level.rows,
    cols: level.cols,
    wheel: level.letterWheel.map(t => t.toUpperCase()),
    wordCount: level.answers.length,
    wordLengths,
    walls: level.walls,
    gridRowsStart: gridStrings.start.rows,
    gridColsStart: gridStrings.start.cols,
    wordStarts,
  };
}

function buildSessionLevelInfo(cached: CachedSession): SessionLevelResponse {
  const gm = cached.gameManager;
  const level = gm.getCurrentLevel();
  const { walls: _, ...base } = buildLevelInfo(level);
  
  const solvedWords = gm.getSolvedWords();
  const solvedSet = new Set(solvedWords.map(normalizeWord));
  const wordLengthsRemaining = level.answers
    .filter((a) => !solvedSet.has(normalizeWord(a.text)))
    .map((a) => a.path.length)
    .sort((a, b) => a - b);
  
  const gridStrings = buildAllGridStrings(level.rows, level.cols, level.answers, solvedSet);
  
  return {
    ...base,
    gridRowsCurrent: gridStrings.current.rows,
    gridColsCurrent: gridStrings.current.cols,
    wheel: gm.getWheelState().map(t => t.toUpperCase()),
    solvedWords: solvedWords.map(w => w.toUpperCase()),
    bonusWords: gm.getBonusWords().map(w => w.toUpperCase()),
    isComplete: gm.isCurrentLevelComplete(),
    wordLengthsRemaining,
    tokenDirection: gm.getTokenOrderMode(),
  };
}

function buildGameState(cached: CachedSession): GameStateResponse {
  const gm = cached.gameManager;
  const level = gm.getCurrentLevel();
  const levelStates = gm.getAllLevelStates();

  const levelPacks: LevelPackProgress[] = levelGroups.map((group) => {
    let firstUncompleted: string | null = null;
    
    const groupLevelsList = levels.filter(l => l.groupId === group.id);
    for (const lvl of groupLevelsList) {
      const state = levelStates.get(lvl.id);
      const solved = state?.solved ?? new Set();
      if (!isLevelComplete(lvl, solved)) {
        firstUncompleted = buildLevelName(lvl);
        break;
      }
    }
    
    return {
      id: group.id,
      levelCount: group.levelCount,
      firstUncompleted,
    };
  });

  return {
    version: cached.version,
    level: buildLevelName(level),
    levelPacks,
  };
}

async function handleGetLevels(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse
): Promise<void> {
  sendJson(res, 200, {
    totalLevels: levels.length,
    groups: levelGroups.map((g) => ({
      id: g.id,
      index: g.index,
      levelCount: g.levelCount,
      wheelSize: g.wheelSize,
    })),
  });
}

async function handleGetGroupLevels(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  groupId: string
): Promise<void> {
  const group = levelGroups.find((g) => g.id === groupId);
  if (!group) {
    sendError(res, 404, 'NOT_FOUND', `Group '${groupId}' not found`);
    return;
  }

  const groupLevelsList = levels.filter(l => l.groupId === groupId);

  sendJson(res, 200, {
    groupId: group.id,
    levels: groupLevelsList.map((level) => ({
      name: buildLevelName(level),
    })),
  });
}

async function handleGetLevel(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  levelName: string
): Promise<void> {
  const level = getLevelByName(levelName);

  if (!level) {
    sendError(res, 404, 'NOT_FOUND', `Level '${levelName}' not found`);
    return;
  }

  sendJson(res, 200, buildLevelInfo(level));
}

async function handleCreateSession(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse
): Promise<void> {
  try {
    await parseJsonBody(req).catch(() => ({}));

    const gameId = await createSession();
    const session = await getSession(gameId);

    sendJson(res, 201, {
      gameId,
      level: 'A1',
      state: buildGameState(session!),
    });
  } catch (e) {
    sendError(res, 400, 'BAD_REQUEST', (e as Error).message);
  }
}

async function handleGetSession(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const session = await getSession(sessionId);

  if (!session) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  sendJson(res, 200, buildGameState(session));
}

async function handleGetSessionLevel(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  sendJson(res, 200, buildSessionLevelInfo(cached));
}

async function handleDeleteSession(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const session = await getSession(sessionId);
  if (!session) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  sessionCache.delete(sessionId);
  await deleteSession(sessionId);
  sendJson(res, 200, { deleted: true });
}

async function handleSubmitWord(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  try {
    const body = await parseJsonBody<{ word: string; version: number; toggleTokenDirectionFirst?: boolean }>(req);

    if (!body.word || typeof body.word !== 'string') {
      sendError(res, 400, 'BAD_REQUEST', 'Missing or invalid word');
      return;
    }

    if (body.version !== cached.version) {
      sendError(res, 409, 'VERSION_MISMATCH', 'Session was modified by another request');
      return;
    }

    if (body.toggleTokenDirectionFirst) {
      cached.gameManager.toggleTokenOrder();
    }

    const result = cached.gameManager.submitWord(body.word);

    await persistSession(sessionId, cached);

    const response: Record<string, unknown> = {
      version: cached.version,
      result: result.result,
      word: body.word.trim().toUpperCase(),
      levelComplete: result.levelComplete,
    };

    if (result.result === 'solved') {
      response['grid'] = 'updated';
    }

    if (result.levelComplete && result.completionMessage) {
      response['completionMessage'] = result.completionMessage;
    }

    response['wheel'] = cached.gameManager.getWheelState().map(t => t.toUpperCase());

    sendJson(res, 200, response);
  } catch (e) {
    sendError(res, 400, 'BAD_REQUEST', (e as Error).message);
  }
}

async function handleToggleTokenDirection(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  try {
    const body = await parseJsonBody<{ version: number }>(req);

    if (body.version !== cached.version) {
      sendError(res, 409, 'VERSION_MISMATCH', 'Session was modified by another request');
      return;
    }

    cached.gameManager.toggleTokenOrder();

    await persistSession(sessionId, cached);

    const wheel = cached.gameManager.getWheelState().map(t => t.toUpperCase());
    sendJson(res, 200, { 
      version: cached.version,
      wheel, 
      tokenDirection: cached.gameManager.getTokenOrderMode(),
    });
  } catch (e) {
    sendError(res, 400, 'BAD_REQUEST', (e as Error).message);
  }
}

async function handleGetWheel(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  const wheel = cached.gameManager.getWheelState().map(t => t.toUpperCase());
  sendJson(res, 200, { 
    version: cached.version,
    tokens: wheel, 
    tokenOrderMode: cached.gameManager.getTokenOrderMode(),
  });
}

async function handleGetGrid(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  const gridState: GridState = cached.gameManager.getGridState();
  sendJson(res, 200, gridState);
}

function buildGridSimple(
  gridState: GridState,
  answers: LevelAnswer[],
  solvedWords: Set<string>
): GridSimpleResponse {
  const { rows, cols, bounds } = gridState;
  const gridStrings = buildAllGridStrings(rows, cols, answers, solvedWords);
  const wordStarts = extractWordStarts(answers);

  return {
    rows,
    cols,
    bounds,
    gridRowsStart: gridStrings.start.rows,
    gridColsStart: gridStrings.start.cols,
    gridRowsCurrent: gridStrings.current.rows,
    gridColsCurrent: gridStrings.current.cols,
    wordStarts,
  };
}

async function handleGetGridSimple(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  const gridState: GridState = cached.gameManager.getGridState();
  const level = cached.gameManager.getCurrentLevel();
  const solvedWords = cached.gameManager.getSolvedWords();
  const simpleResponse = buildGridSimple(gridState, level.answers, new Set(solvedWords));
  sendJson(res, 200, simpleResponse);
}

async function handleNextLevel(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  try {
    const body = await parseJsonBody<{ version: number }>(req);

    if (body.version !== cached.version) {
      sendError(res, 409, 'VERSION_MISMATCH', 'Session was modified by another request');
      return;
    }

    if (!cached.gameManager.isCurrentLevelComplete()) {
      sendError(res, 400, 'BAD_REQUEST', 'Current level not complete');
      return;
    }

    const level = cached.gameManager.getCurrentLevel();
    const currentIndex = levels.findIndex((l) => l.id === level.id);
    if (currentIndex === -1 || currentIndex >= levels.length - 1) {
      sendError(res, 400, 'BAD_REQUEST', 'No more levels available');
      return;
    }

    const previousLevel = buildLevelName(level);
    
    cached.gameManager.advanceToNextLevel();
    const nextLevel = cached.gameManager.getCurrentLevel();

    await persistSession(sessionId, cached);

    sendJson(res, 200, {
      previousLevel,
      newLevel: buildLevelName(nextLevel),
      state: buildGameState(cached),
    });
  } catch (e) {
    sendError(res, 400, 'BAD_REQUEST', (e as Error).message);
  }
}

async function handleJumpLevel(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  try {
    const body = await parseJsonBody<{ levelName: string; version: number }>(req);

    if (body.version !== cached.version) {
      sendError(res, 409, 'VERSION_MISMATCH', 'Session was modified by another request');
      return;
    }

    if (!body.levelName) {
      sendError(res, 400, 'BAD_REQUEST', 'Missing levelName');
      return;
    }

    const targetLevel = getLevelByName(body.levelName);

    if (!targetLevel) {
      sendError(res, 404, 'NOT_FOUND', `Level '${body.levelName}' not found`);
      return;
    }

    const previousLevel = buildLevelName(cached.gameManager.getCurrentLevel());
    cached.gameManager.jumpToLevelById(targetLevel.id);

    await persistSession(sessionId, cached);

    sendJson(res, 200, {
      previousLevel,
      newLevel: buildLevelName(targetLevel),
      state: buildGameState(cached),
    });
  } catch (e) {
    sendError(res, 400, 'BAD_REQUEST', (e as Error).message);
  }
}

async function handleResetLevel(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  try {
    const body = await parseJsonBody<{ version: number }>(req);

    if (body.version !== cached.version) {
      sendError(res, 409, 'VERSION_MISMATCH', 'Session was modified by another request');
      return;
    }

    cached.gameManager.resetCurrentLevelProgress();

    await persistSession(sessionId, cached);

    sendJson(res, 200, {
      version: cached.version,
      level: buildLevelName(cached.gameManager.getCurrentLevel()),
      state: buildSessionLevelInfo(cached),
    });
  } catch (e) {
    sendError(res, 400, 'BAD_REQUEST', (e as Error).message);
  }
}

async function handleListSessions(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse
): Promise<void> {
  try {
    const games = await listSessions();
    const summary = games.map((sg) => {
      const level = getLevelById(sg.levelId);
      return {
        gameId: sg.id,
        level: level ? buildLevelName(level) : null,
      };
    });
    sendJson(res, 200, { games: summary });
  } catch (e) {
    sendError(res, 500, 'INTERNAL_ERROR', (e as Error).message);
  }
}

async function handleGetDictionaryEntry(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  word: string
): Promise<void> {
  const normalized = normalizeWord(word);
  const entry = await getDictionaryEntry(normalized);

  if (!entry) {
    sendJson(res, 200, null);
    return;
  }

  sendJson(res, 200, {
    canonical: entry.canonical,
    definition: entry.definition,
    selectedSource: entry.selectedSource,
    definitions: entry.definitions,
  });
}

async function handleGetDictionaryExists(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  word: string
): Promise<void> {
  const normalized = normalizeWord(word);
  const exists = sharedHasDictionaryEntry(dictionaryLookup, normalized);

  sendJson(res, 200, { exists });
}

async function handleGetHint(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  const level = cached.gameManager.getCurrentLevel();
  const state = cached.gameManager.getCurrentLevelState();
  const solvedWords = new Set(state.solved);

  const hint = await sharedGetUnguessedWordHint(
    level,
    solvedWords,
    state.hints.excludedHintCanonicals,
    state.hints.currentHintCanonical,
    dictionaryLookup,
    dictionaryHintRelatedForms,
    getDictionaryEntry,
    loadDictionaryLetter
  );

  if (!hint) {
    sendJson(res, 200, { version: cached.version, hint: null });
    return;
  }

  state.hints.currentHintCanonical = hint.canonical;

  if (!state.hints.hintedCanonicals.has(hint.canonical)) {
    state.hints.hintedCanonicals.add(hint.canonical);
    state.hints.hintCount += 1;
  }

  await persistSession(sessionId, cached);

  const canRefresh = !state.hints.hintRefreshUsed;

  sendJson(res, 200, {
    version: cached.version,
    excerpt: hint.excerpt.text,
    truncatedStart: hint.excerpt.truncatedStart,
    truncatedEnd: hint.excerpt.truncatedEnd,
    hintCount: state.hints.hintCount,
    canRefresh,
  });
}

async function handleRefreshHint(
  _req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse,
  sessionId: string
): Promise<void> {
  const cached = await getSession(sessionId);

  if (!cached) {
    sendError(res, 404, 'NOT_FOUND', 'Session not found');
    return;
  }

  const state = cached.gameManager.getCurrentLevelState();

  if (state.hints.hintRefreshUsed) {
    sendError(res, 400, 'BAD_REQUEST', 'Hint refresh already used for this level');
    return;
  }

  if (!state.hints.currentHintCanonical) {
    sendError(res, 400, 'BAD_REQUEST', 'No current hint to refresh');
    return;
  }

  state.hints.excludedHintCanonicals.add(state.hints.currentHintCanonical);
  state.hints.hintRefreshUsed = true;

  if (state.hints.hintedCanonicals.has(state.hints.currentHintCanonical)) {
    state.hints.hintedCanonicals.delete(state.hints.currentHintCanonical);
    state.hints.hintCount -= 1;
  }

  state.hints.currentHintCanonical = null;

  const level = cached.gameManager.getCurrentLevel();
  const solvedWords = new Set(state.solved);

  const newHint = await sharedGetUnguessedWordHint(
    level,
    solvedWords,
    state.hints.excludedHintCanonicals,
    state.hints.currentHintCanonical,
    dictionaryLookup,
    dictionaryHintRelatedForms,
    getDictionaryEntry,
    loadDictionaryLetter
  );

  if (!newHint) {
    await persistSession(sessionId, cached);
    sendJson(res, 200, { version: cached.version, hint: null });
    return;
  }

  state.hints.currentHintCanonical = newHint.canonical;

  if (!state.hints.hintedCanonicals.has(newHint.canonical)) {
    state.hints.hintedCanonicals.add(newHint.canonical);
    state.hints.hintCount += 1;
  }

  await persistSession(sessionId, cached);

  sendJson(res, 200, {
    version: cached.version,
    excerpt: newHint.excerpt.text,
    truncatedStart: newHint.excerpt.truncatedStart,
    truncatedEnd: newHint.excerpt.truncatedEnd,
    hintCount: state.hints.hintCount,
    canRefresh: false,
  });
}

async function handleRequest(
  req: import('node:http').IncomingMessage,
  res: import('node:http').ServerResponse
): Promise<void> {
  const url = new URL(req.url || '/', 'http://localhost');
  const path = url.pathname;

  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end();
    return;
  }

  try {
    if (req.method === 'GET' && path === '/api/levels') {
      return handleGetLevels(req, res);
    }

    const levelMatch = path.match(/^\/api\/levels\/([A-Za-z]+\d+)$/);
    if (req.method === 'GET' && levelMatch) {
      return handleGetLevel(req, res, levelMatch[1]);
    }

    const groupLevelsMatch = path.match(/^\/api\/groups\/([^/]+)\/levels$/);
    if (req.method === 'GET' && groupLevelsMatch) {
      return handleGetGroupLevels(req, res, groupLevelsMatch[1]);
    }

    if (req.method === 'GET' && path === '/api/games') {
      return handleListSessions(req, res);
    }

    if (req.method === 'POST' && path === '/api/games') {
      return handleCreateSession(req, res);
    }

    const sessionMatch = path.match(/^\/api\/games\/([^/]+)$/);
    if (sessionMatch) {
      if (req.method === 'GET') {
        return handleGetSession(req, res, sessionMatch[1]);
      }
      if (req.method === 'DELETE') {
        return handleDeleteSession(req, res, sessionMatch[1]);
      }
    }

    const sessionLevelMatch = path.match(/^\/api\/games\/([^/]+)\/level$/);
    if (req.method === 'GET' && sessionLevelMatch) {
      return handleGetSessionLevel(req, res, sessionLevelMatch[1]);
    }

    const submitMatch = path.match(/^\/api\/games\/([^/]+)\/submit$/);
    if (req.method === 'POST' && submitMatch) {
      return handleSubmitWord(req, res, submitMatch[1]);
    }

    const tokenDirectionMatch = path.match(/^\/api\/games\/([^/]+)\/token-direction$/);
    if (req.method === 'POST' && tokenDirectionMatch) {
      return handleToggleTokenDirection(req, res, tokenDirectionMatch[1]);
    }

    const wheelMatch = path.match(/^\/api\/games\/([^/]+)\/wheel$/);
    if (req.method === 'GET' && wheelMatch) {
      return handleGetWheel(req, res, wheelMatch[1]);
    }

    const gridObjectMatch = path.match(/^\/api\/games\/([^/]+)\/grid\/object$/);
    if (req.method === 'GET' && gridObjectMatch) {
      return handleGetGrid(req, res, gridObjectMatch[1]);
    }

    const gridMatch = path.match(/^\/api\/games\/([^/]+)\/grid$/);
    if (req.method === 'GET' && gridMatch) {
      return handleGetGridSimple(req, res, gridMatch[1]);
    }

    const nextMatch = path.match(/^\/api\/games\/([^/]+)\/next$/);
    if (req.method === 'POST' && nextMatch) {
      return handleNextLevel(req, res, nextMatch[1]);
    }

    const jumpMatch = path.match(/^\/api\/games\/([^/]+)\/jump$/);
    if (req.method === 'POST' && jumpMatch) {
      return handleJumpLevel(req, res, jumpMatch[1]);
    }

    const resetLevelMatch = path.match(/^\/api\/games\/([^/]+)\/reset-level$/);
    if (req.method === 'POST' && resetLevelMatch) {
      return handleResetLevel(req, res, resetLevelMatch[1]);
    }

    const dictionaryMatch = path.match(/^\/api\/dictionary\/([^/]+)$/);
    if (req.method === 'GET' && dictionaryMatch) {
      return handleGetDictionaryEntry(req, res, dictionaryMatch[1]);
    }

    const dictionaryExistsMatch = path.match(/^\/api\/dictionary\/([^/]+)\/exists$/);
    if (req.method === 'GET' && dictionaryExistsMatch) {
      return handleGetDictionaryExists(req, res, dictionaryExistsMatch[1]);
    }

    const hintMatch = path.match(/^\/api\/games\/([^/]+)\/hint$/);
    if (req.method === 'GET' && hintMatch) {
      return handleGetHint(req, res, hintMatch[1]);
    }

    const hintRefreshMatch = path.match(/^\/api\/games\/([^/]+)\/hint\/refresh$/);
    if (req.method === 'POST' && hintRefreshMatch) {
      return handleRefreshHint(req, res, hintRefreshMatch[1]);
    }

    if (path === '/health') {
      sendJson(res, 200, { status: 'ok', levelsLoaded: levels.length });
      return;
    }

    sendError(res, 404, 'NOT_FOUND', `Unknown route: ${path}`);
  } catch (e) {
    console.error('Request handler error:', e);
    sendError(res, 500, 'INTERNAL_ERROR', (e as Error).message);
  }
}

async function main(): Promise<void> {
  const port = parseInt(process.env['PORT'] || '3001', 10);
  const savedGamesDir = process.env['SAVEDGAMES_DIR'] || 'savedgames';

  setSessionsDirectory(savedGamesDir);

  console.log('Loading level data...');
  await loadLevelData();

  console.log('Loading dictionary data...');
  await loadDictionaryData();

  const server = createServer((req, res) => {
    void handleRequest(req, res);
  });

  server.listen(port, () => {
    console.log(`Word Tracer API server running on http://localhost:${port}`);
    console.log('See API.md for endpoint documentation.');
  });
}

main().catch((e) => {
  console.error('Server startup failed:', e);
  process.exit(1);
});

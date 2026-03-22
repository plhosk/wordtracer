export type TokenOrderMode = 'forward' | 'reverse';

export interface LevelAnswer {
  text: string;
  path: Array<[number, number]>;
  allowedModes?: TokenOrderMode[];
}

export const WALL_TOP = 0;
export const WALL_RIGHT = 1;
export const WALL_BOTTOM = 2;
export const WALL_LEFT = 3;

export interface LevelWalls {
  [cellKey: string]: [top: number, right: number, bottom: number, left: number];
}

export function getCellWalls(
  walls: LevelWalls,
  row: number,
  col: number
): [number, number, number, number] {
  return walls[`${row},${col}`] ?? [0, 0, 0, 0];
}

export function hasWall(
  walls: LevelWalls,
  row: number,
  col: number,
  direction: number
): boolean {
  const cellWalls = getCellWalls(walls, row, col);
  return cellWalls[direction] === 1;
}

export interface Level {
  id: string;
  rows: number;
  cols: number;
  walls: LevelWalls;
  letterWheel: string[];
  answers: LevelAnswer[];
  validWords: string[];
  bonusWords?: string[];
  groupId?: string;
  groupIndex?: number;
  indexInGroup?: number;
}

export interface LevelGroupDefinition {
  id: string;
  index: number;
  wheelSize: number;
  levelCount: number;
  file: string;
}

export interface LevelsMeta {
  meta: {
    schemaVersion: number;
  };
  groups: LevelGroupDefinition[];
}

export interface LevelGroupFile {
  groupId: string;
  levels: Level[];
}

export function getLetterAt(level: Level, row: number, col: number): string | null {
  for (const answer of level.answers) {
    const idx = answer.path.findIndex(([r, c]) => r === row && c === col);
    if (idx !== -1) {
      return answer.text[idx];
    }
  }
  return null;
}

export interface DictionaryMeta {
  meta: {
    wordCount?: number;
    mappedWordCount?: number;
    definitionCount?: number;
    letterCount?: number;
  };
  letters: string[];
  lookup: Record<string, string | null>;
  hintRelatedForms?: Record<string, string[]>;
}

export type DictionaryDefinitionSource = 'webster' | 'wordnet';

export interface DictionarySourceDefinitions {
  selectedSource?: DictionaryDefinitionSource;
  webster?: string;
  wordnet?: string;
}

export interface DictionaryLetterFile {
  letter: string;
  sourceDefinitions: Record<string, DictionarySourceDefinitions>;
}

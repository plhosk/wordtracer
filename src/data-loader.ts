import {
  type Level,
  type LevelGroupDefinition,
  type LevelsMeta,
  type LevelGroupFile,
  type DictionaryMeta,
  type DictionaryLetterFile,
} from './types';
import {
  type RuntimeLevelGroup,
  buildRuntimeGroupsFromDefinitions,
} from './game-engine';

import levelsMetaUrl from './data/levels._meta.json?url';
import dictionaryMetaUrl from './data/dictionary._meta.json?url';

type LevelsMetaType = NonNullable<LevelsMeta['meta']>;

interface LoadedMetaData {
  levelsMeta: LevelsMetaType | null;
  groupDefinitions: LevelGroupDefinition[];
  dictionaryMeta: DictionaryMeta['meta'] | null;
  dictionaryLetters: string[];
  dictionaryLookup: Record<string, string | null>;
}

interface LoadedLevelData {
  groups: RuntimeLevelGroup[];
}

interface LoadedInitialData {
  groups: RuntimeLevelGroup[];
  initialGroupId: string;
  initialLevels: Level[];
}

class DataLoader {
  private levelsMeta: LevelsMetaType | null = null;
  private groupDefinitions: LevelGroupDefinition[] = [];
  private dictionaryMeta: DictionaryMeta['meta'] | null = null;
  private dictionaryLetters: string[] = [];
  private dictionaryLookup: Record<string, string | null> = {};

  private levelCache: Map<string, Level[]> = new Map();
  private dictionaryCache: Map<string, DictionaryLetterFile> = new Map();

  private metaLoadingPromise: Promise<LoadedMetaData> | null = null;

  async loadMeta(): Promise<LoadedMetaData> {
    if (this.metaLoadingPromise) return this.metaLoadingPromise;
    this.metaLoadingPromise = this.doLoadMeta();
    return this.metaLoadingPromise;
  }

  private async doLoadMeta(): Promise<LoadedMetaData> {
    const [levelsMetaRes, dictMetaRes] = await Promise.all([
      fetch(levelsMetaUrl),
      fetch(dictionaryMetaUrl),
    ]);

    if (!levelsMetaRes.ok) {
      throw new Error(`Failed to load levels meta: ${levelsMetaRes.status}`);
    }
    if (!dictMetaRes.ok) {
      throw new Error(`Failed to load dictionary meta: ${dictMetaRes.status}`);
    }

    const levelsMetaData: LevelsMeta = await levelsMetaRes.json();
    const dictMetaData: DictionaryMeta = await dictMetaRes.json();

    this.levelsMeta = levelsMetaData.meta ?? null;
    this.groupDefinitions = levelsMetaData.groups ?? [];
    this.dictionaryMeta = dictMetaData.meta ?? null;
    this.dictionaryLetters = dictMetaData.letters ?? [];
    this.dictionaryLookup = dictMetaData.lookup ?? {};

    return {
      levelsMeta: this.levelsMeta,
      groupDefinitions: this.groupDefinitions,
      dictionaryMeta: this.dictionaryMeta,
      dictionaryLetters: this.dictionaryLetters,
      dictionaryLookup: this.dictionaryLookup,
    };
  }

  async loadGroupLevels(groupId: string): Promise<Level[]> {
    const cached = this.levelCache.get(groupId);
    if (cached) return cached;

    const groupDef = this.groupDefinitions.find((g) => g.id === groupId);
    if (!groupDef) {
      throw new Error(`Unknown group: ${groupId}`);
    }

    const fileUrl = new URL(`./data/${groupDef.file}`, import.meta.url);
    const response = await fetch(fileUrl.href);
    if (!response.ok) {
      throw new Error(`Failed to load levels for group ${groupId}: ${response.status}`);
    }

    const data: LevelGroupFile = await response.json();
    const levels = (data.levels ?? []).map(level => ({
      ...level,
      id: String(level.id),
    }));
    this.levelCache.set(groupId, levels);
    return levels;
  }

  async loadAllLevels(): Promise<LoadedLevelData> {
    await this.loadMeta();

    const groups = buildRuntimeGroupsFromDefinitions(this.groupDefinitions);

    return { groups };
  }

  async loadInitialLevels(preferredGroupId?: string): Promise<LoadedInitialData> {
    await this.loadMeta();

    const targetGroupId = preferredGroupId ?? this.groupDefinitions[0]?.id;
    if (!targetGroupId) {
      throw new Error('No group definitions available');
    }

    const initialLevels = await this.loadGroupLevels(targetGroupId);

    const groups = buildRuntimeGroupsFromDefinitions(this.groupDefinitions);

    return { groups, initialGroupId: targetGroupId, initialLevels };
  }

  async loadDictionaryLetter(letter: string): Promise<DictionaryLetterFile> {
    const upperLetter = letter.toUpperCase();
    const cached = this.dictionaryCache.get(upperLetter);
    if (cached) return cached;

    const fileUrl = new URL(`./data/dictionary.${upperLetter}.json`, import.meta.url);
    const response = await fetch(fileUrl.href);
    if (!response.ok) {
      throw new Error(`Failed to load dictionary for letter ${upperLetter}: ${response.status}`);
    }

    const data: DictionaryLetterFile = await response.json();
    this.dictionaryCache.set(upperLetter, data);
    return data;
  }

  getDictionaryLookup(): Record<string, string | null> {
    return this.dictionaryLookup;
  }

  getGroupDefinitions(): LevelGroupDefinition[] {
    return this.groupDefinitions;
  }

  getLevelsMeta(): LevelsMetaType | null {
    return this.levelsMeta;
  }

  getDictionaryMeta(): DictionaryMeta['meta'] | null {
    return this.dictionaryMeta;
  }

  getCachedGroupLevels(groupId: string): Level[] | undefined {
    return this.levelCache.get(groupId);
  }

  getCachedDictionaryLetter(letter: string): DictionaryLetterFile | undefined {
    return this.dictionaryCache.get(letter.toUpperCase());
  }

  getAllCachedLevels(): Level[] {
    const allLevels: Level[] = [];
    for (const levels of this.levelCache.values()) {
      allLevels.push(...levels);
    }
    return allLevels;
  }
}

export const dataLoader = new DataLoader();

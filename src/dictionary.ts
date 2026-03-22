import {
  type DictionaryLetterFile,
  type DictionaryDefinitionSource,
  type DictionarySourceDefinitions,
} from './types.js';

export type { DictionaryDefinitionSource } from './types.js';

export interface DictionaryEntryDefinitions {
  webster: string | null;
  wordnet: string | null;
}

export interface DictionaryEntry {
  canonical: string;
  definition: string;
  selectedSource: DictionaryDefinitionSource | null;
  definitions: DictionaryEntryDefinitions;
}

export interface DictionaryLookup {
  [word: string]: string | null;
}

export interface DictionaryHintRelatedForms {
  [canonical: string]: string[];
}

export function hasDictionaryEntry(
  lookup: DictionaryLookup,
  word: string
): boolean {
  if (!word) return false;
  const canonical = lookup[word];
  return canonical !== null && canonical !== undefined;
}

export async function getDictionaryEntry(
  lookup: DictionaryLookup,
  loadLetterFile: (letter: string) => Promise<DictionaryLetterFile>,
  word: string
): Promise<DictionaryEntry | null> {
  if (!word) return null;
  const canonical = lookup[word];
  if (!canonical) return null;

  const letterData = await loadLetterFile(canonical[0]);
  return getDictionaryEntryByCanonical(letterData, canonical);
}

function cleanDefinition(definition: unknown): string | null {
  if (typeof definition !== 'string') {
    return null;
  }
  const trimmed = definition.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeSelectedSource(source: unknown): DictionaryDefinitionSource | null {
  return source === 'webster' || source === 'wordnet' ? source : null;
}

function buildDefinitionsBySource(
  sourceDefinitions: DictionarySourceDefinitions | undefined
): DictionaryEntryDefinitions {
  const webster = cleanDefinition(sourceDefinitions?.webster);
  const wordnet = cleanDefinition(sourceDefinitions?.wordnet);
  return { webster, wordnet };
}

export function getDictionaryEntryByCanonical(
  letterData: DictionaryLetterFile,
  canonical: string
): DictionaryEntry | null {
  const sourceDefinitions = letterData.sourceDefinitions[canonical];
  const selectedSource = normalizeSelectedSource(sourceDefinitions?.selectedSource);
  const definitions = buildDefinitionsBySource(sourceDefinitions);
  const selectedDefinition = selectedSource
    ? definitions[selectedSource]
    : (definitions.webster ?? definitions.wordnet);
  if (!selectedDefinition) {
    return null;
  }

  return {
    canonical,
    definition: selectedDefinition,
    selectedSource,
    definitions,
  };
}

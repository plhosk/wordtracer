import { type DictionaryLetterFile } from './types.js';

export interface DictionaryEntry {
  canonical: string;
  definition: string;
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
  const definition = letterData.definitions[canonical];
  if (typeof definition !== 'string' || definition.trim().length === 0) {
    return null;
  }
  return { canonical, definition };
}

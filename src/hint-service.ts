import { type Level, type DictionaryLetterFile } from './types.js';
import {
  type DictionaryEntry,
  type DictionaryLookup,
  type DictionaryHintRelatedForms,
} from './dictionary.js';

const HINT_TARGET_LENGTH = 60;

export interface HintExcerpt {
  text: string;
  truncatedStart: boolean;
  truncatedEnd: boolean;
}

export interface HintResult {
  canonical: string;
  excerpt: HintExcerpt;
}

export function canonicalHasUnsolvedWords(
  level: Level,
  solvedWords: Set<string>,
  lookup: DictionaryLookup,
  canonical: string
): boolean {
  for (const answer of level.answers) {
    if (solvedWords.has(answer.text)) {
      continue;
    }
    const wordCanonical = lookup[answer.text];
    if (wordCanonical === canonical) {
      return true;
    }
  }
  return false;
}

export function getWordsToAvoidInHint(
  canonical: string,
  lookup: DictionaryLookup,
  level: Level,
  solvedWords: Set<string>,
  hintRelatedForms: DictionaryHintRelatedForms
): string[] {
  const words = new Set<string>();
  const normalizedCanonical = canonical.toLowerCase();

  words.add(normalizedCanonical);

  for (const related of hintRelatedForms[normalizedCanonical] ?? []) {
    words.add(related.toLowerCase());
  }

  for (const [word, wordCanonical] of Object.entries(lookup)) {
    if (wordCanonical === normalizedCanonical) {
      words.add(word.toLowerCase());
    }
  }

  for (const answer of level.answers) {
    if (!solvedWords.has(answer.text)) {
      const wordCanonical = lookup[answer.text];
      if (wordCanonical === normalizedCanonical) {
        words.add(answer.text.toLowerCase());
      }
    }
  }

  return [...words];
}

export function findDefinitionBoundary(
  definition: string,
  startPos: number,
  endPos: number
): number {
  const regex = /\d+\.\s/g;
  regex.lastIndex = startPos;
  const match = regex.exec(definition);
  if (match && match.index < endPos) {
    return match.index;
  }
  return -1;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function maskSpoilerWords(text: string, wordsToAvoid: string[]): string {
  let output = text;
  const replacement = '[redacted]';
  const uniqueWords = [...new Set(wordsToAvoid.filter((word) => word.length >= 2))].sort(
    (a, b) => b.length - a.length
  );

  for (const word of uniqueWords) {
    const pattern = new RegExp(`(^|[^a-z])(${escapeRegExp(word)})(?=$|[^a-z])`, 'gi');
    output = output.replace(pattern, (_full, prefix) => `${prefix}${replacement}`);
  }

  return output;
}

export function sanitizeHintExcerpt(
  definition: string,
  wordsToAvoid: string[]
): HintExcerpt {
  let def = definition;
  const targetLength = HINT_TARGET_LENGTH;
  const listSearchLimit = targetLength * 2;

  const listStart = def.slice(0, listSearchLimit).indexOf('1. ');
  if (listStart !== -1) {
    def = def.slice(listStart);
  }

  const lowerDef = def.toLowerCase();

  let hasSpoilers = false;
  for (const word of wordsToAvoid) {
    if (word.length >= 2 && lowerDef.includes(word)) {
      hasSpoilers = true;
      break;
    }
  }

  if (def.length <= targetLength) {
    if (!hasSpoilers) {
      return { text: def.trim(), truncatedStart: false, truncatedEnd: false };
    }
    const masked = maskSpoilerWords(def, wordsToAvoid).trim();
    return { text: masked, truncatedStart: false, truncatedEnd: false };
  }

  if (!hasSpoilers) {
    return buildExcerpt(def, 0, targetLength, false);
  }

  let startIndex = 0;
  let iterations = 0;
  const maxIterations = 100;

  while (startIndex <= def.length - targetLength && iterations < maxIterations) {
    iterations++;

    let foundSpoiler = false;
    for (const word of wordsToAvoid) {
      if (word.length < 2) continue;
      const wordIndex = lowerDef.indexOf(word, startIndex);
      if (wordIndex !== -1 && wordIndex < startIndex + targetLength) {
        startIndex = wordIndex + word.length + 1;
        foundSpoiler = true;
        break;
      }
    }

    if (!foundSpoiler) {
      if (startIndex > 0) {
        let firstSpoilerStart = def.length;
        for (const word of wordsToAvoid) {
          if (word.length < 2) continue;
          const wordIndex = lowerDef.indexOf(word);
          if (wordIndex !== -1 && wordIndex < firstSpoilerStart) {
            firstSpoilerStart = wordIndex;
          }
        }

        const hasNumberedList = /\d+\.\s/.test(def);
        if (!hasNumberedList && firstSpoilerStart >= targetLength / 2) {
          return buildExcerpt(def, 0, firstSpoilerStart, false);
        }

        const boundaryPos = findDefinitionBoundary(def, startIndex, def.length);
        if (boundaryPos !== -1 && boundaryPos < startIndex + targetLength * 4) {
          let isClean = true;
          for (const word of wordsToAvoid) {
            if (word.length < 2) continue;
            const wordIndex = lowerDef.indexOf(word, boundaryPos);
            if (wordIndex !== -1 && wordIndex < boundaryPos + targetLength) {
              isClean = false;
              break;
            }
          }
          if (isClean) {
            startIndex = boundaryPos;
          }
        }
      }
      return buildExcerpt(def, startIndex, targetLength, startIndex > 0);
    }
  }

  const hasNumberedList = /\d+\.\s/.test(def);
  let firstSpoilerStart = def.length;
  for (const word of wordsToAvoid) {
    if (word.length < 2) continue;
    const wordIndex = lowerDef.indexOf(word);
    if (wordIndex !== -1 && wordIndex < firstSpoilerStart) {
      firstSpoilerStart = wordIndex;
    }
  }

  if (!hasNumberedList && firstSpoilerStart >= targetLength / 2) {
    return buildExcerpt(def, 0, firstSpoilerStart, false);
  }

  const spoilerRanges: Array<{ start: number; end: number }> = [];
  for (const word of wordsToAvoid) {
    if (word.length < 2) continue;
    let pos = 0;
    while (pos < def.length) {
      const wordIndex = lowerDef.indexOf(word, pos);
      if (wordIndex === -1) break;
      spoilerRanges.push({ start: wordIndex, end: wordIndex + word.length });
      pos = wordIndex + 1;
    }
  }

  spoilerRanges.sort((a, b) => a.start - b.start);

  const mergedSpoilers: Array<{ start: number; end: number }> = [];
  for (const spoiler of spoilerRanges) {
    if (mergedSpoilers.length === 0 || mergedSpoilers[mergedSpoilers.length - 1].end < spoiler.start) {
      mergedSpoilers.push({ ...spoiler });
    } else {
      mergedSpoilers[mergedSpoilers.length - 1].end = Math.max(
        mergedSpoilers[mergedSpoilers.length - 1].end,
        spoiler.end
      );
    }
  }

  const cleanRegions: Array<{ start: number; end: number }> = [];
  let lastEnd = 0;
  for (const spoiler of mergedSpoilers) {
    if (spoiler.start > lastEnd) {
      cleanRegions.push({ start: lastEnd, end: spoiler.start });
    }
    lastEnd = Math.max(lastEnd, spoiler.end);
  }
  if (lastEnd < def.length) {
    cleanRegions.push({ start: lastEnd, end: def.length });
  }

  let bestRegion = cleanRegions[0] ?? { start: 0, end: def.length };
  for (const region of cleanRegions) {
    if (region.end - region.start > bestRegion.end - bestRegion.start) {
      bestRegion = region;
    }
  }

  let regionStart = bestRegion.start;
  if (regionStart > 0) {
    const boundaryPos = findDefinitionBoundary(def, regionStart, bestRegion.end);
    if (boundaryPos !== -1) {
      regionStart = boundaryPos;
    }
  }

  const excerpt = def.slice(regionStart, bestRegion.end).trim();
  const truncatedStart = regionStart > 0;
  const truncatedEnd = bestRegion.end < def.length;

  return { text: excerpt, truncatedStart, truncatedEnd };
}

export function buildExcerpt(
  definition: string,
  startIndex: number,
  targetLength: number,
  truncatedStart: boolean
): HintExcerpt {
  let excerpt = definition.slice(startIndex);
  let truncatedEnd = false;

  if (excerpt.length > targetLength) {
    const lastSpace = excerpt.lastIndexOf(' ', targetLength);
    if (lastSpace > targetLength / 2) {
      excerpt = excerpt.slice(0, lastSpace);
    } else {
      excerpt = excerpt.slice(0, targetLength);
    }
    truncatedEnd = true;
  }

  excerpt = excerpt.trim();

  return { text: excerpt, truncatedStart, truncatedEnd };
}

export async function getUnguessedWordHint(
  level: Level,
  solvedWords: Set<string>,
  excludedCanonicals: Set<string>,
  currentHintCanonical: string | null,
  lookup: DictionaryLookup,
  hintRelatedForms: DictionaryHintRelatedForms,
  loadEntry: (word: string) => Promise<DictionaryEntry | null>,
  loadLetterFile: (letter: string) => Promise<DictionaryLetterFile>
): Promise<HintResult | null> {
  if (currentHintCanonical && canonicalHasUnsolvedWords(level, solvedWords, lookup, currentHintCanonical)) {
    const letterData = await loadLetterFile(currentHintCanonical[0]);
    const definition = letterData.definitions[currentHintCanonical];
    if (definition) {
      const wordsToAvoid = getWordsToAvoidInHint(
        currentHintCanonical,
        lookup,
        level,
        solvedWords,
        hintRelatedForms
      );
      const excerpt = sanitizeHintExcerpt(definition, wordsToAvoid);
      return { canonical: currentHintCanonical, excerpt };
    }
  }

  for (const answer of level.answers) {
    if (solvedWords.has(answer.text)) {
      continue;
    }
    const entry = await loadEntry(answer.text);
    if (!entry) {
      continue;
    }
    if (excludedCanonicals.has(entry.canonical)) {
      continue;
    }
    if (entry.canonical === currentHintCanonical) {
      continue;
    }
    const wordsToAvoid = getWordsToAvoidInHint(
      entry.canonical,
      lookup,
      level,
      solvedWords,
      hintRelatedForms
    );
    const excerpt = sanitizeHintExcerpt(entry.definition, wordsToAvoid);
    return { canonical: entry.canonical, excerpt };
  }

  return null;
}

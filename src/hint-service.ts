import { type Level, type DictionaryLetterFile } from './types.js';
import {
  type DictionaryEntry,
  type DictionaryLookup,
  type DictionaryHintRelatedForms,
  getDictionaryEntryByCanonical,
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

export function findDoubleLineBreak(
  definition: string,
  startPos: number,
  searchLimit: number,
  noRepeatLimit: number
): number {
  const searchEnd = Math.min(startPos + searchLimit, definition.length);
  const doubleBreak = definition.indexOf('\n\n', startPos);
  if (doubleBreak === -1 || doubleBreak >= searchEnd) {
    return -1;
  }
  const afterBreak = doubleBreak + 2;
  const repeatEnd = Math.min(afterBreak + noRepeatLimit, definition.length);
  const nextBreak = definition.indexOf('\n\n', afterBreak);
  if (nextBreak !== -1 && nextBreak < repeatEnd) {
    return -1;
  }
  return afterBreak;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

interface SpoilerMatch {
  index: number;
  length: number;
}

function findSpoilerWithBoundary(
  text: string,
  wordsToAvoid: string[],
  startPos: number,
  endPos: number
): SpoilerMatch | null {
  const uniqueWords = [...new Set(wordsToAvoid.filter((w) => w.length >= 2))];
  let earliest: SpoilerMatch | null = null;

  for (const word of uniqueWords) {
    const pattern = new RegExp(`(^|[^a-z])(${escapeRegExp(word)})(?=$|[^a-z])`, 'gi');
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const wordStart = match.index + match[1].length;

      if (wordStart >= startPos && wordStart < endPos) {
        if (!earliest || wordStart < earliest.index) {
          earliest = { index: wordStart, length: match[2].length };
        }
      }

      if (pattern.lastIndex <= match.index) {
        pattern.lastIndex = match.index + 1;
      }
    }
  }

  return earliest;
}

function findFirstSpoiler(text: string, wordsToAvoid: string[]): SpoilerMatch | null {
  return findSpoilerWithBoundary(text, wordsToAvoid, 0, text.length);
}

function findAllSpoilers(text: string, wordsToAvoid: string[]): Array<{ start: number; end: number }> {
  const ranges: Array<{ start: number; end: number }> = [];
  const uniqueWords = [...new Set(wordsToAvoid.filter((w) => w.length >= 2))];

  for (const word of uniqueWords) {
    const pattern = new RegExp(`(^|[^a-z])(${escapeRegExp(word)})(?=$|[^a-z])`, 'gi');
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const wordStart = match.index + match[1].length;
      const wordEnd = wordStart + match[2].length;
      ranges.push({ start: wordStart, end: wordEnd });

      if (pattern.lastIndex <= match.index) {
        pattern.lastIndex = match.index + 1;
      }
    }
  }

  return ranges;
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

function getNumberedSectionStarts(text: string): number[] {
  const starts: number[] = [];
  const pattern = /(?:^|\n)(\d+\.\s)/g;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    const start = match.index + (match[0].length - match[1].length);
    starts.push(start);
    if (pattern.lastIndex <= match.index) {
      pattern.lastIndex = match.index + 1;
    }
  }

  return starts;
}

function normalizeHintText(text: string): string {
  return text.replace(/^\d+\.\s*/, '').trim();
}

function isCrossReferenceHint(text: string): boolean {
  const normalized = normalizeHintText(text).toLowerCase();
  return /^(see|same as)\b/.test(normalized)
    || /^(l\.\s*pl\.|imp\.|p\.\s*p\.|imp\.\s*&\s*p\.\s*p\.)\s*of\b/.test(normalized);
}

function isRejectedHint(excerpt: HintExcerpt): boolean {
  const text = excerpt.text.trim();
  if (!text) {
    return true;
  }

  if (isCrossReferenceHint(text)) {
    return true;
  }

  if (/\[redacted\]/i.test(text)) {
    const remainingLetters = text
      .replace(/\[redacted\]/gi, ' ')
      .replace(/[^a-z]/gi, '');
    if (remainingLetters.length < 4) {
      return true;
    }
  }

  return false;
}

function scoreHintExcerpt(excerpt: HintExcerpt): number {
  const text = excerpt.text.trim();
  if (text.length === 0) {
    return -1000;
  }

  let score = 0;
  score += Math.min(text.length, 80) / 10;

  if (excerpt.truncatedStart) score -= 8;
  if (excerpt.truncatedEnd) score -= 1;
  if (isCrossReferenceHint(text)) score -= 40;
  if (/\[redacted\]/i.test(text)) score -= 25;
  if (/\[(obs\.|r\.|scot\.|n\. of eng)/i.test(text)) score -= 20;

  const normalized = normalizeHintText(text);
  if (/^[a-z(]/.test(normalized) || /^or\b/i.test(normalized)) score -= 6;
  if (/"\s*$/.test(text) || /\b(as|a|an|the|of|to|and|or)\s*$/i.test(text)) score -= 8;
  if (/[.!?;)]$/.test(text)) score += 2;

  return score;
}

function passesModernHintQualityCheck(excerpt: HintExcerpt): boolean {
  if (isRejectedHint(excerpt)) {
    return false;
  }
  if (excerpt.truncatedStart) {
    return false;
  }
  return scoreHintExcerpt(excerpt) >= -8;
}

function chooseHintExcerpt(
  entry: DictionaryEntry,
  wordsToAvoid: string[],
  preferModernHints: boolean
): HintExcerpt | null {
  const selectedExcerpt = sanitizeHintExcerpt(entry.definition, wordsToAvoid);
  if (!preferModernHints) {
    return isRejectedHint(selectedExcerpt) ? null : selectedExcerpt;
  }

  const wordnetDefinition = entry.definitions.wordnet;
  if (wordnetDefinition) {
    const modernExcerpt = sanitizeHintExcerpt(wordnetDefinition, wordsToAvoid);
    if (passesModernHintQualityCheck(modernExcerpt)) {
      return modernExcerpt;
    }
  }

  return isRejectedHint(selectedExcerpt) ? null : selectedExcerpt;
}

function sanitizeHintExcerptCore(
  definition: string,
  wordsToAvoid: string[]
): HintExcerpt {
  let def = definition;
  const targetLength = HINT_TARGET_LENGTH;
  const listSearchLimit = targetLength * 4;

  // Only slice to numbered definition if it starts at line beginning
  const listMatch = def.slice(0, listSearchLimit).match(/(?:^|\n)(1\. )/);
  if (listMatch) {
    const listStart = listMatch.index! + (listMatch[0].length - listMatch[1].length);
    def = def.slice(listStart);
  }

  const firstSpoiler = findFirstSpoiler(def, wordsToAvoid);
  const hasSpoilers = firstSpoiler !== null;

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

    const spoiler = findSpoilerWithBoundary(def, wordsToAvoid, startIndex, startIndex + targetLength);
    if (spoiler) {
      startIndex = spoiler.index + spoiler.length + 1;
    } else {
      if (startIndex > 0) {
        const firstSpoilerPos = findFirstSpoiler(def, wordsToAvoid);
        const firstSpoilerStart = firstSpoilerPos ? firstSpoilerPos.index : def.length;

        const textBeforeSpoiler = def.slice(0, firstSpoilerStart).trim();
        if (firstSpoilerStart >= targetLength / 2) {
          return { text: textBeforeSpoiler, truncatedStart: false, truncatedEnd: true };
        }

        let boundaryPos = findDefinitionBoundary(def, startIndex, def.length);
        if (boundaryPos === -1) {
          boundaryPos = findDoubleLineBreak(def, startIndex, targetLength * 2, targetLength * 4);
        }
        if (boundaryPos !== -1 && boundaryPos < startIndex + targetLength * 4) {
          const spoilerAtBoundary = findSpoilerWithBoundary(def, wordsToAvoid, boundaryPos, boundaryPos + targetLength);
          if (!spoilerAtBoundary) {
            startIndex = boundaryPos;
          }
        }
      }
      return buildExcerpt(def, startIndex, targetLength, startIndex > 0);
    }
  }

  const firstSpoilerPos = findFirstSpoiler(def, wordsToAvoid);
  const firstSpoilerStart = firstSpoilerPos ? firstSpoilerPos.index : def.length;

  if (firstSpoilerStart >= targetLength / 2) {
    const textBeforeSpoiler = def.slice(0, firstSpoilerStart).trim();
    return { text: textBeforeSpoiler, truncatedStart: false, truncatedEnd: true };
  }

  const spoilerRanges = findAllSpoilers(def, wordsToAvoid);

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
    let boundaryPos = findDefinitionBoundary(def, regionStart, bestRegion.end);
    if (boundaryPos === -1) {
      boundaryPos = findDoubleLineBreak(def, regionStart, targetLength * 2, targetLength * 4);
    }
    if (boundaryPos !== -1) {
      regionStart = boundaryPos;
    }
  }

  let excerpt = def.slice(regionStart, bestRegion.end).trim();
  const truncatedStart = regionStart > 0;
  const truncatedEnd = bestRegion.end < def.length;

  // Strip leading punctuation when starting mid-sentence
  if (truncatedStart) {
    const numberedPrefix = excerpt.match(/^(\d+\.\s)/);
    if (numberedPrefix) {
      excerpt = numberedPrefix[1] + excerpt.slice(numberedPrefix[1].length).replace(/^[,;:\-.–—\s]+/, '');
    } else {
      excerpt = excerpt.replace(/^[,;:\-.–—\s]+/, '');
    }
  }

  return { text: excerpt, truncatedStart, truncatedEnd };
}

export function sanitizeHintExcerpt(
  definition: string,
  wordsToAvoid: string[]
): HintExcerpt {
  let def = definition;
  const listSearchLimit = HINT_TARGET_LENGTH * 4;

  const listMatch = def.slice(0, listSearchLimit).match(/(?:^|\n)(1\. )/);
  if (listMatch) {
    const listStart = listMatch.index! + (listMatch[0].length - listMatch[1].length);
    def = def.slice(listStart);
  }

  const numberedStarts = getNumberedSectionStarts(def)
    .filter((start) => start > 0)
    .slice(0, 8);
  const candidateStarts = [0, ...numberedStarts];

  let bestExcerpt = sanitizeHintExcerptCore(def, wordsToAvoid);
  let bestScore = scoreHintExcerpt(bestExcerpt);

  for (const start of candidateStarts) {
    if (start === 0) {
      continue;
    }

    const excerpt = sanitizeHintExcerptCore(def.slice(start), wordsToAvoid);
    const score = scoreHintExcerpt(excerpt);
    if (score > bestScore) {
      bestExcerpt = excerpt;
      bestScore = score;
    }
  }

  return bestExcerpt;
}

export function buildExcerpt(
  definition: string,
  startIndex: number,
  targetLength: number,
  truncatedStart: boolean
): HintExcerpt {
  let excerpt = definition.slice(startIndex);
  let truncatedEnd = false;

  // Strip leading punctuation when starting mid-sentence
  if (truncatedStart) {
    // Keep numbered prefixes like "1. " or "2. "
    const numberedPrefix = excerpt.match(/^(\d+\.\s)/);
    if (numberedPrefix) {
      excerpt = numberedPrefix[1] + excerpt.slice(numberedPrefix[1].length).replace(/^[,;:\-.–—\s]+/, '');
    } else {
      excerpt = excerpt.replace(/^[,;:\-.–—\s]+/, '');
    }
  }

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
  loadLetterFile: (letter: string) => Promise<DictionaryLetterFile>,
  preferModernHints = false
): Promise<HintResult | null> {
  if (currentHintCanonical && canonicalHasUnsolvedWords(level, solvedWords, lookup, currentHintCanonical)) {
    const letterData = await loadLetterFile(currentHintCanonical[0]);
    const entry = getDictionaryEntryByCanonical(letterData, currentHintCanonical);
    if (entry) {
      const wordsToAvoid = getWordsToAvoidInHint(
        currentHintCanonical,
        lookup,
        level,
        solvedWords,
        hintRelatedForms
      );
      const excerpt = chooseHintExcerpt(entry, wordsToAvoid, preferModernHints);
      if (excerpt) {
        return { canonical: currentHintCanonical, excerpt };
      }
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
    const excerpt = chooseHintExcerpt(entry, wordsToAvoid, preferModernHints);
    if (excerpt) {
      return { canonical: entry.canonical, excerpt };
    }
  }

  return null;
}

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from common import load_json, normalize_word, now_iso, project_path, save_json

try:
    import lemminflect
    from lemminflect import getAllInflections, getAllLemmas, getLemma
except ImportError as error:  # pragma: no cover - surfaced as CLI error
    raise SystemExit(
        "Missing dependency: lemminflect. Run `uv sync` in the project root to install dependencies."
    ) from error


def load_licenses() -> list[dict]:
    licenses_path = project_path("data", "raw", "LICENSES.json")
    data = load_json(licenses_path)
    return data if isinstance(data, list) else []


def filter_licenses_for_dictionary(
    licenses: list[dict], dictionary_license_ids: set[str]
) -> list[dict]:
    return [
        {"name": item["name"], "url": item["url"], "license": item["license"]}
        for item in licenses
        if item["id"] in dictionary_license_ids
    ]


def infer_dictionary_license_id(path: Path) -> str | None:
    normalized = str(path).lower()
    if "webster" in normalized:
        return "webster"
    if "wordnet" in normalized:
        return "wordnet"
    return None


def infer_definition_source_key(raw: str) -> str | None:
    return infer_dictionary_license_id(Path(raw))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a compact dictionary lookup bundle for solution and bonus words."
        )
    )
    parser.add_argument(
        "--bundle",
        help="Path to levels.bundle.json (reads from bundle instead of split files).",
    )
    parser.add_argument(
        "--levels-dir",
        default=str(project_path("src", "data")),
        help="Directory containing levels._meta.json and level group files (fallback if --bundle not provided).",
    )
    parser.add_argument(
        "--dictionary",
        default=str(project_path("data", "raw", "webster", "webster.json")),
        help="Path to source dictionary JSON.",
    )
    parser.add_argument(
        "--fallback-dictionary",
        action="append",
        default=[],
        help="Fallback dictionary JSON path (repeatable, checked after --dictionary).",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="Output split files: dictionary._meta.json + dictionary.{letter}.json per letter.",
    )
    parser.add_argument(
        "--split-dir",
        default=str(project_path("src", "data")),
        help="Directory for split output files (used with --split).",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def path_for_meta(path: Path) -> str:
    root = project_path()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def collect_lookup_words_from_bundle(bundle_path: Path) -> set[str]:
    """Collect solution and bonus words from levels.bundle.json."""
    if not bundle_path.exists():
        raise SystemExit(f"Bundle not found: {bundle_path}")

    payload = load_json(bundle_path)
    levels = payload.get("levels", [])
    if not isinstance(levels, list):
        raise SystemExit("Invalid bundle: expected 'levels' list")

    words: set[str] = set()

    for level in levels:
        if not isinstance(level, dict):
            continue

        for answer in level.get("answers", []):
            if not isinstance(answer, dict):
                continue
            normalized = normalize_word(str(answer.get("text", "")))
            if normalized:
                words.add(normalized)

        for bonus_word in level.get("bonusWords", []):
            normalized = normalize_word(str(bonus_word))
            if normalized:
                words.add(normalized)

    return words


def collect_lookup_words_from_split_files(levels_dir: Path) -> set[str]:
    meta_path = levels_dir / "levels._meta.json"
    if not meta_path.exists():
        raise SystemExit(f"Levels meta not found: {meta_path}")

    meta = load_json(meta_path)
    groups = meta.get("groups", [])
    if not isinstance(groups, list):
        raise SystemExit("Invalid levels._meta.json: expected 'groups' list")

    words: set[str] = set()

    for group in groups:
        if not isinstance(group, dict):
            continue
        file_name = group.get("file")
        if not file_name:
            continue

        group_path = levels_dir / file_name
        if not group_path.exists():
            print(f"Warning: Group file not found: {group_path}")
            continue

        group_data = load_json(group_path)
        levels = group_data.get("levels", [])
        if not isinstance(levels, list):
            continue

        for level in levels:
            if not isinstance(level, dict):
                continue

            for answer in level.get("answers", []):
                if not isinstance(answer, dict):
                    continue
                normalized = normalize_word(str(answer.get("text", "")))
                if normalized:
                    words.add(normalized)

            for bonus_word in level.get("bonusWords", []):
                normalized = normalize_word(str(bonus_word))
                if normalized:
                    words.add(normalized)

    return words


def load_dictionary(path: Path) -> dict[str, str]:
    dictionary_payload = load_json(path)
    if not isinstance(dictionary_payload, dict):
        raise SystemExit(f"Dictionary JSON must be an object: {path}")

    dictionary: dict[str, str] = {}
    for key, value in dictionary_payload.items():
        normalized = normalize_word(str(key))
        if not normalized:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                dictionary[normalized] = cleaned

    return dictionary


def iter_normalized_forms(raw_values: object) -> set[str]:
    forms: set[str] = set()
    if isinstance(raw_values, dict):
        values = raw_values.values()
    else:
        values = []

    for item in values:
        if isinstance(item, str):
            normalized = normalize_word(item)
            if normalized:
                forms.add(normalized)
            continue
        if not isinstance(item, (list, tuple, set)):
            continue
        for value in item:
            normalized = normalize_word(str(value))
            if normalized:
                forms.add(normalized)
    return forms


def collect_related_forms(word: str) -> set[str]:
    related = {word}

    direct_lemmas = iter_normalized_forms(getAllLemmas(word))
    direct_inflections = iter_normalized_forms(getAllInflections(word))
    related.update(direct_lemmas)
    related.update(direct_inflections)

    for lemma in direct_lemmas:
        related.update(iter_normalized_forms(getAllInflections(lemma)))

    return related


COMMON_SUFFIXES = (
    "iest",
    "ing",
    "ier",
    "est",
    "ers",
    "er",
    "ed",
    "es",
    "s",
)

HINT_TARGET_LENGTH = 60
HINT_MAX_TARGET_LENGTH = int(HINT_TARGET_LENGTH * 1.5)
HINT_REASON_CROSSREF = "crossref"
HINT_REASON_REDACTED_ONLY = "redacted_only"
HINT_REASON_BAD_START = "bad_start"


@dataclass(frozen=True)
class HintPreview:
    text: str
    start_index: int
    truncated_start: bool
    truncated_end: bool
    definition: str


def unique_hint_words(words: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in words:
        normalized = normalize_word(raw)
        if not normalized or len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def find_spoiler_with_boundary(
    text: str,
    words_to_avoid: list[str],
    start_pos: int,
    end_pos: int,
) -> tuple[int, int] | None:
    earliest: tuple[int, int] | None = None
    for word in unique_hint_words(words_to_avoid):
        pattern = re.compile(
            rf"(^|[^a-z])({re.escape(word)})(?=$|[^a-z])",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            start = match.start(2)
            if start < start_pos or start >= end_pos:
                continue
            length = len(match.group(2))
            if earliest is None or start < earliest[0]:
                earliest = (start, length)
    return earliest


def find_first_spoiler(text: str, words_to_avoid: list[str]) -> tuple[int, int] | None:
    return find_spoiler_with_boundary(text, words_to_avoid, 0, len(text))


def find_all_spoilers(text: str, words_to_avoid: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for word in unique_hint_words(words_to_avoid):
        pattern = re.compile(
            rf"(^|[^a-z])({re.escape(word)})(?=$|[^a-z])",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            start = match.start(2)
            end = start + len(match.group(2))
            ranges.append((start, end))
    return ranges


def mask_spoiler_words(text: str, words_to_avoid: list[str]) -> str:
    output = text
    replacement = "[redacted]"
    for word in sorted(unique_hint_words(words_to_avoid), key=len, reverse=True):
        pattern = re.compile(
            rf"(^|[^a-z])({re.escape(word)})(?=$|[^a-z])",
            flags=re.IGNORECASE,
        )
        output = pattern.sub(lambda match: f"{match.group(1)}{replacement}", output)
    return output


def find_definition_boundary(definition: str, start_pos: int, end_pos: int) -> int:
    for match in re.finditer(r"\d+\.\s", definition[start_pos:end_pos]):
        return start_pos + match.start()
    return -1


def find_double_line_break(
    definition: str,
    start_pos: int,
    search_limit: int,
    no_repeat_limit: int,
) -> int:
    search_end = min(start_pos + search_limit, len(definition))
    double_break = definition.find("\n\n", start_pos)
    if double_break == -1 or double_break >= search_end:
        return -1
    after_break = double_break + 2
    repeat_end = min(after_break + no_repeat_limit, len(definition))
    next_break = definition.find("\n\n", after_break)
    if next_break != -1 and next_break < repeat_end:
        return -1
    return after_break


def strip_mid_sentence_prefix(excerpt: str) -> str:
    numbered_match = re.match(r"^(\d+\.\s)", excerpt)
    if numbered_match:
        prefix = numbered_match.group(1)
        body = re.sub(r"^[,;:\-.–—\s]+", "", excerpt[len(prefix) :])
        return f"{prefix}{body}"
    return re.sub(r"^[,;:\-.–—\s]+", "", excerpt)


def build_excerpt(
    definition: str,
    start_index: int,
    target_length: int,
    truncated_start: bool,
) -> HintPreview:
    excerpt = definition[start_index:]
    truncated_end = False

    if truncated_start:
        excerpt = strip_mid_sentence_prefix(excerpt)

    if len(excerpt) > target_length:
        last_space = excerpt.rfind(" ", 0, target_length + 1)
        if last_space > target_length / 2:
            excerpt = excerpt[:last_space]
        else:
            excerpt = excerpt[:target_length]
        truncated_end = True

    return HintPreview(
        text=excerpt.strip(),
        start_index=start_index,
        truncated_start=truncated_start,
        truncated_end=truncated_end,
        definition=definition,
    )


def build_hint_preview_meta(definition: str, words_to_avoid: list[str]) -> HintPreview:
    text = definition
    target_length = HINT_TARGET_LENGTH
    list_search_limit = target_length * 4

    list_match = re.search(r"(?:^|\n)(1\. )", text[:list_search_limit])
    if list_match:
        list_start = list_match.start(1)
        text = text[list_start:]

    first_spoiler = find_first_spoiler(text, words_to_avoid)
    has_spoilers = first_spoiler is not None

    if len(text) <= target_length:
        if not has_spoilers:
            return HintPreview(
                text=text.strip(),
                start_index=0,
                truncated_start=False,
                truncated_end=False,
                definition=text,
            )
        masked = mask_spoiler_words(text, words_to_avoid).strip()
        return HintPreview(
            text=masked,
            start_index=0,
            truncated_start=False,
            truncated_end=False,
            definition=text,
        )

    if not has_spoilers:
        return build_excerpt(text, 0, target_length, False)

    start_index = 0
    iterations = 0
    max_iterations = 100

    while start_index <= len(text) - target_length and iterations < max_iterations:
        iterations += 1

        spoiler = find_spoiler_with_boundary(
            text,
            words_to_avoid,
            start_index,
            start_index + target_length,
        )
        if spoiler is not None:
            start_index = spoiler[0] + spoiler[1] + 1
            continue

        if start_index > 0:
            first_spoiler_pos = find_first_spoiler(text, words_to_avoid)
            first_spoiler_start = (
                first_spoiler_pos[0] if first_spoiler_pos else len(text)
            )
            text_before_spoiler = text[:first_spoiler_start].strip()
            if first_spoiler_start >= target_length / 2:
                return HintPreview(
                    text=text_before_spoiler,
                    start_index=0,
                    truncated_start=False,
                    truncated_end=True,
                    definition=text,
                )

            boundary_pos = find_definition_boundary(text, start_index, len(text))
            if boundary_pos == -1:
                boundary_pos = find_double_line_break(
                    text,
                    start_index,
                    target_length * 2,
                    target_length * 4,
                )
            if boundary_pos != -1 and boundary_pos < start_index + target_length * 4:
                spoiler_at_boundary = find_spoiler_with_boundary(
                    text,
                    words_to_avoid,
                    boundary_pos,
                    boundary_pos + target_length,
                )
                if spoiler_at_boundary is None:
                    start_index = boundary_pos

        next_spoiler = find_spoiler_with_boundary(
            text,
            words_to_avoid,
            start_index,
            len(text),
        )
        spoiler_free_length = (
            next_spoiler[0] - start_index if next_spoiler else len(text) - start_index
        )
        excerpt_length = min(
            HINT_MAX_TARGET_LENGTH,
            max(target_length, spoiler_free_length),
        )
        return build_excerpt(text, start_index, excerpt_length, start_index > 0)

    first_spoiler_pos = find_first_spoiler(text, words_to_avoid)
    first_spoiler_start = first_spoiler_pos[0] if first_spoiler_pos else len(text)
    if first_spoiler_start >= target_length / 2:
        text_before_spoiler = text[:first_spoiler_start].strip()
        return HintPreview(
            text=text_before_spoiler,
            start_index=0,
            truncated_start=False,
            truncated_end=True,
            definition=text,
        )

    spoiler_ranges = sorted(
        find_all_spoilers(text, words_to_avoid), key=lambda item: item[0]
    )
    merged_spoilers: list[tuple[int, int]] = []
    for start, end in spoiler_ranges:
        if not merged_spoilers or merged_spoilers[-1][1] < start:
            merged_spoilers.append((start, end))
        else:
            merged_spoilers[-1] = (
                merged_spoilers[-1][0],
                max(merged_spoilers[-1][1], end),
            )

    clean_regions: list[tuple[int, int]] = []
    last_end = 0
    for start, end in merged_spoilers:
        if start > last_end:
            clean_regions.append((last_end, start))
        last_end = max(last_end, end)
    if last_end < len(text):
        clean_regions.append((last_end, len(text)))

    best_region = clean_regions[0] if clean_regions else (0, len(text))
    for region in clean_regions:
        if region[1] - region[0] > best_region[1] - best_region[0]:
            best_region = region

    region_start = best_region[0]
    if region_start > 0:
        boundary_pos = find_definition_boundary(text, region_start, best_region[1])
        if boundary_pos == -1:
            boundary_pos = find_double_line_break(
                text,
                region_start,
                target_length * 2,
                target_length * 4,
            )
        if boundary_pos != -1:
            region_start = boundary_pos

    excerpt = text[region_start : best_region[1]].strip()
    truncated_start = region_start > 0
    truncated_end = best_region[1] < len(text)
    if truncated_start:
        excerpt = strip_mid_sentence_prefix(excerpt)

    return HintPreview(
        text=excerpt,
        start_index=region_start,
        truncated_start=truncated_start,
        truncated_end=truncated_end,
        definition=text,
    )


def build_hint_preview(definition: str, words_to_avoid: list[str]) -> str:
    return build_hint_preview_meta(definition, words_to_avoid).text


def normalize_hint_prefix(text: str) -> str:
    normalized = text.strip()
    while True:
        updated = re.sub(r"^\d+\.\s*", "", normalized)
        if updated == normalized:
            break
        normalized = updated
    return normalized.strip()


def has_bad_start_boundary(preview: HintPreview) -> bool:
    if preview.start_index <= 0:
        return False
    if (
        preview.start_index >= 2
        and preview.definition[preview.start_index - 2 : preview.start_index] == "\n\n"
    ):
        return False
    if re.match(r"\d+\.\s", preview.definition[preview.start_index :]):
        return False
    return True


def score_hint_preview(preview_or_text: HintPreview | str) -> tuple[float, set[str]]:
    if isinstance(preview_or_text, HintPreview):
        preview = preview_or_text
        text = preview.text
    else:
        preview = None
        text = preview_or_text

    normalized = normalize_hint_prefix(text)
    lowered = normalized.lower()
    reasons: set[str] = set()

    if re.match(r"^(see|same as)\b", lowered):
        reasons.add(HINT_REASON_CROSSREF)
    if re.match(r"^(l\.\s*pl\.|imp\.|p\.\s*p\.|imp\.\s*&\s*p\.\s*p\.)\s*of\b", lowered):
        reasons.add(HINT_REASON_CROSSREF)

    if "[redacted]" in lowered:
        remaining_letters = re.sub(r"[^a-z]", "", lowered.replace("[redacted]", " "))
        if len(remaining_letters) < 4:
            reasons.add(HINT_REASON_REDACTED_ONLY)

    if preview and has_bad_start_boundary(preview):
        reasons.add(HINT_REASON_BAD_START)

    score = min(len(normalized), 90) / 10
    if HINT_REASON_CROSSREF in reasons:
        score -= 45
    if HINT_REASON_REDACTED_ONLY in reasons:
        score -= 35
    if HINT_REASON_BAD_START in reasons:
        score -= 25
    if re.search(r"\[(obs\.|r\.|scot\.|n\. of eng)", text, flags=re.IGNORECASE):
        score -= 12
    if re.match(r"^[a-z(]", normalized) or re.match(r"^or\b", lowered):
        score -= 5
    if (not preview or not preview.truncated_end) and (
        re.search(r"\"\s*$", text)
        or re.search(r"\b(as|a|an|the|of|to|and|or)\s*$", text, flags=re.IGNORECASE)
    ):
        score -= 6
    if re.search(r"[.!?;)]$", text):
        score += 2

    return score, reasons


def simplified_forms(word: str) -> set[str]:
    forms = {word}
    current = word
    while True:
        stripped = None
        for suffix in COMMON_SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= 3:
                stripped = current[: -len(suffix)]
                break
        if not stripped:
            break
        if stripped in forms:
            break
        forms.add(stripped)
        current = stripped
    return forms


def common_prefix_len(a: str, b: str) -> int:
    max_len = min(len(a), len(b))
    idx = 0
    while idx < max_len and a[idx] == b[idx]:
        idx += 1
    return idx


def longest_common_subsequence_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    rows = len(a) + 1
    cols = len(b) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i in range(1, rows):
        for j in range(1, cols):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[-1][-1]


def has_stem_similarity(canonical: str, candidate: str) -> bool:
    for left in simplified_forms(canonical):
        for right in simplified_forms(candidate):
            if common_prefix_len(left, right) >= 3:
                return True
            if longest_common_subsequence_len(left, right) >= 3:
                return True
    return False


def build_lookup_data(
    dictionary_paths: list[Path],
    bundle_path: Path | None = None,
    levels_dir: Path | None = None,
) -> tuple[
    dict[str, str | None],
    dict[str, str],
    dict[str, dict[str, str]],
    dict[str, list[str]],
    list[str],
    int,
    int,
    dict[str, int],
    list[str],
]:
    dictionaries: list[tuple[str, dict[str, str]]] = []
    dictionary_sources: list[str] = []
    for path in dictionary_paths:
        dictionary = load_dictionary(path)
        if not dictionary:
            continue
        source = path_for_meta(path)
        dictionaries.append((source, dictionary))
        dictionary_sources.append(source)

    if not dictionaries:
        raise SystemExit("No usable dictionary entries found.")

    # Prefer bundle if provided, otherwise fall back to split files
    if bundle_path:
        lookup_words = collect_lookup_words_from_bundle(bundle_path)
    elif levels_dir:
        lookup_words = collect_lookup_words_from_split_files(levels_dir)
    else:
        raise SystemExit("Must provide either --bundle or --levels-dir")

    if not lookup_words:
        raise SystemExit("No solution/bonus words found in levels.")

    lookup: dict[str, str | None] = {}
    definitions: dict[str, str] = {}
    source_definitions: dict[str, dict[str, str]] = {}
    canonical_to_words: dict[str, set[str]] = {}
    canonical_definition_by_source: dict[str, dict[str, str]] = {}
    canonical_primary_source: dict[str, str] = {}
    unresolved: list[str] = []
    direct_match_count = 0
    lemma_match_count = 0
    fallback_match_count = 0

    def find_canonical(target_word: str) -> tuple[str, str] | None:
        for source, dictionary in dictionaries:
            if target_word in dictionary:
                return target_word, source
        return None

    for word in sorted(lookup_words):
        resolved = find_canonical(word)
        canonical = resolved[0] if resolved else None
        source = resolved[1] if resolved else None
        if canonical is None:
            for pos in ("VERB", "NOUN", "ADJ"):
                lemma = getLemma(word, pos)
                if lemma:
                    lemma_normalized = normalize_word(lemma[0])
                    if lemma_normalized:
                        resolved = find_canonical(lemma_normalized)
                        if resolved:
                            canonical = resolved[0]
                            source = resolved[1]
                            break

        if canonical is None:
            lookup[word] = None
            unresolved.append(word)
            continue

        lookup[word] = canonical
        canonical_to_words.setdefault(canonical, set()).add(word)
        if source and canonical not in canonical_primary_source:
            canonical_primary_source[canonical] = source
        source_map = canonical_definition_by_source.setdefault(canonical, {})
        for dictionary_source, dictionary in dictionaries:
            if canonical in dictionary:
                source_map[dictionary_source] = dictionary[canonical]
        if canonical == word:
            direct_match_count += 1
        else:
            lemma_match_count += 1
        if source != dictionaries[0][0]:
            fallback_match_count += 1

    match_stats = {
        "directMatchCount": direct_match_count,
        "lemmaMatchCount": lemma_match_count,
        "fallbackMatchCount": fallback_match_count,
    }

    hint_related_forms: dict[str, list[str]] = {}
    lookup_words = set(lookup)
    for canonical, words in canonical_to_words.items():
        related: set[str] = set(words)
        candidates: set[str] = set()
        for word in words:
            candidates.update(collect_related_forms(word))
        filtered = sorted(
            form
            for form in candidates
            if form in lookup_words
            and len(form) >= 3
            and has_stem_similarity(canonical, form)
        )
        hint_related_forms[canonical] = sorted(related.union(filtered))

    primary_definition_count = 0
    fallback_definition_selected_count = 0
    low_quality_replacement_count = 0
    bad_start_replacement_count = 0
    score_upgrade_replacement_count = 0
    webster_definition_available_count = 0
    wordnet_definition_available_count = 0

    for canonical in sorted(canonical_to_words):
        source_map = canonical_definition_by_source.get(canonical, {})
        if not source_map:
            continue

        primary_source = canonical_primary_source.get(canonical)
        if not primary_source or primary_source not in source_map:
            primary_source = next(iter(source_map.keys()))

        words_to_avoid = hint_related_forms.get(canonical, [canonical])
        if canonical not in words_to_avoid:
            words_to_avoid = [canonical, *words_to_avoid]

        primary_text = source_map[primary_source]
        primary_preview = build_hint_preview_meta(primary_text, words_to_avoid)
        primary_score, primary_reasons = score_hint_preview(primary_preview)

        best_source = primary_source
        best_score = primary_score
        for candidate_source, candidate_text in source_map.items():
            if candidate_source == primary_source:
                continue
            candidate_preview = build_hint_preview_meta(candidate_text, words_to_avoid)
            candidate_score, _ = score_hint_preview(candidate_preview)
            if candidate_score > best_score:
                best_source = candidate_source
                best_score = candidate_score

        selected_source = primary_source
        has_low_quality_reason = (
            HINT_REASON_CROSSREF in primary_reasons
            or HINT_REASON_REDACTED_ONLY in primary_reasons
            or HINT_REASON_BAD_START in primary_reasons
        )
        if best_source != primary_source:
            if has_low_quality_reason and best_score > primary_score:
                selected_source = best_source
                low_quality_replacement_count += 1
                if HINT_REASON_BAD_START in primary_reasons:
                    bad_start_replacement_count += 1
            elif best_score >= primary_score + 8:
                selected_source = best_source
                score_upgrade_replacement_count += 1

        definitions[canonical] = source_map[selected_source]

        source_payload: dict[str, str] = {}
        for source_name, source_text in source_map.items():
            source_key = infer_definition_source_key(source_name)
            if source_key in {"webster", "wordnet"}:
                source_payload[source_key] = source_text

        selected_source_key = infer_definition_source_key(selected_source)
        if selected_source_key in {"webster", "wordnet"}:
            source_payload["selectedSource"] = selected_source_key

        if source_payload:
            source_definitions[canonical] = source_payload
            if "webster" in source_payload:
                webster_definition_available_count += 1
            if "wordnet" in source_payload:
                wordnet_definition_available_count += 1

        if selected_source == primary_source:
            primary_definition_count += 1
        else:
            fallback_definition_selected_count += 1

    match_stats.update(
        {
            "primaryDefinitionCount": primary_definition_count,
            "fallbackDefinitionSelectedCount": fallback_definition_selected_count,
            "lowQualityReplacementCount": low_quality_replacement_count,
            "badStartReplacementCount": bad_start_replacement_count,
            "scoreUpgradeReplacementCount": score_upgrade_replacement_count,
            "websterDefinitionAvailableCount": webster_definition_available_count,
            "wordnetDefinitionAvailableCount": wordnet_definition_available_count,
        }
    )

    return (
        lookup,
        definitions,
        source_definitions,
        hint_related_forms,
        unresolved,
        direct_match_count,
        lemma_match_count,
        match_stats,
        dictionary_sources,
    )


def write_split_files(
    split_dir: Path,
    source_path: Path,
    dictionary_paths: list[Path],
    lookup: dict[str, str | None],
    source_definitions: dict[str, dict[str, str]],
    hint_related_forms: dict[str, list[str]],
    unresolved: list[str],
    direct_match_count: int,
    lemma_match_count: int,
    match_stats: dict[str, int],
    dictionary_sources: list[str],
) -> None:
    split_dir.mkdir(parents=True, exist_ok=True)

    source_definitions_by_letter: dict[str, dict[str, dict[str, str]]] = {}

    for canonical, source_definition in source_definitions.items():
        letter = canonical[0].upper()
        if letter not in source_definitions_by_letter:
            source_definitions_by_letter[letter] = {}
        source_definitions_by_letter[letter][canonical] = source_definition

    all_letters = sorted(source_definitions_by_letter.keys())

    for letter in all_letters:
        letter_payload = {
            "letter": letter,
            "sourceDefinitions": source_definitions_by_letter.get(letter, {}),
        }
        letter_file = split_dir / f"dictionary.{letter}.json"
        save_json(letter_file, letter_payload)

    word_count = len(lookup)
    dictionary_license_ids = {
        inferred
        for inferred in (infer_dictionary_license_id(path) for path in dictionary_paths)
        if inferred is not None
    }
    licenses = filter_licenses_for_dictionary(load_licenses(), dictionary_license_ids)
    meta_payload = {
        "meta": {
            "sourceLevels": path_for_meta(source_path),
            "sourceDictionary": dictionary_sources[0] if dictionary_sources else "",
            "sourceDictionaries": dictionary_sources,
            "wordCount": word_count,
            "mappedWordCount": word_count - len(unresolved),
            "definitionCount": len(source_definitions),
            "unresolvedWordCount": len(unresolved),
            "directMatchCount": direct_match_count,
            "lemmaMatchCount": lemma_match_count,
            "fallbackMatchCount": int(match_stats.get("fallbackMatchCount", 0)),
            "primaryDefinitionCount": int(match_stats.get("primaryDefinitionCount", 0)),
            "fallbackDefinitionSelectedCount": int(
                match_stats.get("fallbackDefinitionSelectedCount", 0)
            ),
            "websterDefinitionAvailableCount": int(
                match_stats.get("websterDefinitionAvailableCount", 0)
            ),
            "wordnetDefinitionAvailableCount": int(
                match_stats.get("wordnetDefinitionAvailableCount", 0)
            ),
            "lowQualityReplacementCount": int(
                match_stats.get("lowQualityReplacementCount", 0)
            ),
            "badStartReplacementCount": int(
                match_stats.get("badStartReplacementCount", 0)
            ),
            "scoreUpgradeReplacementCount": int(
                match_stats.get("scoreUpgradeReplacementCount", 0)
            ),
            "letterCount": len(all_letters),
            "licenses": licenses,
        },
        "letters": all_letters,
        "lookup": lookup,
        "hintRelatedForms": hint_related_forms,
    }
    meta_path = split_dir / "dictionary._meta.json"
    save_json(meta_path, meta_payload)

    print(
        "Built dictionary lookup (split) "
        f"(words={word_count} mapped={word_count - len(unresolved)} "
        f"definitions={len(source_definitions)} unresolved={len(unresolved)})"
    )
    print(
        "  Definition source selection: "
        f"primary={int(match_stats.get('primaryDefinitionCount', 0))} "
        f"fallback={int(match_stats.get('fallbackDefinitionSelectedCount', 0))} "
        f"replacedLowQuality={int(match_stats.get('lowQualityReplacementCount', 0))} "
        f"replacedBadStart={int(match_stats.get('badStartReplacementCount', 0))} "
        f"replacedByScore={int(match_stats.get('scoreUpgradeReplacementCount', 0))}"
    )
    print(f"  Meta: {meta_path}")
    print(f"  Letter files: {len(all_letters)} files (dictionary.A.json, ...)")


def main() -> None:
    args = parse_args()
    dictionary_paths = [resolve_path(args.dictionary)] + [
        resolve_path(raw) for raw in args.fallback_dictionary
    ]

    bundle_path = resolve_path(args.bundle) if args.bundle else None
    levels_dir = resolve_path(args.levels_dir) if args.levels_dir else None

    (
        lookup,
        definitions,
        source_definitions,
        hint_related_forms,
        unresolved,
        direct_match_count,
        lemma_match_count,
        match_stats,
        dictionary_sources,
    ) = build_lookup_data(
        dictionary_paths, bundle_path=bundle_path, levels_dir=levels_dir
    )

    # Source path for metadata: prefer bundle, otherwise levels_dir
    source_path: Path
    if bundle_path:
        source_path = bundle_path
    elif levels_dir:
        source_path = levels_dir
    else:
        raise SystemExit("Must provide either --bundle or --levels-dir")

    if args.split:
        split_dir = resolve_path(args.split_dir)
        write_split_files(
            split_dir,
            source_path,
            dictionary_paths,
            lookup,
            source_definitions,
            hint_related_forms,
            unresolved,
            direct_match_count,
            lemma_match_count,
            match_stats,
            dictionary_sources,
        )
    else:
        raise SystemExit("Only --split mode is supported. Please use --split flag.")


if __name__ == "__main__":
    main()

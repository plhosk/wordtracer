from __future__ import annotations

import argparse
from pathlib import Path

from common import load_json, normalize_word, now_iso, project_path, save_json

try:
    import lemminflect
    from lemminflect import getLemma
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


def build_lookup_data(
    dictionary_paths: list[Path],
    bundle_path: Path | None = None,
    levels_dir: Path | None = None,
) -> tuple[
    dict[str, str | None],
    dict[str, str],
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
        for dictionary_source, dictionary in dictionaries:
            if dictionary_source == source:
                definitions[canonical] = dictionary[canonical]
                break
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

    return (
        lookup,
        definitions,
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
    definitions: dict[str, str],
    unresolved: list[str],
    direct_match_count: int,
    lemma_match_count: int,
    match_stats: dict[str, int],
    dictionary_sources: list[str],
) -> None:
    split_dir.mkdir(parents=True, exist_ok=True)

    definitions_by_letter: dict[str, dict[str, str]] = {}

    for canonical, definition in definitions.items():
        letter = canonical[0].upper()
        if letter not in definitions_by_letter:
            definitions_by_letter[letter] = {}
        definitions_by_letter[letter][canonical] = definition

    all_letters = sorted(definitions_by_letter.keys())

    for letter in all_letters:
        letter_definitions = definitions_by_letter.get(letter, {})

        letter_payload = {
            "letter": letter,
            "definitions": letter_definitions,
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
            "definitionCount": len(definitions),
            "unresolvedWordCount": len(unresolved),
            "directMatchCount": direct_match_count,
            "lemmaMatchCount": lemma_match_count,
            "fallbackMatchCount": int(match_stats.get("fallbackMatchCount", 0)),
            "letterCount": len(all_letters),
            "licenses": licenses,
        },
        "letters": all_letters,
        "lookup": lookup,
    }
    meta_path = split_dir / "dictionary._meta.json"
    save_json(meta_path, meta_payload)

    print(
        "Built dictionary lookup (split) "
        f"(words={word_count} mapped={word_count - len(unresolved)} "
        f"definitions={len(definitions)} unresolved={len(unresolved)})"
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
            definitions,
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

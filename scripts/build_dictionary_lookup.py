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


def filter_licenses_for_dictionary(licenses: list[dict]) -> list[dict]:
    return [
        {"name": item["name"], "url": item["url"], "license": item["license"]}
        for item in licenses
        if item["id"] == "webster"
    ]


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


def build_lookup_data(
    dictionary_path: Path,
    bundle_path: Path | None = None,
    levels_dir: Path | None = None,
) -> tuple[dict[str, str | None], dict[str, str], list[str], int, int]:
    dictionary_payload = load_json(dictionary_path)
    if not isinstance(dictionary_payload, dict):
        raise SystemExit("Dictionary JSON must be an object: word -> definition")

    dictionary: dict[str, str] = {}
    for key, value in dictionary_payload.items():
        normalized = normalize_word(str(key))
        if not normalized:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                dictionary[normalized] = cleaned

    if not dictionary:
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

    for word in sorted(lookup_words):
        canonical = word if word in dictionary else None
        if canonical is None:
            for pos in ("VERB", "NOUN", "ADJ"):
                lemma = getLemma(word, pos)
                if lemma:
                    lemma_normalized = normalize_word(lemma[0])
                    if lemma_normalized and lemma_normalized in dictionary:
                        canonical = lemma_normalized
                        break

        if canonical is None:
            lookup[word] = None
            unresolved.append(word)
            continue

        lookup[word] = canonical
        definitions[canonical] = dictionary[canonical]
        if canonical == word:
            direct_match_count += 1
        else:
            lemma_match_count += 1

    return lookup, definitions, unresolved, direct_match_count, lemma_match_count


def write_split_files(
    split_dir: Path,
    source_path: Path,
    dictionary_path: Path,
    lookup: dict[str, str | None],
    definitions: dict[str, str],
    unresolved: list[str],
    direct_match_count: int,
    lemma_match_count: int,
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
    licenses = filter_licenses_for_dictionary(load_licenses())
    meta_payload = {
        "meta": {
            "sourceLevels": path_for_meta(source_path),
            "sourceDictionary": path_for_meta(dictionary_path),
            "wordCount": word_count,
            "mappedWordCount": word_count - len(unresolved),
            "definitionCount": len(definitions),
            "unresolvedWordCount": len(unresolved),
            "directMatchCount": direct_match_count,
            "lemmaMatchCount": lemma_match_count,
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
    dictionary_path = resolve_path(args.dictionary)

    bundle_path = resolve_path(args.bundle) if args.bundle else None
    levels_dir = resolve_path(args.levels_dir) if args.levels_dir else None

    lookup, definitions, unresolved, direct_match_count, lemma_match_count = (
        build_lookup_data(
            dictionary_path, bundle_path=bundle_path, levels_dir=levels_dir
        )
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
            dictionary_path,
            lookup,
            definitions,
            unresolved,
            direct_match_count,
            lemma_match_count,
        )
    else:
        raise SystemExit("Only --split mode is supported. Please use --split flag.")


if __name__ == "__main__":
    main()

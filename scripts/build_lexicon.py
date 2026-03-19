from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

from common import (
    keep_word_shape,
    now_iso,
    project_path,
    read_blocklist,
    read_word_file,
    save_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a high-coverage filtered English lexicon."
    )
    parser.add_argument(
        "--source",
        default=str(project_path("data", "raw", "words.txt")),
        help="Optional custom source file (format: word or word zipf).",
    )
    parser.add_argument(
        "--source-mode",
        choices=["auto", "file", "corpora", "union"],
        default="auto",
        help="Select source policy: auto, file, corpora, or union.",
    )
    parser.add_argument(
        "--wikipedia-source",
        default=str(project_path("data", "raw", "wikipedia", "enwiki-2023-04-13.txt")),
        help="Wikipedia frequency list path.",
    )
    parser.add_argument(
        "--blocklist",
        action="append",
        default=[str(project_path("data", "raw", "blocklists", "words.json"))],
        help="Blocklist file path (repeatable).",
    )
    parser.add_argument(
        "--blocklist-dir",
        action="append",
        default=[str(project_path("data", "raw", "blocklists"))],
        help="Directory containing *.json blocklist files (repeatable).",
    )
    parser.add_argument(
        "--re-enable-list",
        default=str(project_path("data", "raw", "re-enable", "re-enable.txt")),
        help="Required word list; words not present here are excluded.",
    )
    parser.add_argument(
        "--includelist",
        action="append",
        default=[],
        help="Explicit include list path; bypasses re-enable and frequency gates.",
    )
    parser.add_argument(
        "--out",
        default=str(project_path("data", "processed", "lexicon.json")),
        help="Output lexicon JSON path.",
    )
    parser.add_argument(
        "--stats-out",
        default=str(project_path("data", "processed", "lexicon_stats.json")),
        help="Output stats JSON path.",
    )
    parser.add_argument("--min-len", type=int, default=3)
    parser.add_argument("--max-len", type=int, default=12)
    parser.add_argument("--max-words", type=int, default=120000)
    parser.add_argument("--min-zipf", type=float, default=2.0)
    parser.add_argument(
        "--min-freq", type=float, default=None, help="Alias for --min-zipf."
    )
    parser.add_argument("--unknown-zipf", type=float, default=0.0)
    parser.add_argument("--drop-sample-limit", type=int, default=100)
    parser.add_argument(
        "--allow-weird-shapes",
        action="store_true",
        help="Keep words with extreme repeated-letter patterns.",
    )
    parser.add_argument(
        "--three-letter-max-zipf",
        type=float,
        default=4.0,
        help="Drop 3-letter words at or below this zipf threshold.",
    )
    parser.add_argument(
        "--wordfreq-source",
        choices=["off", "on"],
        default="on",
        help="Use wordfreq package for Zipf frequencies (recommended). If 'off', falls back to corpus-derived frequencies.",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def source_rows_from_file(path: Path) -> list[tuple[str, float | None, str]]:
    return [(word, freq, f"file:{path.name}") for word, freq in read_word_file(path)]


def source_rows_from_count_file(
    path: Path, source: str
) -> list[tuple[str, float, str]]:
    counts: list[tuple[str, float]] = []
    total = 0.0
    for word, maybe_count in read_word_file(path):
        if maybe_count is None or maybe_count <= 0:
            continue
        count = float(maybe_count)
        counts.append((word, count))
        total += count

    if total <= 0:
        return []

    rows: list[tuple[str, float, str]] = []
    for word, count in counts:
        zipf = math.log10((count / total) * 1_000_000_000)
        rows.append((word, zipf, source))
    return rows


def select_rows(
    args: argparse.Namespace,
) -> tuple[list[tuple[str, float | None, str]], dict[str, int], list[str]]:
    source_file = resolve_path(args.source)
    wikipedia_source = resolve_path(args.wikipedia_source)
    rows: list[tuple[str, float | None, str]] = []
    warnings: list[str] = []
    source_counts: dict[str, int] = {}

    has_corpora = wikipedia_source.exists()

    use_file = args.source_mode in {"file", "union"} or (
        args.source_mode == "auto" and not has_corpora and source_file.exists()
    )
    use_corpora = args.source_mode in {"corpora", "union"} or (
        args.source_mode == "auto" and has_corpora
    )

    if use_file:
        if source_file.exists():
            file_rows = source_rows_from_file(source_file)
            source_counts["file"] = len(file_rows)
            rows.extend(file_rows)
        else:
            warnings.append(f"source file missing: {source_file}")

    if use_corpora:
        for label, path in (("wikipedia", wikipedia_source),):
            if not path.exists():
                warnings.append(f"{label} source missing: {path}")
                continue
            corpus_rows = source_rows_from_count_file(path, label)
            source_counts[label] = len(corpus_rows)
            rows.extend(corpus_rows)

    return rows, source_counts, warnings


def expand_list_paths(file_paths: list[str], dir_paths: list[str]) -> list[Path]:
    expanded: list[Path] = []
    seen: set[Path] = set()

    for raw in file_paths:
        path = resolve_path(raw)
        if path.exists() and path not in seen:
            expanded.append(path)
            seen.add(path)

    for raw in dir_paths:
        path = resolve_path(raw)
        if not path.exists() or not path.is_dir():
            continue
        for item in sorted(path.glob("*.json")):
            if item not in seen:
                expanded.append(item)
                seen.add(item)

    return expanded


def require_input_sources(
    args: argparse.Namespace, blocklist_files: list[Path], includelist_files: list[Path]
) -> None:
    issues: list[str] = []

    for raw in args.blocklist:
        path = resolve_path(raw)
        if not path.exists() or not path.is_file():
            issues.append(f"blocklist file missing: {path}")

    for raw in args.blocklist_dir:
        path = resolve_path(raw)
        if not path.exists() or not path.is_dir():
            issues.append(f"blocklist directory missing: {path}")
            continue
        if not any(path.glob("*.json")):
            issues.append(f"blocklist directory has no *.json files: {path}")

    if not blocklist_files:
        issues.append("no blocklist files resolved from --blocklist/--blocklist-dir")

    re_enable_path = resolve_path(args.re_enable_list)
    if not re_enable_path.exists() or not re_enable_path.is_file():
        issues.append(f"re-enable list missing: {re_enable_path}")

    for path in includelist_files:
        if not path.exists() or not path.is_file():
            issues.append(f"includelist file missing: {path}")

    if args.source_mode in {"auto", "corpora", "union"}:
        wikipedia_source = resolve_path(args.wikipedia_source)
        if not wikipedia_source.exists() or not wikipedia_source.is_file():
            issues.append(f"wikipedia source missing: {wikipedia_source}")

    if issues:
        joined = "\n- ".join(issues)
        raise SystemExit(f"Missing required lexicon inputs:\n- {joined}")


def load_re_enable_words(path: Path) -> set[str]:
    words = {word for word, _ in read_word_file(path)}
    if not words:
        raise SystemExit(f"Re-enable list is empty: {path}")
    return words


def read_word_set(paths: list[Path]) -> tuple[set[str], dict[str, int]]:
    output: set[str] = set()
    per_file_counts: dict[str, int] = {}
    for path in paths:
        words = read_blocklist(path)
        output.update(words)
        per_file_counts[str(path)] = len(words)
    return output, per_file_counts


def maybe_record_drop(
    bucket: dict[str, list[dict]], reason: str, limit: int, word: str, freq: float
) -> None:
    entries = bucket.setdefault(reason, [])
    if len(entries) >= limit:
        return
    entries.append({"word": word, "freq": round(freq, 4), "len": len(word)})


_wordfreq_available = None


def get_wordfreq_zipf(word: str) -> float | None:
    """Return Zipf frequency from wordfreq package, or None if unavailable."""
    global _wordfreq_available
    if _wordfreq_available is False:
        return None
    try:
        from wordfreq import zipf_frequency

        _wordfreq_available = True
        freq = zipf_frequency(word, "en")
        return freq if freq > 0 else None
    except ImportError:
        _wordfreq_available = False
        return None


def main() -> None:
    args = parse_args()
    if args.min_freq is not None:
        args.min_zipf = args.min_freq

    # Fail fast if wordfreq is required but not available
    if args.wordfreq_source != "off":
        try:
            import wordfreq  # noqa: F401
        except ImportError:
            raise SystemExit(
                "Missing dependency: wordfreq. Run `uv sync` in the project root to install dependencies."
            )

    blocklist_files = expand_list_paths(args.blocklist, args.blocklist_dir)
    includelist_files = [resolve_path(raw) for raw in args.includelist]
    require_input_sources(args, blocklist_files, includelist_files)
    re_enable_path = resolve_path(args.re_enable_list)
    re_enable_words = load_re_enable_words(re_enable_path)
    blocklist, blocklist_per_file = read_word_set(blocklist_files)
    includelist, includelist_per_file = read_word_set(includelist_files)
    rows, source_counts, warnings = select_rows(args)

    if not rows:
        details = "; ".join(warnings) if warnings else "no sources produced rows"
        raise SystemExit(
            f"Unable to build lexicon: {details}. Provide valid corpus/source files."
        )

    merged: dict[str, dict] = {}
    duplicate_rows = 0
    guessed_freq_count = 0

    for word, maybe_freq, source in rows:
        freq = maybe_freq

        # Use wordfreq as primary frequency source when enabled
        if args.wordfreq_source != "off":
            wordfreq_freq = get_wordfreq_zipf(word)
            if wordfreq_freq is not None:
                freq = wordfreq_freq
            else:
                # Word not in wordfreq - use unknown_zipf (will likely be filtered)
                freq = args.unknown_zipf
                guessed_freq_count += 1
        elif freq is None:
            freq = args.unknown_zipf
            guessed_freq_count += 1

        existing = merged.get(word)
        if existing is None:
            merged[word] = {"freq": float(freq), "sources": {source}}
        else:
            duplicate_rows += 1
            existing["freq"] = max(float(existing["freq"]), float(freq))
            existing["sources"].add(source)

    includelist_injected_count = 0
    includelist_fallback_freq = max(float(args.min_zipf), float(args.unknown_zipf))
    for word in sorted(includelist):
        if word in merged:
            continue
        merged[word] = {
            "freq": includelist_fallback_freq,
            "sources": {"includelist"},
        }
        includelist_injected_count += 1

    reasons = Counter()
    drop_samples: dict[str, list[dict]] = {}
    kept: list[dict] = []
    for word, info in merged.items():
        freq = float(info["freq"])

        if len(word) < args.min_len:
            reasons["tooShort"] += 1
            maybe_record_drop(
                drop_samples, "tooShort", args.drop_sample_limit, word, freq
            )
            continue
        if len(word) > args.max_len:
            reasons["tooLong"] += 1
            maybe_record_drop(
                drop_samples, "tooLong", args.drop_sample_limit, word, freq
            )
            continue

        if word in blocklist:
            reasons["blocked"] += 1
            maybe_record_drop(
                drop_samples, "blocked", args.drop_sample_limit, word, freq
            )
            continue
        if word in includelist:
            kept.append(
                {
                    "word": word,
                    "freq": round(freq, 4),
                    "len": len(word),
                    "sources": sorted(info["sources"]),
                }
            )
            continue
        if word not in re_enable_words:
            reasons["notInReEnableList"] += 1
            maybe_record_drop(
                drop_samples,
                "notInReEnableList",
                args.drop_sample_limit,
                word,
                freq,
            )
            continue
        if not args.allow_weird_shapes and not keep_word_shape(word):
            reasons["shapeFiltered"] += 1
            maybe_record_drop(
                drop_samples, "shapeFiltered", args.drop_sample_limit, word, freq
            )
            continue
        if len(word) == 3 and freq <= args.three_letter_max_zipf:
            reasons["threeLetterLowZipf"] += 1
            maybe_record_drop(
                drop_samples,
                "threeLetterLowZipf",
                args.drop_sample_limit,
                word,
                freq,
            )
            continue
        if freq < args.min_zipf:
            reasons["belowMinZipf"] += 1
            maybe_record_drop(
                drop_samples, "belowMinZipf", args.drop_sample_limit, word, freq
            )
            continue

        kept.append(
            {
                "word": word,
                "freq": round(freq, 4),
                "len": len(word),
                "sources": sorted(info["sources"]),
            }
        )

    kept.sort(key=lambda item: (-item["freq"], item["word"]))
    truncated = max(0, len(kept) - args.max_words)
    kept = kept[: args.max_words]

    payload = {
        "meta": {
            "sourceMode": args.source_mode,
            "sourceCounts": source_counts,
            "rawRowCount": len(rows),
            "uniqueWordCount": len(merged),
            "wordCount": len(kept),
            "minLen": args.min_len,
            "maxLen": args.max_len,
            "minZipf": args.min_zipf,
            "maxWords": args.max_words,
            "allowWeirdShapes": bool(args.allow_weird_shapes),
            "threeLetterMaxZipf": args.three_letter_max_zipf,
            "blocklistCount": len(blocklist),
            "blocklistFiles": [str(path) for path in blocklist_files],
            "blocklistPerFile": blocklist_per_file,
            "includelistCount": len(includelist),
            "includelistFiles": [str(path) for path in includelist_files],
            "includelistPerFile": includelist_per_file,
            "includelistInjectedCount": includelist_injected_count,
            "includelistFallbackFreq": includelist_fallback_freq,
            "reEnableListPath": str(re_enable_path),
            "reEnableWordCount": len(re_enable_words),
            "duplicateRowsCollapsed": duplicate_rows,
            "rowsWithGuessedFreq": guessed_freq_count,
            "wordfreqSource": args.wordfreq_source,
            "truncatedByMaxWords": truncated,
            "dropSampleLimit": args.drop_sample_limit,
            "warnings": warnings,
        },
        "words": [
            {"word": item["word"], "freq": item["freq"], "len": item["len"]}
            for item in kept
        ],
    }

    stats_payload = {
        "meta": payload["meta"],
        "filterDrops": {
            "tooShort": int(reasons["tooShort"]),
            "tooLong": int(reasons["tooLong"]),
            "blocked": int(reasons["blocked"]),
            "notInReEnableList": int(reasons["notInReEnableList"]),
            "shapeFiltered": int(reasons["shapeFiltered"]),
            "threeLetterLowZipf": int(reasons["threeLetterLowZipf"]),
            "belowMinZipf": int(reasons["belowMinZipf"]),
        },
        "dropSamples": drop_samples,
        "topWords": kept[:50],
    }

    out_path = resolve_path(args.out)
    stats_out_path = resolve_path(args.stats_out)
    save_json(out_path, payload)
    save_json(stats_out_path, stats_payload)

    print(f"Wrote {len(kept)} words to {out_path}")
    print(f"Wrote lexicon stats to {stats_out_path}")
    for warning in warnings:
        print(f"warning: {warning}")


if __name__ == "__main__":
    main()

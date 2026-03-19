from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from common import project_path


@dataclass
class ShapeResult:
    singles: int
    doubles: int
    triples: int
    levels: int
    attempts: int
    hit_rate: float
    build_fail_count: int
    build_fail_rate: float
    duplicate_reject_count: int
    duplicate_reject_rate: float
    near_replace_count: int
    near_replace_rate: float
    answer_slots: int
    unique_answers: int
    unique_ratio: float
    avg_answers_per_level: float
    short_ratio: float
    long6_ratio: float
    long7_ratio: float
    avg_token_count: float
    len4_share: float
    len4_predictable_ratio: float
    len4_ambiguous_ratio: float
    len4_avg_decompositions: float
    len4_top_pattern: str
    len4_top_pattern_share: float
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep 7-token wheel shape configs and report answer-variety metrics."
    )
    parser.add_argument("--wheel-size", type=int, default=7)
    parser.add_argument(
        "--single-range",
        default="1-3",
        help="Inclusive range for 1-letter token count, e.g. 1-3.",
    )
    parser.add_argument(
        "--triple-range",
        default="1-2",
        help="Inclusive range for 3-letter token count, e.g. 1-2.",
    )
    parser.add_argument(
        "--count-per-config",
        type=int,
        default=220,
        help="Requested generated levels per shape.",
    )
    parser.add_argument(
        "--max-attempts-per-config",
        type=int,
        default=0,
        help="Max generation attempts per shape (0 = auto 40x count).",
    )
    parser.add_argument("--seed", type=int, default=8100)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument(
        "--layout-mode",
        choices=("maze-path", "crossword-letter"),
        default="crossword-letter",
    )
    parser.add_argument("--rows-min", type=int, default=10)
    parser.add_argument("--rows-max", type=int, default=10)
    parser.add_argument("--cols-min", type=int, default=10)
    parser.add_argument("--cols-max", type=int, default=10)
    parser.add_argument("--min-answers", type=int, default=8)
    parser.add_argument("--max-answers", type=int, default=0)
    parser.add_argument("--combo-sizes", default="1,2")
    parser.add_argument("--wheel-token-sizes", default="1,2")
    parser.add_argument("--min-answer-token-count", type=int, default=2)
    parser.add_argument("--min-answer-token-large-wheel-size", type=int, default=7)
    parser.add_argument("--min-answer-token-count-large-wheel", type=int, default=2)
    parser.add_argument("--min-bonus-token-count", type=int, default=2)
    parser.add_argument("--target-min-answer-len", type=int, default=4)
    parser.add_argument("--short-answer-len", type=int, default=4)
    parser.add_argument("--preferred-max-short-answers", type=int, default=5)
    parser.add_argument("--answer-length-weight", type=float, default=22.0)
    parser.add_argument("--preferred-answer-len-min", type=int, default=4)
    parser.add_argument("--preferred-answer-len-max", type=int, default=6)
    parser.add_argument("--preferred-answer-len-bonus", type=float, default=10.0)
    parser.add_argument("--short-answer-penalty", type=float, default=18.0)
    parser.add_argument("--progress-every-seconds", type=float, default=0.0)
    parser.add_argument(
        "--keep-generated-json",
        action="store_true",
        help="Do not delete temporary candidate JSON files.",
    )
    return parser.parse_args()


def parse_range(raw: str, label: str) -> tuple[int, int]:
    token = raw.strip()
    if "-" not in token:
        value = int(token)
        if value < 0:
            raise SystemExit(f"{label} must be >= 0")
        return value, value
    left, right = token.split("-", 1)
    start = int(left.strip())
    end = int(right.strip())
    if start < 0 or end < 0 or start > end:
        raise SystemExit(f"Invalid {label}: {raw}")
    return start, end


def token_text(token: str, mode: str) -> str:
    if mode == "reverse" and len(token) >= 2:
        return token[::-1]
    return token


def decomposition_patterns(
    word: str,
    wheel_tokens: list[str],
    allowed_modes: list[str],
) -> tuple[int, set[tuple[int, ...]]]:
    total_paths = 0
    patterns: set[tuple[int, ...]] = set()
    modes = [mode for mode in allowed_modes if mode in {"forward", "reverse"}]
    if not modes:
        modes = ["forward", "reverse"]

    for mode in modes:
        rendered = [token_text(token, mode) for token in wheel_tokens]

        def walk(pos: int, used_mask: int, lens: tuple[int, ...]) -> None:
            nonlocal total_paths
            if pos == len(word):
                total_paths += 1
                patterns.add(lens)
                return
            for idx, token in enumerate(rendered):
                if used_mask & (1 << idx):
                    continue
                if not word.startswith(token, pos):
                    continue
                walk(pos + len(token), used_mask | (1 << idx), lens + (len(token),))

        walk(0, 0, ())

    return total_paths, patterns


def run_generate_for_shape(
    script_path: Path,
    out_path: Path,
    args: argparse.Namespace,
    singles: int,
    triples: int,
    seed: int,
) -> dict:
    max_attempts = args.max_attempts_per_config
    if max_attempts <= 0:
        max_attempts = max(args.count_per_config * 40, args.count_per_config)

    cmd = [
        sys.executable,
        "-u",
        str(script_path),
        "--count",
        str(args.count_per_config),
        "--seed",
        str(seed),
        "--wheel-size",
        str(args.wheel_size),
        "--layout-mode",
        args.layout_mode,
        "--rows-min",
        str(args.rows_min),
        "--rows-max",
        str(args.rows_max),
        "--cols-min",
        str(args.cols_min),
        "--cols-max",
        str(args.cols_max),
        "--min-answers",
        str(args.min_answers),
        "--max-answers",
        str(args.max_answers),
        "--max-attempts",
        str(max_attempts),
        "--workers",
        str(args.workers),
        "--combo-sizes",
        args.combo_sizes,
        "--wheel-token-sizes",
        args.wheel_token_sizes,
        "--min-single-letter-tokens",
        str(singles),
        "--max-single-letter-tokens",
        str(singles),
        "--min-three-letter-tokens-large-wheel-size",
        str(args.wheel_size),
        "--min-three-letter-tokens-large-wheel",
        str(triples),
        "--min-answer-token-count",
        str(args.min_answer_token_count),
        "--min-answer-token-large-wheel-size",
        str(args.min_answer_token_large_wheel_size),
        "--min-answer-token-count-large-wheel",
        str(args.min_answer_token_count_large_wheel),
        "--min-bonus-token-count",
        str(args.min_bonus_token_count),
        "--target-min-answer-len",
        str(args.target_min_answer_len),
        "--short-answer-len",
        str(args.short_answer_len),
        "--preferred-max-short-answers",
        str(args.preferred_max_short_answers),
        "--answer-length-weight",
        str(args.answer_length_weight),
        "--preferred-answer-len-min",
        str(args.preferred_answer_len_min),
        "--preferred-answer-len-max",
        str(args.preferred_answer_len_max),
        "--preferred-answer-len-bonus",
        str(args.preferred_answer_len_bonus),
        "--short-answer-penalty",
        str(args.short_answer_penalty),
        "--progress-every-seconds",
        str(args.progress_every_seconds),
        "--out",
        str(out_path),
    ]
    subprocess.run(cmd, cwd=script_path.parent.parent, check=True)
    with out_path.open() as handle:
        return json.load(handle)


def analyze_payload(
    payload: dict, singles: int, doubles: int, triples: int
) -> ShapeResult:
    levels = [item for item in payload.get("levels", []) if isinstance(item, dict)]
    meta = payload.get("meta", {})
    attempts = int(meta.get("attempts", 0))
    generated = len(levels)
    hit_rate = (generated / attempts) if attempts > 0 else 0.0

    duplicate_stats = meta.get("duplicateStats", {})
    exact_duplicates = int(duplicate_stats.get("exact", 0))
    near_rejected = int(duplicate_stats.get("nearRejected", 0))
    overlap_rejected = int(duplicate_stats.get("overlapRejected", 0))
    near_replaced = int(duplicate_stats.get("nearReplaced", 0))
    duplicate_reject_count = exact_duplicates + near_rejected + overlap_rejected
    build_fail_count = max(
        0,
        attempts - generated - duplicate_reject_count - near_replaced,
    )
    build_fail_rate = (build_fail_count / attempts) if attempts > 0 else 0.0
    duplicate_reject_rate = duplicate_reject_count / attempts if attempts > 0 else 0.0
    near_replace_rate = (near_replaced / attempts) if attempts > 0 else 0.0

    answer_words: list[str] = []
    token_counts: list[int] = []
    len4_total = 0
    len4_predictable = 0
    len4_decompositions: list[int] = []
    len4_pattern_counts: Counter[str] = Counter()

    for level in levels:
        wheel_tokens = [str(token) for token in level.get("letterWheel", [])]
        for answer in level.get("answers", []):
            if not isinstance(answer, dict):
                continue
            word = str(answer.get("text", "")).strip().lower()
            if not word:
                continue
            answer_words.append(word)
            token_counts.append(int(answer.get("tokenCount", 0)))

            if len(word) != 4:
                continue

            len4_total += 1
            allowed_modes = answer.get("allowedModes", [])
            if not isinstance(allowed_modes, list):
                allowed_modes = ["forward", "reverse"]

            decomposition_count, patterns = decomposition_patterns(
                word,
                wheel_tokens,
                [str(mode) for mode in allowed_modes],
            )
            len4_decompositions.append(decomposition_count)
            if len(patterns) == 1:
                len4_predictable += 1
            for pattern in patterns:
                len4_pattern_counts["+".join(str(size) for size in pattern)] += 1

    answer_slots = len(answer_words)
    unique_answers = len(set(answer_words))
    unique_ratio = (unique_answers / answer_slots) if answer_slots else 0.0
    avg_answers_per_level = (answer_slots / generated) if generated else 0.0
    short_ratio = (
        sum(1 for word in answer_words if len(word) <= 4) / answer_slots
        if answer_slots
        else 0.0
    )
    long6_ratio = (
        sum(1 for word in answer_words if len(word) >= 6) / answer_slots
        if answer_slots
        else 0.0
    )
    long7_ratio = (
        sum(1 for word in answer_words if len(word) >= 7) / answer_slots
        if answer_slots
        else 0.0
    )
    avg_token_count = (sum(token_counts) / len(token_counts)) if token_counts else 0.0
    len4_share = (len4_total / answer_slots) if answer_slots else 0.0
    len4_predictable_ratio = (len4_predictable / len4_total) if len4_total else 0.0
    len4_ambiguous_ratio = 1.0 - len4_predictable_ratio if len4_total else 0.0
    len4_avg_decompositions = (
        sum(len4_decompositions) / len(len4_decompositions)
        if len4_decompositions
        else 0.0
    )

    if len4_pattern_counts:
        top_pattern, top_count = max(
            len4_pattern_counts.items(), key=lambda item: (item[1], item[0])
        )
        top_pattern_share = top_count / sum(len4_pattern_counts.values())
    else:
        top_pattern = "n/a"
        top_pattern_share = 0.0

    quality_term = min(1.0, avg_answers_per_level / 9.0)
    score = (
        (0.40 * unique_ratio)
        + (0.25 * len4_ambiguous_ratio)
        + (0.20 * hit_rate)
        + (0.15 * quality_term)
    )

    return ShapeResult(
        singles=singles,
        doubles=doubles,
        triples=triples,
        levels=generated,
        attempts=attempts,
        hit_rate=hit_rate,
        build_fail_count=build_fail_count,
        build_fail_rate=build_fail_rate,
        duplicate_reject_count=duplicate_reject_count,
        duplicate_reject_rate=duplicate_reject_rate,
        near_replace_count=near_replaced,
        near_replace_rate=near_replace_rate,
        answer_slots=answer_slots,
        unique_answers=unique_answers,
        unique_ratio=unique_ratio,
        avg_answers_per_level=avg_answers_per_level,
        short_ratio=short_ratio,
        long6_ratio=long6_ratio,
        long7_ratio=long7_ratio,
        avg_token_count=avg_token_count,
        len4_share=len4_share,
        len4_predictable_ratio=len4_predictable_ratio,
        len4_ambiguous_ratio=len4_ambiguous_ratio,
        len4_avg_decompositions=len4_avg_decompositions,
        len4_top_pattern=top_pattern,
        len4_top_pattern_share=top_pattern_share,
        score=score,
    )


def main() -> None:
    args = parse_args()
    if args.wheel_size <= 0:
        raise SystemExit("--wheel-size must be >= 1")
    if args.count_per_config <= 0:
        raise SystemExit("--count-per-config must be >= 1")

    single_min, single_max = parse_range(args.single_range, "--single-range")
    triple_min, triple_max = parse_range(args.triple_range, "--triple-range")

    configs: list[tuple[int, int, int]] = []
    for singles in range(single_min, single_max + 1):
        for triples in range(triple_min, triple_max + 1):
            doubles = args.wheel_size - singles - triples
            if doubles < 1:
                continue
            configs.append((singles, doubles, triples))

    if not configs:
        raise SystemExit("No valid token-shape configurations for provided ranges.")

    script_path = project_path("scripts", "generate_boards.py")
    print(
        f"Sweeping {len(configs)} shapes for wheel size {args.wheel_size}; {args.count_per_config} requested levels each"
    )

    results: list[ShapeResult] = []
    with tempfile.TemporaryDirectory(prefix="wheel-shape-sweep-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for idx, (singles, doubles, triples) in enumerate(configs):
            out_path = tmp_root / f"shape-{singles}-{doubles}-{triples}.json"
            print(f"- shape {singles}/{doubles}/{triples} ...", flush=True)
            payload = run_generate_for_shape(
                script_path,
                out_path,
                args,
                singles,
                triples,
                args.seed + idx,
            )
            result = analyze_payload(payload, singles, doubles, triples)
            results.append(result)
            print(
                "  "
                f"levels={result.levels} hitRate={result.hit_rate:.3f} "
                f"failRate={result.build_fail_rate:.3f} dupReject={result.duplicate_reject_rate:.3f} repl={result.near_replace_rate:.3f} "
                f"uniq={result.unique_ratio:.3f} len4Amb={result.len4_ambiguous_ratio:.3f} "
                f"long6%={result.long6_ratio * 100.0:.1f} long7%={result.long7_ratio * 100.0:.1f} "
                f"top4={result.len4_top_pattern}({result.len4_top_pattern_share:.3f}) score={result.score:.3f}"
            )
            if args.keep_generated_json:
                keep_path = project_path(
                    "data",
                    "generated",
                    f"wheel_shape_sweep_{singles}_{doubles}_{triples}.json",
                )
                keep_path.write_text(json.dumps(payload, indent=2))

    results.sort(key=lambda item: item.score, reverse=True)
    print("\nRanked shapes (higher score is better):")
    for rank, item in enumerate(results, start=1):
        print(
            f"{rank:>2}. shape={item.singles}/{item.doubles}/{item.triples} "
            f"score={item.score:.3f} hit={item.hit_rate:.3f} "
            f"fail={item.build_fail_rate:.3f} dupReject={item.duplicate_reject_rate:.3f} repl={item.near_replace_rate:.3f} "
            f"uniq={item.unique_ratio:.3f} ans/level={item.avg_answers_per_level:.2f} "
            f"short={item.short_ratio:.3f} long6%={item.long6_ratio * 100.0:.1f} long7%={item.long7_ratio * 100.0:.1f} "
            f"len4Amb={item.len4_ambiguous_ratio:.3f} "
            f"len4Predict={item.len4_predictable_ratio:.3f} len4DecAvg={item.len4_avg_decompositions:.2f} "
            f"top4={item.len4_top_pattern}({item.len4_top_pattern_share:.3f})"
        )

    best = results[0]
    print(
        "\nRecommended fixed shape: "
        f"{best.singles}x1-letter, {best.doubles}x2-letter, {best.triples}x3-letter"
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

from common import now_iso, project_path, save_json


AUTO_GROUP_WHEEL_SHAPE_MIX_RAW: dict[int, str] = {
    3: "2/1/0:0.65,1/2/0:0.35",
    4: "3/1/0:0.20,2/2/0:0.40,2/1/1:0.15,1/3/0:0.25",
    5: "4/1/0:0.15,3/2/0:0.25,2/3/0:0.30,2/2/1:0.10,1/4/0:0.15,1/3/1:0.05",
    6: "5/1/0:0.12,4/2/0:0.20,3/3/0:0.22,2/4/0:0.18,2/3/1:0.10,1/5/0:0.12,1/4/1:0.06",
    7: "6/1/0:0.10,5/2/0:0.19,5/1/1:0.13,4/2/1:0.16,4/3/0:0.13,3/3/1:0.10,3/4/0:0.06,2/5/0:0.08,2/4/1:0.05",
}


class ArgumentFileParser(argparse.ArgumentParser):
    def convert_arg_line_to_args(self, arg_line: str) -> list[str]:
        stripped = arg_line.strip()
        if not stripped or stripped.startswith("#"):
            return []
        return shlex.split(stripped, comments=True)


def parse_args() -> argparse.Namespace:
    parser = ArgumentFileParser(
        description="Run full level-generation pipeline.",
        fromfile_prefix_chars="@",
    )
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument(
        "--bonus-lexicon",
        default=str(project_path("data", "processed", "lexicon_bonus.json")),
        help="Path for relaxed bonus lexicon JSON.",
    )
    parser.add_argument(
        "--bonus-lexicon-stats",
        default=str(project_path("data", "processed", "lexicon_bonus_stats.json")),
        help="Path for relaxed bonus lexicon stats JSON.",
    )
    parser.add_argument(
        "--includelist",
        "--bonus-includelist",
        dest="includelist",
        default=str(project_path("data", "raw", "includelist", "includelist.json")),
        help="Explicit include list for words to add to both main and bonus lexicons.",
    )
    parser.add_argument(
        "--bonus-min-zipf",
        type=float,
        default=1.5,
        help="Minimum zipf used for the relaxed bonus lexicon.",
    )
    parser.add_argument(
        "--bonus-three-letter-min-zipf",
        type=float,
        default=3.0,
        help="Minimum zipf for 3-letter bonus words; negative disables this gate.",
    )
    parser.add_argument(
        "--wordfreq-source",
        choices=("off", "on"),
        default="on",
        help="Use wordfreq package for Zipf frequencies (recommended).",
    )
    parser.add_argument(
        "--dictionary-source",
        default=str(project_path("data", "raw", "webster", "webster.json")),
        help="Source dictionary JSON used to build app lookup data.",
    )
    parser.add_argument(
        "--combo-sizes",
        default="1,2",
        help="Comma-separated combo sizes (default: 1,2).",
    )
    parser.add_argument(
        "--wheel-token-sizes",
        default="1,2",
        help="Comma-separated wheel token sizes (default: 1,2).",
    )
    parser.add_argument(
        "--wheel-size-min",
        type=int,
        default=3,
        help="Minimum wheel size for grouped generation.",
    )
    parser.add_argument(
        "--wheel-size-max",
        type=int,
        default=7,
        help="Maximum wheel size for grouped generation.",
    )
    parser.add_argument(
        "--group-count-max",
        type=int,
        default=12,
        help="Maximum number of level groups.",
    )
    parser.add_argument(
        "--group-label-start",
        default="A",
        help="Starting group label character.",
    )
    parser.add_argument(
        "--group-size-step",
        type=int,
        default=10,
        help="Per-group size increment before cap (used when --group-size-targets is empty).",
    )
    parser.add_argument(
        "--group-size-max",
        type=int,
        default=50,
        help="Maximum levels per group (used when --group-size-targets is empty).",
    )
    parser.add_argument(
        "--group-size-targets",
        default="",
        help=(
            "Optional comma-separated explicit group sizes. "
            "If shorter than group count, the last value is reused. "
            "Example: 8,15,30,40,50"
        ),
    )
    parser.add_argument(
        "--group-size-undershoot-ratio",
        type=float,
        default=0.0,
        help=(
            "Maximum allowed fractional undershoot per group during export. "
            "Example: 0.2 allows selecting at least 80%% of target levels."
        ),
    )
    parser.add_argument(
        "--group-oversamples",
        default="10",
        help="Comma-separated oversample multipliers per group. If shorter than group count, the last value is reused for remaining groups.",
    )
    parser.add_argument(
        "--group-freq-floors",
        default="",
        help="Comma-separated per-group minimum answer-frequency floors.",
    )
    parser.add_argument(
        "--group-min-answers",
        default="8",
        help="Comma-separated minimum answer counts per group. If shorter than group count, the last value is reused.",
    )
    parser.add_argument(
        "--group-freq-relax-step",
        type=float,
        default=0.05,
        help="Frequency floor relaxation step used during grouped export.",
    )
    parser.add_argument(
        "--group-freq-relax-max-steps",
        type=int,
        default=24,
        help="Maximum floor relaxation iterations during grouped export.",
    )
    parser.add_argument(
        "--min-single-letter-tokens",
        type=int,
        default=2,
        help="Minimum single-letter wheel tokens per level.",
    )
    parser.add_argument(
        "--max-single-letter-tokens",
        type=int,
        default=2,
        help="Maximum single-letter wheel tokens per level.",
    )
    parser.add_argument(
        "--min-three-letter-tokens-large-wheel-size",
        type=int,
        default=7,
        help="Apply a minimum 3-letter token requirement at or above this wheel size.",
    )
    parser.add_argument(
        "--min-three-letter-tokens-large-wheel",
        type=int,
        default=1,
        help="Minimum 3-letter wheel tokens required for large-wheel levels.",
    )
    parser.add_argument(
        "--layout-mode",
        choices=("maze-path", "crossword-letter"),
        default="crossword-letter",
        help="Board layout mode used by generate_boards.py",
    )
    parser.add_argument(
        "--rows-min",
        type=int,
        default=10,
        help="Minimum crossword row count.",
    )
    parser.add_argument(
        "--rows-max",
        type=int,
        default=10,
        help="Maximum crossword row count.",
    )
    parser.add_argument(
        "--cols-min",
        type=int,
        default=10,
        help="Minimum crossword column count.",
    )
    parser.add_argument(
        "--cols-max",
        type=int,
        default=10,
        help="Maximum crossword column count.",
    )
    parser.add_argument(
        "--crossword-placement-attempts",
        type=int,
        default=90,
        help="Placement retries per board size in crossword mode.",
    )
    parser.add_argument(
        "--crossword-max-isolated-words",
        type=int,
        default=2,
        help="Fallback cap for words outside the main connected component.",
    )
    parser.add_argument(
        "--crossword-isolated-word-min-freq",
        type=float,
        default=4.8,
        help="Minimum frequency required for disconnected crossword words.",
    )
    parser.add_argument(
        "--crossword-level-time-limit",
        type=float,
        default=0.0,
        help="Seconds allowed per crossword level placement attempt (<=0 uses dynamic throughput-based limit).",
    )
    parser.add_argument(
        "--min-answer-token-count",
        type=int,
        default=2,
        help="Minimum token count required for answer words.",
    )
    parser.add_argument(
        "--max-word-len",
        type=int,
        default=12,
        help="Maximum answer/bonus word length candidate bound.",
    )
    parser.add_argument(
        "--combo-pool-max-words",
        type=int,
        default=12000,
        help="Max lexicon words used when building combo pool scores.",
    )
    parser.add_argument(
        "--wheel-sampling-pool-max",
        type=int,
        default=1200,
        help="Max top-ranked combo tokens considered when sampling wheels.",
    )
    parser.add_argument(
        "--target-min-answer-len",
        type=int,
        default=4,
        help="Try this minimum answer length first before relaxing.",
    )
    parser.add_argument(
        "--short-answer-len",
        type=int,
        default=3,
        help="Words at or below this length are treated as short answers.",
    )
    parser.add_argument(
        "--preferred-max-short-answers",
        type=int,
        default=2,
        help="Preferred cap on short answers; generation relaxes upward only if needed.",
    )
    parser.add_argument(
        "--answer-length-weight",
        type=float,
        default=22.0,
        help="Length bonus weight for answer-word selection scoring.",
    )
    parser.add_argument(
        "--preferred-answer-len-min",
        type=int,
        default=5,
        help="Preferred minimum answer length for soft scoring bonus.",
    )
    parser.add_argument(
        "--preferred-answer-len-max",
        type=int,
        default=8,
        help="Preferred maximum answer length for soft scoring bonus.",
    )
    parser.add_argument(
        "--preferred-answer-len-bonus",
        type=float,
        default=12.0,
        help="Soft bonus per length step for preferred-length answers.",
    )
    parser.add_argument(
        "--short-answer-penalty",
        type=float,
        default=105.0,
        help="Penalty scale applied to short answers during answer selection.",
    )
    parser.add_argument(
        "--long-word-bias-wheel-size",
        type=int,
        default=7,
        help="Apply stricter long-word targeting at or above this wheel size.",
    )
    parser.add_argument(
        "--long-word-target-min-len",
        type=int,
        default=4,
        help="Initial minimum answer length target for large-wheel levels.",
    )
    parser.add_argument(
        "--long-word-relax-min-len",
        type=int,
        default=3,
        help="Relaxation floor for minimum answer length on large-wheel levels.",
    )
    parser.add_argument(
        "--min-answer-token-large-wheel-size",
        type=int,
        default=7,
        help="Apply stricter answer token-count gate at or above this wheel size.",
    )
    parser.add_argument(
        "--min-answer-token-count-large-wheel",
        type=int,
        default=2,
        help="Minimum answer token-count used for large-wheel levels.",
    )
    parser.add_argument(
        "--min-bonus-token-count",
        type=int,
        default=2,
        help="Minimum token count required for bonus/valid words.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=0,
        help="Max board-generation attempts (0 = auto based on count).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help=(
            "Parallel board-generation workers "
            "(0 = logical cores minus one when <8, otherwise minus two)."
        ),
    )
    parser.add_argument(
        "--progress-every-seconds",
        type=float,
        default=10.0,
        help="Status output cadence for board generation in seconds.",
    )
    parser.add_argument(
        "--near-duplicate-answer-jaccard",
        type=float,
        default=0.4,
        help="Reject generated levels with high recent answer-set overlap.",
    )
    parser.add_argument(
        "--near-duplicate-window",
        type=int,
        default=20,
        help="Recent accepted-level window used by overlap dedup.",
    )
    parser.add_argument(
        "--group-overlap-window",
        type=int,
        default=12,
        help="How many recent exported levels to penalize for answer overlap.",
    )
    parser.add_argument(
        "--group-word-cooldown",
        type=int,
        default=5,
        help="Minimum level gap target before reusing an answer word.",
    )
    parser.add_argument(
        "--group-word-cooldown-early-groups",
        type=int,
        default=4,
        help="How many early groups use stricter word cooldown.",
    )
    parser.add_argument(
        "--group-strict-novelty-early-groups",
        type=int,
        default=0,
        help="How many early groups enforce strict novelty filters without soft fallback.",
    )
    parser.add_argument(
        "--group-word-cooldown-early-levels",
        type=int,
        default=24,
        help="Stricter minimum level gap target for early groups.",
    )
    parser.add_argument(
        "--group-short-word-len-max",
        type=int,
        default=4,
        help="Words at or below this length use stricter cooldown.",
    )
    parser.add_argument(
        "--group-short-word-cooldown",
        type=int,
        default=6,
        help="Cooldown target for short answer words across exported levels.",
    )
    parser.add_argument(
        "--group-short-word-cooldown-early-levels",
        type=int,
        default=24,
        help="Stricter short-word cooldown target for early groups.",
    )
    parser.add_argument(
        "--group-short-word-signature-cooldown",
        type=int,
        default=14,
        help="Cooldown target for short-word anagram signatures across exported levels.",
    )
    parser.add_argument(
        "--group-short-word-signature-cooldown-early-levels",
        type=int,
        default=28,
        help="Stricter short-word anagram-signature cooldown target for early groups.",
    )
    parser.add_argument(
        "--group-short-word-signature-penalty-weight",
        type=float,
        default=3.0,
        help="Selection penalty weight for short-word anagram-signature reuse.",
    )
    parser.add_argument(
        "--group-hard-overlap-window",
        type=int,
        default=16,
        help="Recent levels window used for hard overlap gating.",
    )
    parser.add_argument(
        "--group-hard-overlap-max-shared-words",
        type=int,
        default=1,
        help="Reject candidates sharing more than this many words with recent levels.",
    )
    parser.add_argument(
        "--group-reuse-budget-ratio",
        type=float,
        default=0.2,
        help="Max prior-pack word reuse budget as a fraction of expected answers.",
    )
    parser.add_argument(
        "--group-reuse-budget-min",
        type=int,
        default=0,
        help="Minimum prior-pack word reuse budget per group.",
    )
    parser.add_argument(
        "--group-cross-pack-early-groups",
        type=int,
        default=6,
        help="How many early groups enforce per-word cross-pack reuse caps.",
    )
    parser.add_argument(
        "--group-cross-pack-short-word-max-reuse",
        type=int,
        default=1,
        help="Maximum groups a short answer word may appear in across early packs.",
    )
    parser.add_argument(
        "--group-cross-pack-long-word-max-reuse",
        type=int,
        default=2,
        help="Maximum groups a long answer word may appear in across early packs.",
    )
    parser.add_argument(
        "--group-cross-pack-late-start-group",
        type=int,
        default=8,
        help="Group index at which relaxed late-pack cross-pack caps begin.",
    )
    parser.add_argument(
        "--group-cross-pack-late-short-word-max-reuse",
        type=int,
        default=12,
        help="Late-pack maximum groups a short answer word may appear in.",
    )
    parser.add_argument(
        "--group-cross-pack-late-long-word-max-reuse",
        type=int,
        default=16,
        help="Late-pack maximum groups a long answer word may appear in.",
    )
    parser.add_argument(
        "--group-three-letter-signature-early-groups",
        type=int,
        default=3,
        help="How many early groups enforce 3-letter answer-family reuse caps.",
    )
    parser.add_argument(
        "--group-three-letter-signature-max-reuse",
        type=int,
        default=2,
        help="Maximum groups a 3-letter answer-family signature may appear in across early packs.",
    )
    parser.add_argument(
        "--group-global-overuse-short-weight",
        type=float,
        default=1.2,
        help="Selection penalty weight for globally overused short words.",
    )
    parser.add_argument(
        "--group-global-overuse-long-weight",
        type=float,
        default=0.2,
        help="Selection penalty weight for globally overused long words.",
    )
    parser.add_argument(
        "--group-difficulty-profile-start-group",
        type=int,
        default=4,
        help="Group index where late-pack difficulty profiling begins.",
    )
    parser.add_argument(
        "--group-difficulty-target-avg-freq-start",
        type=float,
        default=4.05,
        help="Target average answer frequency at profile start group.",
    )
    parser.add_argument(
        "--group-difficulty-target-avg-freq-end",
        type=float,
        default=3.70,
        help="Target average answer frequency at final group.",
    )
    parser.add_argument(
        "--group-difficulty-target-power",
        type=float,
        default=1.4,
        help="Curve exponent for late-pack difficulty profile interpolation.",
    )
    parser.add_argument(
        "--group-difficulty-target-weight",
        type=float,
        default=3.5,
        help="Penalty weight for distance from per-group target average frequency.",
    )
    parser.add_argument(
        "--group-difficulty-floor-margin",
        type=float,
        default=0.45,
        help="Soft minimum margin below target average frequency allowed per group.",
    )
    parser.add_argument(
        "--group-difficulty-ceiling-margin",
        type=float,
        default=0.20,
        help="Soft maximum margin above target average frequency allowed per group.",
    )
    parser.add_argument(
        "--group-wheel-shape-mix-by-wheel",
        default="auto",
        help=(
            "Optional weighted wheel-shape mixes per wheel size. "
            "Format: wheel=mix;wheel=mix where mix is singles/doubles/triples:weight entries. "
            "Example: 3=2/1/0:0.6,1/2/0:0.4;4=2/2/0:0.5,1/3/0:0.5. "
            "Use 'auto' for curated defaults across wheel sizes; empty disables all per-wheel mixes."
        ),
    )
    parser.add_argument(
        "--group-wheel-shape-min-levels",
        type=int,
        default=1,
        help="Minimum per-shape level quota per group when mix is enabled.",
    )
    return parser.parse_args()


def run(script_dir: Path, *args: str) -> None:
    cmd = [sys.executable, "-u", *args]
    if any(str(arg).endswith("generate_boards.py") for arg in args):
        print("", flush=True)
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=script_dir.parent, check=True)


def parse_float_list(raw: str) -> list[float]:
    items: list[float] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        items.append(float(token))
    return items


def parse_int_list(raw: str) -> list[int]:
    items: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        items.append(int(token))
    return items


def parse_group_wheel_shape_mix(raw: str, wheel_size: int) -> list[dict]:
    token = raw.strip().lower()
    if token == "auto":
        raw = AUTO_GROUP_WHEEL_SHAPE_MIX_RAW.get(wheel_size, "")

    entries = [token.strip() for token in raw.split(",") if token.strip()]
    if not entries:
        return []

    shapes: list[dict] = []
    total_weight = 0.0
    for token in entries:
        if ":" in token:
            shape_raw, weight_raw = token.split(":", 1)
            weight = float(weight_raw.strip())
        else:
            shape_raw = token
            weight = 1.0
        if weight <= 0:
            raise SystemExit("wheel-shape mix weights must be > 0")

        parts = [part.strip() for part in shape_raw.split("/")]
        if len(parts) != 3:
            raise SystemExit("wheel-shape mix entries must be singles/doubles/triples")

        singles = int(parts[0])
        doubles = int(parts[1])
        triples = int(parts[2])
        if min(singles, doubles, triples) < 0:
            raise SystemExit("wheel-shape mix token counts must be >= 0")
        if singles + doubles + triples != wheel_size:
            raise SystemExit("wheel-shape mix entries must sum to wheel size")
        if doubles < 1:
            raise SystemExit("wheel-shape mix requires at least one 2-letter token")

        shape_id = f"{singles}/{doubles}/{triples}"
        if any(item["id"] == shape_id for item in shapes):
            raise SystemExit("wheel-shape mix contains duplicate shapes")

        shapes.append(
            {
                "id": shape_id,
                "singles": singles,
                "doubles": doubles,
                "triples": triples,
                "weight": weight,
            }
        )
        total_weight += weight

    for shape in shapes:
        shape["weight"] = shape["weight"] / total_weight
    return shapes


def parse_group_wheel_shape_mix_by_wheel(
    raw: str,
    wheel_size_min: int,
    wheel_size_max: int,
) -> dict[int, list[dict]]:
    token = raw.strip().lower()
    if token == "":
        return {}
    if token == "auto":
        mixes: dict[int, list[dict]] = {}
        for wheel_size in range(wheel_size_min, wheel_size_max + 1):
            mix = parse_group_wheel_shape_mix("auto", wheel_size)
            if mix:
                mixes[wheel_size] = mix
        return mixes

    mixes: dict[int, list[dict]] = {}
    entries = [item.strip() for item in raw.split(";") if item.strip()]
    for entry in entries:
        if "=" not in entry:
            raise SystemExit(
                "--group-wheel-shape-mix-by-wheel entries must be wheel=mix"
            )
        wheel_raw, mix_raw = entry.split("=", 1)
        wheel_size = int(wheel_raw.strip())
        if wheel_size < wheel_size_min or wheel_size > wheel_size_max:
            raise SystemExit(
                "--group-wheel-shape-mix-by-wheel wheel size is out of grouped wheel-size range"
            )
        if wheel_size in mixes:
            raise SystemExit(
                "--group-wheel-shape-mix-by-wheel contains duplicate wheel sizes"
            )
        mixes[wheel_size] = parse_group_wheel_shape_mix(mix_raw.strip(), wheel_size)
    return mixes


def allocate_weighted_counts(
    total: int,
    weights: list[float],
    min_each: int = 0,
) -> list[int]:
    if total <= 0 or not weights:
        return [0 for _ in weights]

    bucket_count = len(weights)
    effective_min_each = max(0, min_each)
    if bucket_count > 0:
        effective_min_each = min(effective_min_each, total // bucket_count)

    counts = [effective_min_each for _ in range(bucket_count)]
    remaining = total - (effective_min_each * bucket_count)
    if remaining <= 0:
        return counts

    total_weight = sum(weight for weight in weights if weight > 0)
    if total_weight <= 0:
        normalized = [1.0 / bucket_count for _ in range(bucket_count)]
    else:
        normalized = [max(0.0, weight) / total_weight for weight in weights]

    raw_allocations = [remaining * weight for weight in normalized]
    floor_allocations = [int(value) for value in raw_allocations]
    counts = [count + add for count, add in zip(counts, floor_allocations)]

    leftover = remaining - sum(floor_allocations)
    if leftover > 0:
        rank = sorted(
            range(bucket_count),
            key=lambda idx: (
                raw_allocations[idx] - floor_allocations[idx],
                normalized[idx],
                -idx,
            ),
            reverse=True,
        )
        for idx in rank[:leftover]:
            counts[idx] += 1

    return counts


def group_label(start_label: str, index: int) -> str:
    """Generate Excel-style column labels: A-Z, then AA-AZ, BA-BZ, etc."""
    base = (start_label.strip() or "A")[0].upper()
    base_offset = ord(base) - ord("A")
    total_index = base_offset + index

    # Excel-style conversion: 0=A, 1=B, ..., 25=Z, 26=AA, 27=AB, etc.
    result = ""
    current = total_index
    while True:
        result = chr(ord("A") + (current % 26)) + result
        current = current // 26
        if current == 0:
            break
        current -= 1  # Adjust for 0-indexing in each position

    return result


def auto_max_attempts(raw_max_attempts: int, count: int) -> int:
    if raw_max_attempts > 0:
        return raw_max_attempts
    return max(6000, count * 40)


def build_group_specs(args: argparse.Namespace) -> list[dict]:
    if args.group_count_max <= 0:
        raise SystemExit("--group-count-max must be >= 1")
    if args.group_size_step <= 0:
        raise SystemExit("--group-size-step must be >= 1")
    if args.group_size_max <= 0:
        raise SystemExit("--group-size-max must be >= 1")
    if args.group_size_undershoot_ratio < 0 or args.group_size_undershoot_ratio >= 1:
        raise SystemExit("--group-size-undershoot-ratio must be in [0, 1)")
    size_targets = parse_int_list(args.group_size_targets)
    if any(value <= 0 for value in size_targets):
        raise SystemExit("--group-size-targets values must be >= 1")
    oversamples = parse_int_list(args.group_oversamples)
    min_answers_by_group = parse_int_list(args.group_min_answers)
    if not oversamples:
        raise SystemExit("--group-oversamples must include at least one integer")
    if any(value <= 0 for value in oversamples):
        raise SystemExit("--group-oversamples values must be >= 1")
    if not min_answers_by_group:
        raise SystemExit("--group-min-answers must include at least one integer")
    if any(value <= 0 for value in min_answers_by_group):
        raise SystemExit("--group-min-answers values must be >= 1")
    if args.wheel_size_min <= 0 or args.wheel_size_max <= 0:
        raise SystemExit("--wheel-size-min/--wheel-size-max must be >= 1")
    if args.wheel_size_min > args.wheel_size_max:
        raise SystemExit("--wheel-size-min must be <= --wheel-size-max")
    if args.min_single_letter_tokens < 0:
        raise SystemExit("--min-single-letter-tokens must be >= 0")
    if args.max_single_letter_tokens < 0:
        raise SystemExit("--max-single-letter-tokens must be >= 0")
    if args.min_single_letter_tokens > args.max_single_letter_tokens:
        raise SystemExit(
            "--min-single-letter-tokens must be <= --max-single-letter-tokens"
        )
    if args.min_three_letter_tokens_large_wheel_size <= 0:
        raise SystemExit("--min-three-letter-tokens-large-wheel-size must be >= 1")
    if args.min_three_letter_tokens_large_wheel < 0:
        raise SystemExit("--min-three-letter-tokens-large-wheel must be >= 0")
    if (
        args.min_three_letter_tokens_large_wheel_size <= args.wheel_size_max
        and args.min_three_letter_tokens_large_wheel > args.wheel_size_max
    ):
        raise SystemExit(
            "--min-three-letter-tokens-large-wheel must be <= --wheel-size-max"
        )
    if args.combo_pool_max_words <= 0:
        raise SystemExit("--combo-pool-max-words must be >= 1")
    if args.wheel_sampling_pool_max <= 0:
        raise SystemExit("--wheel-sampling-pool-max must be >= 1")
    if args.group_freq_relax_step < 0:
        raise SystemExit("--group-freq-relax-step must be >= 0")
    if args.group_freq_relax_max_steps < 0:
        raise SystemExit("--group-freq-relax-max-steps must be >= 0")
    if args.group_overlap_window < 0:
        raise SystemExit("--group-overlap-window must be >= 0")
    if args.group_word_cooldown < 0:
        raise SystemExit("--group-word-cooldown must be >= 0")
    if args.group_word_cooldown_early_groups < 0:
        raise SystemExit("--group-word-cooldown-early-groups must be >= 0")
    if args.group_strict_novelty_early_groups < 0:
        raise SystemExit("--group-strict-novelty-early-groups must be >= 0")
    if args.group_word_cooldown_early_levels < 0:
        raise SystemExit("--group-word-cooldown-early-levels must be >= 0")
    if args.group_short_word_len_max <= 0:
        raise SystemExit("--group-short-word-len-max must be >= 1")
    if args.group_short_word_cooldown < 0:
        raise SystemExit("--group-short-word-cooldown must be >= 0")
    if args.group_short_word_cooldown_early_levels < 0:
        raise SystemExit("--group-short-word-cooldown-early-levels must be >= 0")
    if args.group_short_word_signature_cooldown < 0:
        raise SystemExit("--group-short-word-signature-cooldown must be >= 0")
    if args.group_short_word_signature_cooldown_early_levels < 0:
        raise SystemExit(
            "--group-short-word-signature-cooldown-early-levels must be >= 0"
        )
    if args.group_short_word_signature_penalty_weight < 0:
        raise SystemExit("--group-short-word-signature-penalty-weight must be >= 0")
    if args.group_hard_overlap_window < 0:
        raise SystemExit("--group-hard-overlap-window must be >= 0")
    if args.group_hard_overlap_max_shared_words < 0:
        raise SystemExit("--group-hard-overlap-max-shared-words must be >= 0")
    if args.group_reuse_budget_ratio < 0:
        raise SystemExit("--group-reuse-budget-ratio must be >= 0")
    if args.group_reuse_budget_min < 0:
        raise SystemExit("--group-reuse-budget-min must be >= 0")
    if args.group_cross_pack_early_groups < 0:
        raise SystemExit("--group-cross-pack-early-groups must be >= 0")
    if args.group_cross_pack_short_word_max_reuse < 0:
        raise SystemExit("--group-cross-pack-short-word-max-reuse must be >= 0")
    if args.group_cross_pack_long_word_max_reuse < 0:
        raise SystemExit("--group-cross-pack-long-word-max-reuse must be >= 0")
    if args.group_cross_pack_late_start_group < 0:
        raise SystemExit("--group-cross-pack-late-start-group must be >= 0")
    if args.group_cross_pack_late_short_word_max_reuse < 0:
        raise SystemExit("--group-cross-pack-late-short-word-max-reuse must be >= 0")
    if args.group_cross_pack_late_long_word_max_reuse < 0:
        raise SystemExit("--group-cross-pack-late-long-word-max-reuse must be >= 0")
    if args.group_three_letter_signature_early_groups < 0:
        raise SystemExit("--group-three-letter-signature-early-groups must be >= 0")
    if args.group_three_letter_signature_max_reuse < 1:
        raise SystemExit("--group-three-letter-signature-max-reuse must be >= 1")
    if args.group_global_overuse_short_weight < 0:
        raise SystemExit("--group-global-overuse-short-weight must be >= 0")
    if args.group_global_overuse_long_weight < 0:
        raise SystemExit("--group-global-overuse-long-weight must be >= 0")
    if args.group_difficulty_profile_start_group < 0:
        raise SystemExit("--group-difficulty-profile-start-group must be >= 0")
    if args.group_difficulty_target_power <= 0:
        raise SystemExit("--group-difficulty-target-power must be > 0")
    if args.group_difficulty_target_weight < 0:
        raise SystemExit("--group-difficulty-target-weight must be >= 0")
    if args.group_difficulty_floor_margin < 0:
        raise SystemExit("--group-difficulty-floor-margin must be >= 0")
    if args.group_difficulty_ceiling_margin < 0:
        raise SystemExit("--group-difficulty-ceiling-margin must be >= 0")
    if args.group_wheel_shape_min_levels < 0:
        raise SystemExit("--group-wheel-shape-min-levels must be >= 0")
    parse_group_wheel_shape_mix_by_wheel(
        args.group_wheel_shape_mix_by_wheel,
        args.wheel_size_min,
        args.wheel_size_max,
    )

    freq_floors = parse_float_list(args.group_freq_floors)
    specs: list[dict] = []
    for index in range(args.group_count_max):
        if size_targets:
            target_size = (
                size_targets[index] if index < len(size_targets) else size_targets[-1]
            )
        else:
            target_size = min((index + 1) * args.group_size_step, args.group_size_max)
        wheel_size = min(args.wheel_size_min + index, args.wheel_size_max)
        specs.append(
            {
                "id": group_label(args.group_label_start, index),
                "index": index,
                "targetSize": target_size,
                "wheelSize": wheel_size,
                "oversampleMultiplier": (
                    oversamples[index] if index < len(oversamples) else oversamples[-1]
                ),
                "frequencyFloor": (
                    freq_floors[index] if index < len(freq_floors) else None
                ),
                "minAnswers": (
                    min_answers_by_group[index]
                    if index < len(min_answers_by_group)
                    else min_answers_by_group[-1]
                ),
            }
        )
    return specs


def run_generate_and_score(
    script_dir: Path,
    args: argparse.Namespace,
    *,
    run_id: str,
    count: int,
    wheel_size: int,
    min_answers: int,
    seed: int,
    overall_start_epoch: float | None = None,
    overall_work_completed_before: int | float | None = None,
    overall_work_total: int | float | None = None,
    min_single_letter_tokens: int | None = None,
    max_single_letter_tokens: int | None = None,
    min_three_letter_tokens_large_wheel_size: int | None = None,
    min_three_letter_tokens_large_wheel: int | None = None,
) -> tuple[Path, Path]:
    candidate_out = project_path("data", "generated", f"candidate_levels_{run_id}.json")
    scored_out = project_path("data", "generated", f"scored_levels_{run_id}.json")

    min_single_tokens = (
        args.min_single_letter_tokens
        if min_single_letter_tokens is None
        else min_single_letter_tokens
    )
    max_single_tokens = (
        args.max_single_letter_tokens
        if max_single_letter_tokens is None
        else max_single_letter_tokens
    )
    min_three_tokens_wheel_size = (
        args.min_three_letter_tokens_large_wheel_size
        if min_three_letter_tokens_large_wheel_size is None
        else min_three_letter_tokens_large_wheel_size
    )
    min_three_tokens = (
        args.min_three_letter_tokens_large_wheel
        if min_three_letter_tokens_large_wheel is None
        else min_three_letter_tokens_large_wheel
    )

    overall_args: list[str] = []
    if (
        overall_start_epoch is not None
        and overall_work_completed_before is not None
        and overall_work_total is not None
        and overall_work_total > 0
    ):
        overall_args = [
            "--overall-start-epoch",
            str(overall_start_epoch),
            "--overall-work-completed-before",
            str(overall_work_completed_before),
            "--overall-work-total",
            str(overall_work_total),
        ]

    run(
        script_dir,
        str(script_dir / "generate_boards.py"),
        "--out",
        str(candidate_out),
        "--count",
        str(count),
        "--seed",
        str(seed),
        "--bonus-lexicon",
        str(args.bonus_lexicon),
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
        "--crossword-placement-attempts",
        str(args.crossword_placement_attempts),
        "--crossword-max-isolated-words",
        str(args.crossword_max_isolated_words),
        "--crossword-isolated-word-min-freq",
        str(args.crossword_isolated_word_min_freq),
        "--crossword-level-time-limit",
        str(args.crossword_level_time_limit),
        "--combo-sizes",
        args.combo_sizes,
        "--wheel-token-sizes",
        args.wheel_token_sizes,
        "--wheel-size",
        str(wheel_size),
        "--min-single-letter-tokens",
        str(min_single_tokens),
        "--max-single-letter-tokens",
        str(max_single_tokens),
        "--min-three-letter-tokens-large-wheel-size",
        str(min_three_tokens_wheel_size),
        "--min-three-letter-tokens-large-wheel",
        str(min_three_tokens),
        "--min-answer-token-count",
        str(args.min_answer_token_count),
        "--min-answers",
        str(min_answers),
        "--max-word-len",
        str(args.max_word_len),
        "--combo-pool-max-words",
        str(args.combo_pool_max_words),
        "--wheel-sampling-pool-max",
        str(args.wheel_sampling_pool_max),
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
        "--long-word-bias-wheel-size",
        str(args.long_word_bias_wheel_size),
        "--long-word-target-min-len",
        str(args.long_word_target_min_len),
        "--long-word-relax-min-len",
        str(args.long_word_relax_min_len),
        "--min-answer-token-large-wheel-size",
        str(args.min_answer_token_large_wheel_size),
        "--min-answer-token-count-large-wheel",
        str(args.min_answer_token_count_large_wheel),
        "--min-bonus-token-count",
        str(args.min_bonus_token_count),
        "--max-attempts",
        str(auto_max_attempts(args.max_attempts, count)),
        "--workers",
        str(args.workers),
        "--progress-every-seconds",
        str(args.progress_every_seconds),
        "--near-duplicate-answer-jaccard",
        str(args.near_duplicate_answer_jaccard),
        "--near-duplicate-window",
        str(args.near_duplicate_window),
        *overall_args,
    )
    run(
        script_dir,
        str(script_dir / "score_levels.py"),
        "--input",
        str(candidate_out),
        "--out",
        str(scored_out),
        "--combo-sizes",
        args.combo_sizes,
    )
    return candidate_out, scored_out


def run_grouped_pipeline(script_dir: Path, args: argparse.Namespace) -> None:
    groups = build_group_specs(args)
    overall_start_epoch = time.time()
    overall_work_total = sum(
        int(group["targetSize"]) * int(group["oversampleMultiplier"])
        for group in groups
    )
    overall_work_completed = 0
    shape_mix_by_wheel = parse_group_wheel_shape_mix_by_wheel(
        args.group_wheel_shape_mix_by_wheel,
        args.wheel_size_min,
        args.wheel_size_max,
    )
    max_wheel_start_index = max(0, args.wheel_size_max - args.wheel_size_min)

    runs: list[dict] = []

    groups_by_wheel: dict[int, list[dict]] = {}
    for group in groups:
        groups_by_wheel.setdefault(int(group["wheelSize"]), []).append(group)

    for wheel_size in sorted(groups_by_wheel):
        wheel_groups = groups_by_wheel[wheel_size]
        shape_mix = shape_mix_by_wheel.get(wheel_size, [])

        if shape_mix:
            shape_weights = [float(shape["weight"]) for shape in shape_mix]
            for group in wheel_groups:
                target_counts = allocate_weighted_counts(
                    int(group["targetSize"]),
                    shape_weights,
                    args.group_wheel_shape_min_levels,
                )
                shape_targets: list[dict] = []
                for shape, target_count in zip(shape_mix, target_counts):
                    if target_count <= 0:
                        continue
                    shape_targets.append(
                        {
                            "shapeId": shape["id"],
                            "singles": shape["singles"],
                            "doubles": shape["doubles"],
                            "triples": shape["triples"],
                            "weight": round(float(shape["weight"]), 6),
                            "targetLevels": int(target_count),
                        }
                    )
                group["shapeTargets"] = shape_targets
                group["runIds"] = []

            shape_target_requests: dict[tuple[str, int], dict] = {}
            for group in wheel_groups:
                min_answers = int(group["minAnswers"])
                oversample = int(group["oversampleMultiplier"])
                for target in group.get("shapeTargets", []):
                    shape_id = str(target.get("shapeId", "")).strip()
                    target_levels = int(target.get("targetLevels", 0))
                    if not shape_id or target_levels <= 0:
                        continue
                    key = (shape_id, min_answers)
                    bucket = shape_target_requests.setdefault(
                        key,
                        {
                            "requestedCount": 0,
                            "groups": [],
                        },
                    )
                    bucket["requestedCount"] += target_levels * oversample
                    bucket["groups"].append(group)

            for shape in shape_mix:
                shape_id = str(shape["id"])
                matching_requests = [
                    (min_answers, bucket)
                    for (
                        candidate_shape_id,
                        min_answers,
                    ), bucket in shape_target_requests.items()
                    if candidate_shape_id == shape_id
                ]
                if not matching_requests:
                    continue
                matching_requests.sort(key=lambda item: item[0])
                multi_min_answers = len(matching_requests) > 1
                for min_answers, bucket in matching_requests:
                    requested_count = int(bucket["requestedCount"])
                    if requested_count <= 0:
                        continue
                    run_id = (
                        f"wheel-{wheel_size}-shared-shape-"
                        f"{shape['singles']}-{shape['doubles']}-{shape['triples']}"
                    )
                    if multi_min_answers:
                        run_id = f"{run_id}-min{min_answers}"

                    run_seed = args.seed + len(runs)
                    candidate_path, scored_path = run_generate_and_score(
                        script_dir,
                        args,
                        run_id=run_id,
                        count=requested_count,
                        wheel_size=wheel_size,
                        min_answers=min_answers,
                        seed=run_seed,
                        overall_start_epoch=overall_start_epoch,
                        overall_work_completed_before=overall_work_completed,
                        overall_work_total=overall_work_total,
                        min_single_letter_tokens=int(shape["singles"]),
                        max_single_letter_tokens=int(shape["singles"]),
                        min_three_letter_tokens_large_wheel_size=wheel_size,
                        min_three_letter_tokens_large_wheel=int(shape["triples"]),
                    )
                    overall_work_completed += requested_count
                    runs.append(
                        {
                            "id": run_id,
                            "seed": run_seed,
                            "wheelSize": wheel_size,
                            "wheelShape": shape_id,
                            "oversampleMultiplier": [
                                group["oversampleMultiplier"]
                                for group in bucket["groups"]
                            ],
                            "minAnswers": min_answers,
                            "requestedCount": requested_count,
                            "candidatePath": str(candidate_path),
                            "scoredPath": str(scored_path),
                        }
                    )

                    for group in bucket["groups"]:
                        for target in group.get("shapeTargets", []):
                            if (
                                target.get("shapeId") == shape_id
                                and int(target.get("targetLevels", 0)) > 0
                            ):
                                target["runId"] = run_id
                                group.setdefault("runIds", []).append(run_id)

            for group in wheel_groups:
                if not group.get("runIds"):
                    raise SystemExit(
                        f"No mixed-shape runs mapped for group {group['id']}."
                    )
                group["runId"] = group["runIds"][0]
            continue

        groups_by_min_answers: dict[int, list[dict]] = {}
        for group in wheel_groups:
            groups_by_min_answers.setdefault(int(group["minAnswers"]), []).append(group)

        for min_answers, min_answer_groups in sorted(groups_by_min_answers.items()):
            if len(min_answer_groups) == 1 and len(wheel_groups) == 1:
                group = min_answer_groups[0]
                run_id = f"group-{group['id'].lower()}-wheel-{wheel_size}"
            else:
                run_id = f"wheel-{wheel_size}-shared"
                if len(groups_by_min_answers) > 1:
                    run_id = f"{run_id}-min{min_answers}"
            run_seed = args.seed + len(runs)
            candidate_count = sum(
                int(group["targetSize"]) * int(group["oversampleMultiplier"])
                for group in min_answer_groups
            )
            candidate_path, scored_path = run_generate_and_score(
                script_dir,
                args,
                run_id=run_id,
                count=candidate_count,
                wheel_size=wheel_size,
                min_answers=min_answers,
                seed=run_seed,
                overall_start_epoch=overall_start_epoch,
                overall_work_completed_before=overall_work_completed,
                overall_work_total=overall_work_total,
            )
            overall_work_completed += candidate_count
            runs.append(
                {
                    "id": run_id,
                    "seed": run_seed,
                    "wheelSize": wheel_size,
                    "oversampleMultiplier": [
                        group["oversampleMultiplier"] for group in min_answer_groups
                    ],
                    "minAnswers": min_answers,
                    "requestedCount": candidate_count,
                    "candidatePath": str(candidate_path),
                    "scoredPath": str(scored_path),
                }
            )
            for group in min_answer_groups:
                group["runId"] = run_id
                group["runIds"] = [run_id]

    manifest_path = project_path("data", "generated", "group_runs_manifest.json")
    group_plan = {
        "groupCountMax": args.group_count_max,
        "groupLabelStart": (args.group_label_start.strip() or "A")[0].upper(),
        "groupSizeStep": args.group_size_step,
        "groupSizeMax": args.group_size_max,
        "groupSizeTargets": parse_int_list(args.group_size_targets),
        "groupSizeUndershootRatio": args.group_size_undershoot_ratio,
        "oversampleMultipliers": parse_int_list(args.group_oversamples),
        "wheelSizeMin": args.wheel_size_min,
        "wheelSizeMax": args.wheel_size_max,
        "maxWheelStartIndex": max_wheel_start_index,
        "frequencyFloors": parse_float_list(args.group_freq_floors),
        "minAnswersByGroup": parse_int_list(args.group_min_answers),
        "frequencyRelaxStep": args.group_freq_relax_step,
        "frequencyRelaxMaxSteps": args.group_freq_relax_max_steps,
        "noveltyOverlapWindow": args.group_overlap_window,
        "wordCooldownLevels": args.group_word_cooldown,
        "wordCooldownEarlyGroups": args.group_word_cooldown_early_groups,
        "strictNoveltyEarlyGroups": args.group_strict_novelty_early_groups,
        "wordCooldownEarlyLevels": args.group_word_cooldown_early_levels,
        "shortWordLenMax": args.group_short_word_len_max,
        "shortWordCooldownLevels": args.group_short_word_cooldown,
        "shortWordCooldownEarlyLevels": args.group_short_word_cooldown_early_levels,
        "shortWordSignatureCooldownLevels": args.group_short_word_signature_cooldown,
        "shortWordSignatureCooldownEarlyLevels": args.group_short_word_signature_cooldown_early_levels,
        "shortWordSignaturePenaltyWeight": args.group_short_word_signature_penalty_weight,
        "hardOverlapWindow": args.group_hard_overlap_window,
        "hardOverlapMaxSharedWords": args.group_hard_overlap_max_shared_words,
        "groupReuseBudgetRatio": args.group_reuse_budget_ratio,
        "groupReuseBudgetMin": args.group_reuse_budget_min,
        "crossPackEarlyGroups": args.group_cross_pack_early_groups,
        "crossPackShortWordLenMax": args.group_short_word_len_max,
        "crossPackShortWordMaxGroupReuse": args.group_cross_pack_short_word_max_reuse,
        "crossPackLongWordMaxGroupReuse": args.group_cross_pack_long_word_max_reuse,
        "crossPackLateStartGroup": args.group_cross_pack_late_start_group,
        "crossPackLateShortWordMaxGroupReuse": args.group_cross_pack_late_short_word_max_reuse,
        "crossPackLateLongWordMaxGroupReuse": args.group_cross_pack_late_long_word_max_reuse,
        "threeLetterSignatureEarlyGroups": args.group_three_letter_signature_early_groups,
        "threeLetterSignatureMaxGroupReuse": args.group_three_letter_signature_max_reuse,
        "globalOveruseShortWordLenMax": args.group_short_word_len_max,
        "globalOveruseShortWeight": args.group_global_overuse_short_weight,
        "globalOveruseLongWeight": args.group_global_overuse_long_weight,
        "difficultyProfileStartGroup": args.group_difficulty_profile_start_group,
        "difficultyTargetAvgFreqStart": args.group_difficulty_target_avg_freq_start,
        "difficultyTargetAvgFreqEnd": args.group_difficulty_target_avg_freq_end,
        "difficultyTargetPower": args.group_difficulty_target_power,
        "difficultyTargetWeight": args.group_difficulty_target_weight,
        "difficultyFloorMargin": args.group_difficulty_floor_margin,
        "difficultyCeilingMargin": args.group_difficulty_ceiling_margin,
        "preferredAnswerLenMin": args.preferred_answer_len_min,
        "preferredAnswerLenMax": args.preferred_answer_len_max,
        "preferredAnswerLenBonus": args.preferred_answer_len_bonus,
        "shortAnswerPenalty": args.short_answer_penalty,
        "longWordBiasWheelSize": args.long_word_bias_wheel_size,
        "longWordTargetMinLen": args.long_word_target_min_len,
        "longWordRelaxMinLen": args.long_word_relax_min_len,
        "minAnswerTokenLargeWheelSize": args.min_answer_token_large_wheel_size,
        "minAnswerTokenCountLargeWheel": args.min_answer_token_count_large_wheel,
        "comboPoolMaxWords": args.combo_pool_max_words,
        "wheelSamplingPoolMax": args.wheel_sampling_pool_max,
        "comboSizes": args.combo_sizes,
        "wheelTokenSizes": args.wheel_token_sizes,
        "minThreeLetterTokensLargeWheelSize": args.min_three_letter_tokens_large_wheel_size,
        "minThreeLetterTokensLargeWheel": args.min_three_letter_tokens_large_wheel,
        "wheelShapeMixByWheel": shape_mix_by_wheel,
        "wheelShapeMinLevelsPerGroup": args.group_wheel_shape_min_levels,
        "bonusLexicon": str(args.bonus_lexicon),
        "includelist": str(args.includelist),
        "bonusMinZipf": args.bonus_min_zipf,
        "bonusThreeLetterMinZipf": args.bonus_three_letter_min_zipf,
    }
    manifest = {
        "meta": {
            "seed": args.seed,
            "layoutMode": args.layout_mode,
        },
        "groupPlan": group_plan,
        "groups": groups,
        "runs": runs,
    }
    save_json(manifest_path, manifest)

    run(
        script_dir,
        str(script_dir / "export_levels.py"),
        "--manifest",
        str(manifest_path),
    )


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    levels_bundle_path = project_path("data", "generated", "levels.bundle.json")

    use_wordfreq = args.wordfreq_source != "off"

    main_lexicon_cmd = [
        str(script_dir / "build_lexicon.py"),
    ]
    main_lexicon_cmd.extend(["--includelist", str(args.includelist)])
    if not use_wordfreq:
        main_lexicon_cmd.extend(["--wordfreq-source", "off"])
    run(script_dir, *main_lexicon_cmd)

    bonus_lexicon_cmd = [
        str(script_dir / "build_lexicon.py"),
        "--out",
        str(args.bonus_lexicon),
        "--stats-out",
        str(args.bonus_lexicon_stats),
        "--min-zipf",
        str(args.bonus_min_zipf),
    ]
    bonus_lexicon_cmd.extend(
        [
            "--three-letter-max-zipf",
            str(args.bonus_three_letter_min_zipf),
            "--includelist",
            str(args.includelist),
        ]
    )
    if not use_wordfreq:
        bonus_lexicon_cmd.extend(["--wordfreq-source", "off"])
    run(script_dir, *bonus_lexicon_cmd)
    run(
        script_dir,
        str(script_dir / "extract_combos.py"),
        "--combo-sizes",
        args.combo_sizes,
    )

    run_grouped_pipeline(script_dir, args)

    run(script_dir, str(script_dir / "analyze_levels_bundle.py"))

    run(
        script_dir,
        str(script_dir / "build_dictionary_lookup.py"),
        "--bundle",
        str(levels_bundle_path),
        "--dictionary",
        str(args.dictionary_source),
        "--split",
        "--split-dir",
        str(project_path("src", "data")),
    )


def ring_bell() -> None:
    print("\a", end="", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        ring_bell()

from __future__ import annotations

import argparse
import math
from pathlib import Path

from common import (
    DEFAULT_COMBO_SIZES,
    generate_combos,
    load_json,
    now_iso,
    parse_combo_sizes,
    project_path,
    save_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score generated levels for progression ordering."
    )
    parser.add_argument(
        "--input",
        default=str(project_path("data", "generated", "candidate_levels.json")),
        help="Input candidate levels JSON.",
    )
    parser.add_argument(
        "--combos",
        default=str(project_path("data", "processed", "combos.json")),
        help="Combo map JSON, used for ambiguity scoring.",
    )
    parser.add_argument(
        "--out",
        default=str(project_path("data", "generated", "scored_levels.json")),
        help="Output scored levels JSON.",
    )
    parser.add_argument(
        "--combo-sizes",
        default="",
        help="Optional comma-separated combo sizes override (e.g. '2,3').",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def occupied_cells(level: dict) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for answer in level.get("answers", []):
        for row, col in answer.get("path", []):
            cells.add((row, col))
    return cells


def blocked_density(level: dict) -> float:
    rows = int(level["rows"])
    cols = int(level["cols"])
    h = level["walls"]["h"]
    v = level["walls"]["v"]
    occupied = occupied_cells(level)
    blocked = 0
    total = 0

    for r in range(rows - 1):
        for c in range(cols):
            upper = (r, c) in occupied
            lower = (r + 1, c) in occupied
            if not upper and not lower:
                continue
            total += 1
            if not upper or not lower or h[r][c] == 1:
                blocked += 1

    for r in range(rows):
        for c in range(cols - 1):
            left = (r, c) in occupied
            right = (r, c + 1) in occupied
            if not left and not right:
                continue
            total += 1
            if not left or not right or v[r][c] == 1:
                blocked += 1

    return blocked / total if total else 0.0


def average_open_degree(level: dict) -> float:
    rows = int(level["rows"])
    cols = int(level["cols"])
    h = level["walls"]["h"]
    v = level["walls"]["v"]
    occupied = occupied_cells(level)

    total_degree = 0
    for r, c in occupied:
        degree = 0
        if r > 0 and (r - 1, c) in occupied and h[r - 1][c] == 0:
            degree += 1
        if r < rows - 1 and (r + 1, c) in occupied and h[r][c] == 0:
            degree += 1
        if c > 0 and (r, c - 1) in occupied and v[r][c - 1] == 0:
            degree += 1
        if c < cols - 1 and (r, c + 1) in occupied and v[r][c] == 0:
            degree += 1
        total_degree += degree
    return total_degree / len(occupied) if occupied else 0.0


def combo_ambiguity(
    level: dict, combo_to_words: dict[str, list[str]], combo_sizes: tuple[int, ...]
) -> float:
    counts: list[int] = []
    for answer in level.get("answers", []):
        for combo in generate_combos(answer["text"], combo_sizes):
            counts.append(len(combo_to_words.get(combo, [])))
    if not counts:
        return 0.0
    avg = sum(counts) / len(counts)
    return clamp(math.log1p(avg) / math.log1p(35.0))


def freq_difficulty(level: dict) -> float:
    stats = frequency_stats(level)
    avg_freq = stats["avg"]
    if avg_freq <= 0:
        return 1.0
    return clamp((6.5 - avg_freq) / 4.5)


def frequency_stats(level: dict) -> dict[str, float]:
    freqs = sorted(float(item.get("freq", 0.0)) for item in level.get("answers", []))
    if not freqs:
        return {"min": 0.0, "avg": 0.0, "p25": 0.0}
    avg_freq = sum(freqs) / len(freqs)
    p25_index = max(0, min(len(freqs) - 1, int(math.floor((len(freqs) - 1) * 0.25))))
    return {
        "min": freqs[0],
        "avg": avg_freq,
        "p25": freqs[p25_index],
    }


# Weight for intersection density in difficulty scoring (higher = more impact)
INTERSECTION_EASE_WEIGHT = 0.60
# Weight for word length in difficulty scoring (higher = more impact)
LENGTH_EASE_WEIGHT = 0.50


def intersection_ease(level: dict) -> float:
    """
    Higher intersection ratio = easier to solve.
    Returns value 0-1 where higher = easier.
    Actual intersection ratio range: 0.16-0.45
    """
    stats = level.get("placementStats", {})
    ratio = float(stats.get("intersectionRatio", 0.32))
    # Normalize: 0.15 → 1.0 (easiest), 0.45 → 0.0 (hardest)
    # Invert so higher ratio = higher ease
    normalized = clamp((ratio - 0.15) / 0.30)
    return normalized


def length_ease(level: dict) -> float:
    """
    Shorter average word length = easier to solve (more words, more crossings).
    Returns value 0-1 where higher = easier.
    Actual avg length range: 3.0-6.75
    """
    stats = level.get("placementStats", {})
    avg_len = float(stats.get("avgAnswerLength", 4.25))
    # Normalize: 3.0 → 1.0 (easiest), 6.5 → 0.0 (hardest)
    normalized = clamp((6.5 - avg_len) / 3.5)
    return normalized


def level_difficulty(
    level: dict, combo_to_words: dict[str, list[str]], combo_sizes: tuple[int, ...]
) -> tuple[float, dict[str, float]]:
    f_freq = freq_difficulty(level)
    freq_stats = frequency_stats(level)
    f_intersection = intersection_ease(level)
    f_length = length_ease(level)

    # Center ease factors around 0 so they adjust up/down from baseline
    # A level with "average" ease (0.5) gets no adjustment
    # Higher ease (< 0.5 after centering) = easier = lower difficulty
    # Lower ease (> 0.5 after centering) = harder = higher difficulty
    centered_int = f_intersection - 0.5  # Range: -0.5 to +0.5
    centered_len = f_length - 0.5  # Range: -0.5 to +0.5

    # Ease factors adjust difficulty: negative (easier) or positive (harder)
    # Higher intersection/length ease → negative adjustment → lower difficulty
    raw_score = (
        f_freq
        - (centered_int * INTERSECTION_EASE_WEIGHT)
        - (centered_len * LENGTH_EASE_WEIGHT)
    )
    score = round(clamp(raw_score), 4)

    features = {
        "freq": round(f_freq, 4),
        "intersectionEase": round(f_intersection, 4),
        "lengthEase": round(f_length, 4),
        "minAnswerFreq": round(freq_stats["min"], 4),
        "avgAnswerFreq": round(freq_stats["avg"], 4),
        "p25AnswerFreq": round(freq_stats["p25"], 4),
    }
    return score, features


def tier(score: float) -> str:
    if score < 0.34:
        return "easy"
    if score < 0.67:
        return "medium"
    return "hard"


def read_combo_sizes(payload: dict, combo_sizes_arg: str) -> tuple[int, ...]:
    if combo_sizes_arg:
        return parse_combo_sizes(combo_sizes_arg)

    raw_sizes = payload.get("meta", {}).get("comboSizes")
    if isinstance(raw_sizes, list):
        numeric_sizes = [
            size for size in raw_sizes if isinstance(size, int) and size > 0
        ]
        if numeric_sizes:
            return tuple(sorted(set(numeric_sizes)))

    return DEFAULT_COMBO_SIZES


def main() -> None:
    args = parse_args()
    in_path = resolve_path(args.input)
    combos_path = resolve_path(args.combos)
    out_path = resolve_path(args.out)

    payload = load_json(in_path)
    levels = payload.get("levels", [])
    combo_payload = load_json(combos_path)
    combo_to_words = combo_payload.get("comboToWords", {})
    combo_sizes = read_combo_sizes(combo_payload, args.combo_sizes)

    for level in levels:
        score, features = level_difficulty(level, combo_to_words, combo_sizes)
        level["difficulty"] = score
        level["difficultyTier"] = tier(score)
        level["difficultyFeatures"] = features
        level["minAnswerFreq"] = features["minAnswerFreq"]
        level["avgAnswerFreq"] = features["avgAnswerFreq"]
        level["p25AnswerFreq"] = features["p25AnswerFreq"]

    levels.sort(key=lambda item: (item.get("difficulty", 0.0), item.get("id", 0)))
    for idx, level in enumerate(levels, start=1):
        level["campaignIndex"] = idx

    out_payload = {
        "meta": {
            "source": str(in_path),
            "comboSizes": list(combo_sizes),
            "levelCount": len(levels),
        },
        "levels": levels,
    }
    save_json(out_path, out_payload)
    print(f"Scored {len(levels)} levels -> {out_path}")


if __name__ == "__main__":
    main()

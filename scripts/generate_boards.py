from __future__ import annotations

import argparse
import math
import os
import random
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
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


WORKER_COMBO_POOL: list[str] | None = None
WORKER_LEXICON_SET: set[str] | None = None
WORKER_BONUS_LEXICON_SET: set[str] | None = None
WORKER_FREQ_MAP: dict[str, float] | None = None
WORKER_BONUS_FREQ_MAP: dict[str, float] | None = None
WORKER_COMBO_SIZES: tuple[int, ...] | None = None
WORKER_ARGS: argparse.Namespace | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate candidate levels for supported board layouts."
    )
    parser.add_argument(
        "--lexicon",
        default=str(project_path("data", "processed", "lexicon.json")),
        help="Path to lexicon JSON.",
    )
    parser.add_argument(
        "--bonus-lexicon",
        default="",
        help="Optional bonus lexicon JSON path (defaults to --lexicon).",
    )
    parser.add_argument(
        "--out",
        default=str(project_path("data", "generated", "candidate_levels.json")),
        help="Output path for candidate levels.",
    )
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument(
        "--layout-mode",
        choices=("maze-path", "crossword-letter"),
        default="crossword-letter",
        help="Board layout mode. Default: crossword-letter",
    )
    parser.add_argument("--size-min", type=int, default=3)
    parser.add_argument("--size-max", type=int, default=4)
    parser.add_argument("--rows-min", type=int, default=10)
    parser.add_argument("--rows-max", type=int, default=10)
    parser.add_argument("--cols-min", type=int, default=10)
    parser.add_argument("--cols-max", type=int, default=10)
    parser.add_argument(
        "--crossword-placement-attempts",
        type=int,
        default=90,
        help="Placement retries per crossword board size.",
    )
    parser.add_argument(
        "--crossword-max-isolated-words",
        type=int,
        default=2,
        help="Fallback cap for words outside the largest component.",
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
    parser.add_argument("--wheel-size", type=int, default=7)
    parser.add_argument("--min-word-len", type=int, default=3)
    parser.add_argument("--max-word-len", type=int, default=12)
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
    parser.add_argument("--min-answers", type=int, default=8)
    parser.add_argument(
        "--max-answers",
        type=int,
        default=0,
        help="Maximum answers per level (0 = uncapped).",
    )
    parser.add_argument("--max-bonus-words", type=int, default=220)
    parser.add_argument("--max-candidate-words", type=int, default=2500)
    parser.add_argument("--max-attempts", type=int, default=6000)
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help=(
            "Parallel worker processes "
            "(0 = logical cores minus one when <8, otherwise minus two)."
        ),
    )
    parser.add_argument(
        "--progress-every-seconds",
        type=float,
        default=15.0,
        help="Print generation progress every N seconds (0 disables progress output).",
    )
    parser.add_argument(
        "--overall-start-epoch",
        type=float,
        default=0.0,
        help="Optional Unix epoch timestamp when the parent generation pipeline started.",
    )
    parser.add_argument(
        "--overall-work-completed-before",
        type=float,
        default=0.0,
        help="Optional overall work completed before this run (used for overall ETA).",
    )
    parser.add_argument(
        "--overall-work-total",
        type=float,
        default=0.0,
        help="Optional total overall work units for the parent generation pipeline.",
    )
    parser.add_argument(
        "--near-duplicate-answer-jaccard",
        type=float,
        default=0.4,
        help="Reject recent near-duplicate boards when answer-set Jaccard is at least this high.",
    )
    parser.add_argument(
        "--near-duplicate-window",
        type=int,
        default=20,
        help="How many most-recent accepted levels to check for answer overlap dedup.",
    )
    parser.add_argument("--block-prob", type=float, default=0.35)
    parser.add_argument(
        "--combo-sizes",
        default=",".join(str(size) for size in DEFAULT_COMBO_SIZES),
        help="Comma-separated sizes for exported/scored combos. Default: 1,2",
    )
    parser.add_argument(
        "--wheel-token-sizes",
        default="1,2",
        help="Comma-separated wheel token sizes, e.g. '1,2'.",
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
        "--min-answer-token-count",
        type=int,
        default=2,
        help="Minimum wheel-token count required for answer words.",
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
        help="Minimum wheel-token count required for bonus/valid words.",
    )
    # Variance parameters for difficulty scaling
    parser.add_argument(
        "--variance-overlap-weight-min",
        type=float,
        default=60.0,
        help="Minimum overlap score weight for placement variance.",
    )
    parser.add_argument(
        "--variance-overlap-weight-max",
        type=float,
        default=100.0,
        help="Maximum overlap score weight for placement variance.",
    )
    parser.add_argument(
        "--variance-short-penalty-min",
        type=float,
        default=70.0,
        help="Minimum short-answer penalty for selection variance.",
    )
    parser.add_argument(
        "--variance-short-penalty-max",
        type=float,
        default=140.0,
        help="Maximum short-answer penalty for selection variance.",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def token_has_vowel(token: str) -> bool:
    return any(char in "aeiou" for char in token)


def default_worker_count() -> int:
    cpu_count = os.cpu_count() or 1
    reserve = 2 if cpu_count >= 8 else 1
    return max(1, cpu_count - reserve)


def resolve_worker_count(raw_workers: int) -> int:
    if raw_workers < 0:
        raise SystemExit("--workers must be >= 0")
    if raw_workers == 0:
        return default_worker_count()
    return max(1, raw_workers)


def token_text(token: str, mode: str) -> str:
    if mode == "reverse" and len(token) >= 2:
        return token[::-1]
    return token


def format_eta(seconds: float) -> str:
    if seconds < 0 or not math.isfinite(seconds):
        return "--"

    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def dynamic_crossword_time_limit(
    completed_attempts: int,
    started_at: float,
    default_limit: float = 3.0,
) -> float:
    if completed_attempts <= 0:
        return default_limit
    elapsed = max(0.001, time.monotonic() - started_at)
    average_attempt_time = elapsed / completed_attempts
    return max(1.0, average_attempt_time * 2.5)


def build_combo_pool(
    lexicon_words: list[dict], combo_sizes: tuple[int, ...], max_words: int
) -> list[str]:
    scores: dict[str, float] = {}
    for entry in lexicon_words[: min(len(lexicon_words), max_words)]:
        word = entry["word"]
        freq = float(entry.get("freq", 0.0))
        for combo in generate_combos(word, combo_sizes):
            scores[combo] = scores.get(combo, 0.0) + max(0.1, freq)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
    return [combo for combo, _ in ranked]


def choose_wheel_from_pool(
    combo_pool: list[str],
    sampling_pool_max: int,
    wheel_size: int,
    min_single_letter_tokens: int,
    max_single_letter_tokens: int,
    min_three_letter_tokens: int,
    max_three_letter_tokens: int,
    rng: random.Random,
) -> list[str]:
    if not combo_pool:
        return ["th", "he", "an", "in", "er", "on"][:wheel_size]

    sampling_pool = combo_pool[: min(len(combo_pool), max(1, sampling_pool_max))]
    vowel_tokens = [token for token in sampling_pool if token_has_vowel(token)]
    single_letter_tokens = [token for token in sampling_pool if len(token) == 1]
    three_letter_tokens = [token for token in sampling_pool if len(token) == 3]
    if min_three_letter_tokens > 0 and not three_letter_tokens:
        three_letter_tokens = [token for token in combo_pool if len(token) == 3]
    single_letter_limit = max(0, max_single_letter_tokens)
    three_letter_limit = max(0, max_three_letter_tokens)
    target_single_letters = min(
        wheel_size,
        max(0, min_single_letter_tokens),
        len(single_letter_tokens),
        single_letter_limit,
    )
    target_three_letters = min(
        max(0, wheel_size - target_single_letters),
        max(0, min_three_letter_tokens),
        len(three_letter_tokens),
        three_letter_limit,
    )

    wheel: list[str] = []

    def can_add(token: str) -> bool:
        if token in wheel:
            return False
        if len(token) == 1:
            singles = sum(1 for item in wheel if len(item) == 1)
            if singles >= single_letter_limit:
                return False
        if len(token) == 3:
            triples = sum(1 for item in wheel if len(item) == 3)
            if triples >= three_letter_limit:
                return False
        return True

    attempts = 0
    while (
        len([token for token in wheel if len(token) == 1]) < target_single_letters
        and attempts < 300
    ):
        attempts += 1
        token = rng.choice(single_letter_tokens)
        if can_add(token):
            wheel.append(token)

    attempts = 0
    while (
        len([token for token in wheel if len(token) == 3]) < target_three_letters
        and attempts < 300
    ):
        attempts += 1
        token = rng.choice(three_letter_tokens)
        if can_add(token):
            wheel.append(token)

    target_vowel_tokens = min(2, wheel_size, len(vowel_tokens))
    attempts = 0

    while len(wheel) < target_vowel_tokens and attempts < 300:
        attempts += 1
        token = rng.choice(vowel_tokens[: min(len(vowel_tokens), 300)])
        if can_add(token):
            wheel.append(token)

    attempts = 0
    while len(wheel) < wheel_size and attempts < 1000:
        attempts += 1
        token = rng.choice(sampling_pool)
        if can_add(token):
            wheel.append(token)

    for token in sampling_pool:
        if len(wheel) >= wheel_size:
            break
        if can_add(token):
            wheel.append(token)

    if len(wheel) < wheel_size:
        for token in combo_pool:
            if len(wheel) >= wheel_size:
                break
            if can_add(token):
                wheel.append(token)

    rng.shuffle(wheel)
    return wheel


def candidate_words_from_wheel(
    wheel_tokens: list[str],
    lexicon_set: set[str],
    min_word_len: int,
    max_word_len: int,
    max_candidate_words: int,
    mode: str = "forward",
) -> tuple[dict[str, set[int]], dict[str, list[tuple[str, ...]]]]:
    found_masks: dict[str, set[int]] = {}
    token_sequences: dict[str, list[tuple[str, ...]]] = {}
    sequence_seen: dict[str, set[tuple[str, ...]]] = {}
    max_sequences_per_word = 12

    def walk(current: str, used_mask: int, used_tokens: tuple[str, ...]) -> None:
        if len(current) >= min_word_len and current in lexicon_set:
            existing = found_masks.get(current)
            if existing is not None:
                existing.add(used_mask)
            elif len(found_masks) < max_candidate_words:
                found_masks[current] = {used_mask}

            if current in found_masks:
                seen = sequence_seen.setdefault(current, set())
                if (
                    used_tokens not in seen
                    and len(token_sequences.get(current, [])) < max_sequences_per_word
                ):
                    token_sequences.setdefault(current, []).append(used_tokens)
                    seen.add(used_tokens)

        if len(current) >= max_word_len:
            return

        for idx, token in enumerate(wheel_tokens):
            if used_mask & (1 << idx):
                continue
            nxt = current + token_text(token, mode)
            if len(nxt) > max_word_len:
                continue
            walk(nxt, used_mask | (1 << idx), used_tokens + (token,))

    walk("", 0, ())
    return found_masks, token_sequences


def grid_neighbors(rows: int, cols: int, r: int, c: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if r > 0:
        out.append((r - 1, c))
    if r < rows - 1:
        out.append((r + 1, c))
    if c > 0:
        out.append((r, c - 1))
    if c < cols - 1:
        out.append((r, c + 1))
    return out


def random_simple_path(
    rows: int, cols: int, length: int, rng: random.Random
) -> list[tuple[int, int]] | None:
    if length > rows * cols:
        return None

    for _ in range(120):
        start = (rng.randrange(rows), rng.randrange(cols))
        path = [start]
        used = {start}
        while len(path) < length:
            r, c = path[-1]
            choices = [
                pos for pos in grid_neighbors(rows, cols, r, c) if pos not in used
            ]
            if not choices:
                break
            nxt = rng.choice(choices)
            used.add(nxt)
            path.append(nxt)
        if len(path) == length:
            return path
    return None


def open_edge(
    h: list[list[int]], v: list[list[int]], a: tuple[int, int], b: tuple[int, int]
) -> None:
    ar, ac = a
    br, bc = b
    if ar == br:
        left = min(ac, bc)
        v[ar][left] = 0
        return
    up = min(ar, br)
    h[up][ac] = 0


def place_words(
    words: list[str],
    rows: int,
    cols: int,
    wheel_tokens: list[str],
    block_prob: float,
    rng: random.Random,
) -> (
    tuple[list[list[str]], list[list[int]], list[list[int]], dict[str, list[list[int]]]]
    | None
):
    cells: list[list[str | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    h = [[1 for _ in range(cols)] for _ in range(rows - 1)]
    v = [[1 for _ in range(cols - 1)] for _ in range(rows)]
    paths: dict[str, list[list[int]]] = {}

    for word in sorted(words, key=len, reverse=True):
        placed = False
        for _ in range(250):
            path = random_simple_path(rows, cols, len(word), rng)
            if path is None:
                continue
            ok = True
            for idx, (r, c) in enumerate(path):
                current = cells[r][c]
                char = word[idx]
                if current is not None and current != char:
                    ok = False
                    break
            if not ok:
                continue

            for idx, (r, c) in enumerate(path):
                cells[r][c] = word[idx]
                if idx > 0:
                    open_edge(h, v, path[idx - 1], path[idx])

            paths[word] = [[r, c] for r, c in path]
            placed = True
            break

        if not placed:
            return None

    extra_open_prob = max(0.0, (1.0 - block_prob) * 0.3)
    for r in range(rows - 1):
        for c in range(cols):
            if h[r][c] == 1 and rng.random() < extra_open_prob:
                h[r][c] = 0
    for r in range(rows):
        for c in range(cols - 1):
            if v[r][c] == 1 and rng.random() < extra_open_prob:
                v[r][c] = 0

    fill_chars = [char for token in wheel_tokens for char in token]
    if not fill_chars:
        fill_chars = list("etaoin")

    finished_cells: list[list[str]] = []
    for row in cells:
        out_row: list[str] = []
        for char in row:
            out_row.append(char if char is not None else rng.choice(fill_chars))
        finished_cells.append(out_row)

    return finished_cells, h, v, paths


def straight_paths(rows: int, cols: int, length: int) -> list[list[tuple[int, int]]]:
    out: list[list[tuple[int, int]]] = []
    if length <= 0:
        return out

    if length <= cols:
        for r in range(rows):
            for c in range(cols - length + 1):
                out.append([(r, c + idx) for idx in range(length)])

    if length <= rows:
        for c in range(cols):
            for r in range(rows - length + 1):
                out.append([(r + idx, c) for idx in range(length)])

    return out


def derive_walls_from_paths(
    rows: int, cols: int, paths: dict[str, list[tuple[int, int]]]
) -> tuple[list[list[int]], list[list[int]]]:
    h = [[1 for _ in range(cols)] for _ in range(rows - 1)]
    v = [[1 for _ in range(cols - 1)] for _ in range(rows)]
    for path in paths.values():
        for idx in range(1, len(path)):
            open_edge(h, v, path[idx - 1], path[idx])
    return h, v


def derive_walls_sparse(
    rows: int,
    cols: int,
    paths: dict[str, list[list[int]]],
    h: list[list[int]],
    v: list[list[int]],
) -> dict[str, list[int]]:
    """
    Build sparse cell-based walls representation.
    Returns dict mapping "row,col" -> [top, right, bottom, left]
    Walls are 1 if present, 0 if absent.
    - Boundary walls (edges of occupied area) are always 1
    - Internal walls between adjacent occupied cells use puzzle wall value
    """
    # Get all occupied cells
    occupied: set[tuple[int, int]] = set()
    for path in paths.values():
        for cell in path:
            occupied.add((cell[0], cell[1]))

    walls: dict[str, list[int]] = {}
    for r, c in occupied:
        # Top wall: boundary if no occupied cell above, else puzzle wall value
        if (r - 1, c) not in occupied:
            top = 1
        elif r > 0:
            top = h[r - 1][c]
        else:
            top = 1

        # Bottom wall: boundary if no occupied cell below, else puzzle wall value
        if (r + 1, c) not in occupied:
            bottom = 1
        elif r < rows - 1:
            bottom = h[r][c]
        else:
            bottom = 1

        # Left wall: boundary if no occupied cell to left, else puzzle wall value
        if (r, c - 1) not in occupied:
            left = 1
        elif c > 0:
            left = v[r][c - 1]
        else:
            left = 1

        # Right wall: boundary if no occupied cell to right, else puzzle wall value
        if (r, c + 1) not in occupied:
            right = 1
        elif c < cols - 1:
            right = v[r][c]
        else:
            right = 1

        walls[f"{r},{c}"] = [top, right, bottom, left]

    return walls


def word_components(paths: dict[str, list[tuple[int, int]]]) -> list[set[str]]:
    words = list(paths)
    if not words:
        return []

    cell_to_words: dict[tuple[int, int], list[str]] = {}
    for word, path in paths.items():
        for cell in path:
            cell_to_words.setdefault(cell, []).append(word)

    neighbors: dict[str, set[str]] = {word: set() for word in words}
    for linked_words in cell_to_words.values():
        if len(linked_words) <= 1:
            continue
        for word in linked_words:
            neighbors[word].update(other for other in linked_words if other != word)

    seen: set[str] = set()
    components: list[set[str]] = []
    for word in words:
        if word in seen:
            continue
        stack = [word]
        comp: set[str] = set()
        seen.add(word)
        while stack:
            current = stack.pop()
            comp.add(current)
            for nxt in neighbors[current]:
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        components.append(comp)
    return components


def isolated_words_from_components(components: list[set[str]]) -> set[str]:
    if len(components) <= 1:
        return set()
    largest = max(components, key=len)
    isolated: set[str] = set()
    for comp in components:
        if comp is largest:
            continue
        isolated.update(comp)
    return isolated


def detached_components_from_components(components: list[set[str]]) -> list[set[str]]:
    if len(components) <= 1:
        return []
    largest = max(components, key=len)
    return [comp for comp in components if comp is not largest]


def isolate_words_common_enough(
    isolated_words: set[str],
    all_words: list[str],
    freq_map: dict[str, float],
    min_freq: float,
) -> bool:
    if not isolated_words:
        return True

    all_freqs = sorted(freq_map.get(word, 0.0) for word in all_words)
    if not all_freqs:
        return False
    threshold_index = max(0, math.ceil(len(all_freqs) * 0.75) - 1)
    threshold = max(min_freq, all_freqs[threshold_index])
    return all(freq_map.get(word, 0.0) >= threshold for word in isolated_words)


def place_words_crossword_tokens(
    words: list[str],
    rows: int,
    cols: int,
    word_token_sequences: dict[str, list[tuple[str, ...]]],
    wheel_tokens: list[str],
    freq_map: dict[str, float],
    placement_attempts: int,
    max_isolated_words: int,
    isolated_word_min_freq: float,
    allow_disconnected: bool,
    deadline: float | None,
    rng: random.Random,
    overlap_score_weight: float = 80.0,
) -> (
    tuple[
        list[list[str]],
        list[list[int]],
        list[list[int]],
        dict[str, list[list[int]]],
        dict[str, int | bool],
    ]
    | None
):
    usable_sequences: dict[str, list[tuple[str, ...]]] = {}
    max_seq_len: dict[str, int] = {}
    for word in words:
        options = [
            seq
            for seq in word_token_sequences.get(word, [])
            if 2 <= len(seq) <= max(rows, cols)
        ]
        if not options:
            return None
        usable_sequences[word] = options
        max_seq_len[word] = max(len(seq) for seq in options)

    candidate_limit = 140
    center_r = (rows - 1) / 2.0
    center_c = (cols - 1) / 2.0

    lengths = sorted(
        {len(seq) for sequences in usable_sequences.values() for seq in sequences}
    )
    slots_by_len = {length: straight_paths(rows, cols, length) for length in lengths}

    placement_templates: dict[
        str,
        list[tuple[list[tuple[int, int, str]], list[tuple[int, int]], float]],
    ] = {}
    for word in words:
        templates: list[
            tuple[list[tuple[int, int, str]], list[tuple[int, int]], float]
        ] = []
        for seq in usable_sequences[word]:
            for path in slots_by_len[len(seq)]:
                pairs = [(row, col, token) for (row, col), token in zip(path, seq)]
                center_penalty = sum(
                    abs(row - center_r) + abs(col - center_c) for row, col in path
                )
                templates.append((pairs, path, center_penalty))
        if not templates:
            return None
        placement_templates[word] = templates

    fallback_fill = wheel_tokens[:] if wheel_tokens else ["th", "an", "er", "on"]

    placement_modes = (True, False) if allow_disconnected else (True,)
    for require_connected in placement_modes:
        if deadline is not None and time.monotonic() > deadline:
            break
        tries = max(1, placement_attempts)
        for _ in range(tries):
            if deadline is not None and time.monotonic() > deadline:
                break
            cells: list[list[str | None]] = [
                [None for _ in range(cols)] for _ in range(rows)
            ]
            usage = [[0 for _ in range(cols)] for _ in range(rows)]
            placed_paths: dict[str, list[tuple[int, int]]] = {}

            jitter = {word: rng.random() for word in words}
            placement_order = sorted(
                words,
                key=lambda word: (
                    -max_seq_len[word],
                    len(usable_sequences[word]),
                    -freq_map.get(word, 0.0),
                    jitter[word],
                    word,
                ),
            )

            def collect_candidates(
                word: str,
                require_overlap: bool,
            ) -> list[tuple[float, int, list[tuple[int, int]], tuple[str, ...]]]:
                options: list[
                    tuple[float, int, list[tuple[int, int]], tuple[str, ...]]
                ] = []
                for pairs, path, center_penalty in placement_templates[word]:
                    overlap = 0
                    fits = True
                    for r, c, token in pairs:
                        current = cells[r][c]
                        if current is not None and current != token:
                            fits = False
                            break
                        if current is not None:
                            overlap += 1
                    if not fits:
                        continue
                    if has_single_axis_overlap(path, placed_paths):
                        continue
                    if require_overlap and overlap == 0:
                        continue

                    seq = tuple(token for _, _, token in pairs)
                    score = (
                        (overlap * overlap_score_weight)
                        - (center_penalty * 2.2)
                        + rng.random()
                    )
                    options.append((score, overlap, path, seq))

                options.sort(key=lambda item: item[0], reverse=True)
                return options[:candidate_limit]

            def backtrack(index: int, no_overlap_words: int) -> bool:
                if deadline is not None and time.monotonic() > deadline:
                    return False
                if index >= len(placement_order):
                    return True

                word = placement_order[index]
                needs_overlap = require_connected and index > 0
                candidates = collect_candidates(word, needs_overlap)
                if not candidates:
                    return False

                for _, overlap, path, seq in candidates:
                    next_no_overlap = no_overlap_words
                    if index > 0 and overlap == 0:
                        next_no_overlap += 1
                        if next_no_overlap > max_isolated_words:
                            continue

                    for (r, c), token in zip(path, seq):
                        if usage[r][c] == 0:
                            cells[r][c] = token
                        usage[r][c] += 1
                    placed_paths[word] = path

                    if backtrack(index + 1, next_no_overlap):
                        return True

                    del placed_paths[word]
                    for r, c in path:
                        usage[r][c] -= 1
                        if usage[r][c] == 0:
                            cells[r][c] = None

                return False

            if not backtrack(0, 0):
                continue

            components = word_components(placed_paths)
            detached_components = detached_components_from_components(components)
            isolated_words = isolated_words_from_components(components)
            if require_connected and len(components) != 1:
                continue
            if not require_connected:
                if any(len(comp) != 1 for comp in detached_components):
                    continue
                if len(isolated_words) > max_isolated_words:
                    continue
                if not isolate_words_common_enough(
                    isolated_words,
                    words,
                    freq_map,
                    isolated_word_min_freq,
                ):
                    continue

            h, v = derive_walls_from_paths(rows, cols, placed_paths)
            occupied_cells = {(r, c) for path in placed_paths.values() for r, c in path}

            finished_cells: list[list[str]] = []
            for row in cells:
                out_row: list[str] = []
                for token in row:
                    out_row.append(
                        token if token is not None else rng.choice(fallback_fill)
                    )
                finished_cells.append(out_row)

            finished_paths = {
                word: [[r, c] for r, c in path] for word, path in placed_paths.items()
            }
            # Compute intersection metrics
            cell_visits: dict[tuple[int, int], int] = {}
            for path in placed_paths.values():
                for cell in path:
                    cell_visits[cell] = cell_visits.get(cell, 0) + 1
            inter_count = sum(1 for count in cell_visits.values() if count >= 2)
            inter_ratio = inter_count / len(occupied_cells) if occupied_cells else 0.0
            # Compute average answer length
            avg_answer_len = (
                sum(len(w) for w in placed_paths.keys()) / len(placed_paths)
                if placed_paths
                else 0.0
            )
            layout_stats = {
                "connected": len(components) == 1,
                "componentCount": len(components),
                "isolatedWordCount": len(isolated_words),
                "disconnectedWordCount": len(isolated_words),
                "occupiedCellCount": len(occupied_cells),
                "gridCells": rows * cols,
                "intersectionCount": inter_count,
                "intersectionRatio": round(inter_ratio, 6),
                "avgAnswerLength": round(avg_answer_len, 4),
            }
            return finished_cells, h, v, finished_paths, layout_stats

    return None


def place_words_crossword_letters(
    words: list[str],
    rows: int,
    cols: int,
    wheel_tokens: list[str],
    freq_map: dict[str, float],
    placement_attempts: int,
    max_isolated_words: int,
    isolated_word_min_freq: float,
    allow_disconnected: bool,
    deadline: float | None,
    rng: random.Random,
    overlap_score_weight: float = 80.0,
) -> (
    tuple[
        list[list[str]],
        list[list[int]],
        list[list[int]],
        dict[str, list[list[int]]],
        dict[str, int | bool],
    ]
    | None
):
    candidate_limit = 140
    center_r = (rows - 1) / 2.0
    center_c = (cols - 1) / 2.0
    slots_by_len = {
        length: straight_paths(rows, cols, length)
        for length in {len(word) for word in words}
    }
    fallback_fill = list({char for token in wheel_tokens for char in token}) or list(
        "etaoin"
    )

    placement_modes = (True, False) if allow_disconnected else (True,)
    for require_connected in placement_modes:
        if deadline is not None and time.monotonic() > deadline:
            break
        tries = max(1, placement_attempts)
        for _ in range(tries):
            if deadline is not None and time.monotonic() > deadline:
                break

            cells: list[list[str | None]] = [
                [None for _ in range(cols)] for _ in range(rows)
            ]
            usage = [[0 for _ in range(cols)] for _ in range(rows)]
            placed_paths: dict[str, list[tuple[int, int]]] = {}

            jitter = {word: rng.random() for word in words}
            placement_order = sorted(
                words,
                key=lambda word: (
                    -len(word),
                    -freq_map.get(word, 0.0),
                    jitter[word],
                    word,
                ),
            )

            def collect_candidates(
                word: str,
                require_overlap: bool,
            ) -> list[tuple[float, int, list[tuple[int, int]]]]:
                options: list[tuple[float, int, list[tuple[int, int]]]] = []
                for path in slots_by_len[len(word)]:
                    overlap = 0
                    fits = True
                    for idx, (r, c) in enumerate(path):
                        current = cells[r][c]
                        letter = word[idx]
                        if current is not None and current != letter:
                            fits = False
                            break
                        if current is not None:
                            overlap += 1
                    if not fits:
                        continue
                    if has_single_axis_overlap(path, placed_paths):
                        continue
                    if require_overlap and overlap == 0:
                        continue

                    center_penalty = sum(
                        abs(row - center_r) + abs(col - center_c) for row, col in path
                    )
                    score = (
                        (overlap * overlap_score_weight)
                        - (center_penalty * 2.2)
                        + rng.random()
                    )
                    options.append((score, overlap, path))

                options.sort(key=lambda item: item[0], reverse=True)
                return options[:candidate_limit]

            def backtrack(index: int, no_overlap_words: int) -> bool:
                if deadline is not None and time.monotonic() > deadline:
                    return False
                if index >= len(placement_order):
                    return True

                word = placement_order[index]
                needs_overlap = require_connected and index > 0
                candidates = collect_candidates(word, needs_overlap)
                if not candidates:
                    return False

                for _, overlap, path in candidates:
                    next_no_overlap = no_overlap_words
                    if index > 0 and overlap == 0:
                        next_no_overlap += 1
                        if next_no_overlap > max_isolated_words:
                            continue

                    for idx, (r, c) in enumerate(path):
                        if usage[r][c] == 0:
                            cells[r][c] = word[idx]
                        usage[r][c] += 1
                    placed_paths[word] = path

                    if backtrack(index + 1, next_no_overlap):
                        return True

                    del placed_paths[word]
                    for r, c in path:
                        usage[r][c] -= 1
                        if usage[r][c] == 0:
                            cells[r][c] = None

                return False

            if not backtrack(0, 0):
                continue

            components = word_components(placed_paths)
            detached_components = detached_components_from_components(components)
            isolated_words = isolated_words_from_components(components)
            if require_connected and len(components) != 1:
                continue
            if not require_connected:
                if any(len(comp) != 1 for comp in detached_components):
                    continue
                if len(isolated_words) > max_isolated_words:
                    continue
                if not isolate_words_common_enough(
                    isolated_words,
                    words,
                    freq_map,
                    isolated_word_min_freq,
                ):
                    continue

            h, v = derive_walls_from_paths(rows, cols, placed_paths)
            occupied_cells = {(r, c) for path in placed_paths.values() for r, c in path}

            finished_cells: list[list[str]] = []
            for row in cells:
                out_row: list[str] = []
                for letter in row:
                    out_row.append(
                        letter if letter is not None else rng.choice(fallback_fill)
                    )
                finished_cells.append(out_row)

            finished_paths = {
                word: [[r, c] for r, c in path] for word, path in placed_paths.items()
            }
            # Compute intersection metrics
            cell_visits: dict[tuple[int, int], int] = {}
            for path in placed_paths.values():
                for cell in path:
                    cell_visits[cell] = cell_visits.get(cell, 0) + 1
            inter_count = sum(1 for count in cell_visits.values() if count >= 2)
            inter_ratio = inter_count / len(occupied_cells) if occupied_cells else 0.0
            # Compute average answer length
            avg_answer_len = (
                sum(len(w) for w in placed_paths.keys()) / len(placed_paths)
                if placed_paths
                else 0.0
            )
            layout_stats = {
                "connected": len(components) == 1,
                "componentCount": len(components),
                "isolatedWordCount": len(isolated_words),
                "disconnectedWordCount": len(isolated_words),
                "occupiedCellCount": len(occupied_cells),
                "gridCells": rows * cols,
                "intersectionCount": inter_count,
                "intersectionRatio": round(inter_ratio, 6),
                "avgAnswerLength": round(avg_answer_len, 4),
            }
            return finished_cells, h, v, finished_paths, layout_stats

    return None


def path_spells_word(
    cells: list[list[str]], path: list[list[int]], word: str, mode: str = "forward"
) -> bool:
    if mode != "forward":
        return False
    path_text = "".join(cells[row][col] for row, col in path)
    return path_text == word


def path_is_straight(path: list[list[int]]) -> bool:
    if len(path) < 2:
        return False
    same_row = len({row for row, _ in path}) == 1
    same_col = len({col for _, col in path}) == 1
    return same_row or same_col


def path_axis(path: list[tuple[int, int]]) -> str:
    rows = {row for row, _ in path}
    return "h" if len(rows) == 1 else "v"


def has_single_axis_overlap(
    candidate_path: list[tuple[int, int]],
    placed_paths: dict[str, list[tuple[int, int]]],
) -> bool:
    candidate_cells = set(candidate_path)
    candidate_axis = path_axis(candidate_path)
    for existing_path in placed_paths.values():
        overlap = candidate_cells.intersection(existing_path)
        if not overlap:
            continue
        if len(overlap) > 1:
            return True
        if path_axis(existing_path) == candidate_axis:
            return True
    return False


def min_token_count(word_masks: set[int]) -> int:
    return min(mask.bit_count() for mask in word_masks)


def required_mode_count() -> int:
    return 2


def validate_letter_grid(
    cells: list[list[str]],
    paths: dict[str, list[list[int]]],
    answer_modes: dict[str, set[str]],
) -> bool:
    occupied = {(row, col) for path in paths.values() for row, col in path}
    if not occupied:
        return False

    for row, col in occupied:
        cell = cells[row][col]
        if not isinstance(cell, str) or len(cell) != 1:
            return False

    forward_only_count = 0
    reverse_only_count = 0
    for word, path in paths.items():
        if len(path) != len(word) or not path_is_straight(path):
            return False
        if not path_spells_word(cells, path, word):
            return False
        modes = answer_modes.get(word)
        if not modes:
            return False
        if modes == {"forward"}:
            forward_only_count += 1
        elif modes == {"reverse"}:
            reverse_only_count += 1

    required = required_mode_count()
    return forward_only_count >= required and reverse_only_count >= required


def pick_answer_words(
    candidate_word_masks: dict[str, set[int]],
    candidate_word_modes: dict[str, set[str]],
    freq_map: dict[str, float],
    min_answers: int,
    max_answers: int,
    wheel_size: int,
    short_answer_len: int,
    max_short_answers: int | None,
    answer_length_weight: float,
    preferred_answer_len_min: int,
    preferred_answer_len_max: int,
    preferred_answer_len_bonus: float,
    short_answer_penalty: float,
    rng: random.Random,
) -> tuple[list[str], list[int]]:
    if len(candidate_word_masks) < min_answers:
        return [], []

    forward_only = [
        word for word, modes in candidate_word_modes.items() if modes == {"forward"}
    ]
    reverse_only = [
        word for word, modes in candidate_word_modes.items() if modes == {"reverse"}
    ]
    required_per_mode = required_mode_count()
    if len(forward_only) < required_per_mode or len(reverse_only) < required_per_mode:
        return [], []

    ranked_words = sorted(
        candidate_word_masks,
        key=lambda item: (-len(item), -freq_map.get(item, 0.0), item),
    )
    top_pool = ranked_words
    max_target = len(top_pool) if max_answers <= 0 else min(max_answers, len(top_pool))
    if max_target < min_answers:
        return [], []

    full_mask = (1 << wheel_size) - 1
    selected_words: list[str] = []
    selected_set: set[str] = set()
    token_counts = [0 for _ in range(wheel_size)]
    covered_mask = 0
    selected_freqs: list[float] = []
    forward_only_count = 0
    reverse_only_count = 0
    short_count = 0

    while len(selected_words) < max_target:
        uncovered_mask = full_mask ^ covered_mask
        best_word: str | None = None
        best_mask = 0
        best_score = float("-inf")

        for word in top_pool:
            if word in selected_set:
                continue
            if (
                max_short_answers is not None
                and len(word) <= short_answer_len
                and short_count >= max_short_answers
            ):
                continue
            freq = freq_map.get(word, 0.0)
            modes = candidate_word_modes[word]
            for mask in candidate_word_masks[word]:
                coverage_gain = (mask & uncovered_mask).bit_count()
                reuse_gain = sum(
                    token_counts[idx] for idx in range(wheel_size) if mask & (1 << idx)
                )
                token_len = mask.bit_count()
                word_len = len(word)
                band_penalty = 0.0
                if selected_freqs:
                    mean_freq = sum(selected_freqs) / len(selected_freqs)
                    band_penalty += abs(freq - mean_freq) * 28
                    if freq < mean_freq:
                        band_penalty += (mean_freq - freq) * 18
                score = (
                    coverage_gain * 170
                    + reuse_gain * 16
                    + token_len * 6
                    + word_len * answer_length_weight
                    + min(freq, 8.0) * 12
                    - band_penalty
                )
                if word_len >= preferred_answer_len_min:
                    bounded_word_len = min(word_len, preferred_answer_len_max)
                    if bounded_word_len >= preferred_answer_len_min:
                        score += (
                            bounded_word_len - preferred_answer_len_min + 1
                        ) * preferred_answer_len_bonus
                if word_len <= short_answer_len:
                    score -= (short_answer_len - word_len + 1) * short_answer_penalty
                if covered_mask != full_mask and coverage_gain == 0:
                    score -= 120
                if modes == {"forward"} and forward_only_count < required_per_mode:
                    score += 260
                elif modes == {"reverse"} and reverse_only_count < required_per_mode:
                    score += 260

                remaining_slots = max_target - len(selected_words)
                remaining_forward = max(0, required_per_mode - forward_only_count)
                remaining_reverse = max(0, required_per_mode - reverse_only_count)
                if remaining_slots <= remaining_forward + remaining_reverse:
                    if remaining_forward > 0 and modes != {"forward"}:
                        score -= 220
                    if remaining_reverse > 0 and modes != {"reverse"}:
                        score -= 220
                if score > best_score:
                    best_score = score
                    best_word = word
                    best_mask = mask

        if best_word is None:
            break

        selected_words.append(best_word)
        selected_set.add(best_word)
        covered_mask |= best_mask
        selected_freqs.append(freq_map.get(best_word, 0.0))
        if candidate_word_modes[best_word] == {"forward"}:
            forward_only_count += 1
        elif candidate_word_modes[best_word] == {"reverse"}:
            reverse_only_count += 1
        if len(best_word) <= short_answer_len:
            short_count += 1
        for idx in range(wheel_size):
            if best_mask & (1 << idx):
                token_counts[idx] += 1

        requirements_met = (
            covered_mask == full_mask
            and len(selected_words) >= min_answers
            and forward_only_count >= required_per_mode
            and reverse_only_count >= required_per_mode
        )
        if requirements_met:
            if min(token_counts) >= 2 and rng.random() < 0.55:
                break
            if rng.random() < 0.2:
                break

    if (
        covered_mask != full_mask
        or len(selected_words) < min_answers
        or forward_only_count < required_per_mode
        or reverse_only_count < required_per_mode
    ):
        return [], []

    selected_words.sort(key=lambda item: (-len(item), -freq_map.get(item, 0.0), item))
    return selected_words, token_counts


def build_level(
    level_id: int,
    combo_pool: list[str],
    lexicon_set: set[str],
    bonus_lexicon_set: set[str],
    freq_map: dict[str, float],
    bonus_freq_map: dict[str, float],
    combo_sizes: tuple[int, ...],
    args: argparse.Namespace,
    rng: random.Random,
    crossword_level_time_limit: float | None = None,
) -> dict | None:
    layout_mode = str(args.layout_mode)
    seed_word = ""

    # Generate variance parameters for this level
    overlap_score_weight = rng.uniform(
        args.variance_overlap_weight_min,
        args.variance_overlap_weight_max,
    )
    short_answer_penalty = rng.uniform(
        args.variance_short_penalty_min,
        args.variance_short_penalty_max,
    )
    wheel_tokens: list[str] = []
    candidate_word_masks: dict[str, set[int]] = {}
    candidate_word_sequences: dict[str, list[tuple[str, ...]]] = {}
    candidate_word_modes: dict[str, set[str]] = {}
    bonus_candidate_word_masks: dict[str, set[int]] = {}
    bonus_candidate_word_modes: dict[str, set[str]] = {}
    min_candidate_tokens: dict[str, int] = {}
    answer_candidates: dict[str, set[int]] = {}
    answer_candidate_modes: dict[str, set[str]] = {}
    answers: list[str] = []
    answer_token_counts: list[int] = []
    grid_cell_cap = (
        args.rows_max * args.cols_max
        if layout_mode == "crossword-letter"
        else args.size_max * args.size_max
    )
    max_word_len = min(args.max_word_len, max(2, grid_cell_cap * 3))
    layout_stats: dict[str, int | bool] = {
        "connected": True,
        "componentCount": 1,
        "isolatedWordCount": 0,
    }

    for _ in range(80):
        wheel_tokens = choose_wheel_from_pool(
            combo_pool,
            args.wheel_sampling_pool_max,
            args.wheel_size,
            args.min_single_letter_tokens,
            args.max_single_letter_tokens,
            (
                args.min_three_letter_tokens_large_wheel
                if args.wheel_size >= args.min_three_letter_tokens_large_wheel_size
                else 0
            ),
            (
                args.min_three_letter_tokens_large_wheel
                if args.wheel_size >= args.min_three_letter_tokens_large_wheel_size
                else args.wheel_size
            ),
            rng,
        )
        seed_word = "-".join(wheel_tokens)
        forward_masks, forward_sequences = candidate_words_from_wheel(
            wheel_tokens,
            lexicon_set,
            args.min_word_len,
            max_word_len,
            args.max_candidate_words,
            "forward",
        )
        reverse_masks, reverse_sequences = candidate_words_from_wheel(
            wheel_tokens,
            lexicon_set,
            args.min_word_len,
            max_word_len,
            args.max_candidate_words,
            "reverse",
        )
        candidate_word_masks = {}
        candidate_word_sequences = {}
        candidate_word_modes = {}
        for mode, masks_map, sequences_map in (
            ("forward", forward_masks, forward_sequences),
            ("reverse", reverse_masks, reverse_sequences),
        ):
            for word, masks in masks_map.items():
                candidate_word_masks.setdefault(word, set()).update(masks)
                candidate_word_modes.setdefault(word, set()).add(mode)
            for word, sequences in sequences_map.items():
                existing = candidate_word_sequences.setdefault(word, [])
                seen = set(existing)
                for sequence in sequences:
                    if sequence in seen:
                        continue
                    existing.append(sequence)
                    seen.add(sequence)

        if bonus_lexicon_set == lexicon_set:
            bonus_candidate_word_masks = {
                word: set(masks) for word, masks in candidate_word_masks.items()
            }
            bonus_candidate_word_modes = {
                word: set(modes) for word, modes in candidate_word_modes.items()
            }
        else:
            bonus_forward_masks, _ = candidate_words_from_wheel(
                wheel_tokens,
                bonus_lexicon_set,
                args.min_word_len,
                max_word_len,
                args.max_candidate_words,
                "forward",
            )
            bonus_reverse_masks, _ = candidate_words_from_wheel(
                wheel_tokens,
                bonus_lexicon_set,
                args.min_word_len,
                max_word_len,
                args.max_candidate_words,
                "reverse",
            )
            bonus_candidate_word_masks = {}
            bonus_candidate_word_modes = {}
            for mode, masks_map in (
                ("forward", bonus_forward_masks),
                ("reverse", bonus_reverse_masks),
            ):
                for word, masks in masks_map.items():
                    bonus_candidate_word_masks.setdefault(word, set()).update(masks)
                    bonus_candidate_word_modes.setdefault(word, set()).add(mode)
        min_candidate_tokens = {
            word: min_token_count(masks) for word, masks in candidate_word_masks.items()
        }
        effective_min_answer_token_count = args.min_answer_token_count
        if args.wheel_size >= args.min_answer_token_large_wheel_size:
            effective_min_answer_token_count = max(
                effective_min_answer_token_count,
                args.min_answer_token_count_large_wheel,
            )
        answer_candidates = {
            word: masks
            for word, masks in candidate_word_masks.items()
            if min_candidate_tokens[word] >= effective_min_answer_token_count
        }
        answer_candidate_modes = {
            word: candidate_word_modes[word] for word in answer_candidates
        }
        if len(answer_candidates) < args.min_answers:
            continue

        target_min_len = max(args.min_word_len, args.target_min_answer_len)
        relax_min_len = args.min_word_len
        if args.wheel_size >= args.long_word_bias_wheel_size:
            target_min_len = max(target_min_len, args.long_word_target_min_len)
            relax_min_len = max(
                args.min_word_len,
                min(args.long_word_relax_min_len, target_min_len),
            )
        min_len_attempts = list(range(target_min_len, relax_min_len - 1, -1))
        for min_len in min_len_attempts:
            filtered_candidates = {
                word: masks
                for word, masks in answer_candidates.items()
                if len(word) >= min_len
            }
            if len(filtered_candidates) < args.min_answers:
                continue
            filtered_modes = {
                word: answer_candidate_modes[word] for word in filtered_candidates
            }
            short_cap_limit = (
                len(filtered_candidates)
                if args.max_answers <= 0
                else min(args.max_answers, len(filtered_candidates))
            )
            for short_cap in range(
                max(0, args.preferred_max_short_answers), short_cap_limit + 1
            ):
                answers, answer_token_counts = pick_answer_words(
                    filtered_candidates,
                    filtered_modes,
                    freq_map,
                    args.min_answers,
                    args.max_answers,
                    args.wheel_size,
                    args.short_answer_len,
                    short_cap,
                    args.answer_length_weight,
                    args.preferred_answer_len_min,
                    args.preferred_answer_len_max,
                    args.preferred_answer_len_bonus,
                    short_answer_penalty,
                    rng,
                )
                if answers:
                    break
            if answers:
                break
        if answers:
            break
    if len(answer_candidates) < args.min_answers or not answers:
        return None

    if any(count <= 0 for count in answer_token_counts):
        return None

    if layout_mode == "crossword-letter":
        level_time_limit = (
            crossword_level_time_limit
            if crossword_level_time_limit is not None
            else args.crossword_level_time_limit
        )
        if level_time_limit <= 0:
            level_time_limit = 3.0
        placement_deadline = time.monotonic() + level_time_limit
        size_options = [
            (rows, cols)
            for rows in range(args.rows_min, args.rows_max + 1)
            for cols in range(args.cols_min, args.cols_max + 1)
        ]
        longest_answer = max(len(word) for word in answers)
        total_answer_letters = sum(len(word) for word in answers)
        target_grid_cells = max(
            longest_answer * longest_answer,
            math.ceil(total_answer_letters * 1.4),
        )
        size_options.sort(
            key=lambda item: (
                int(max(item) < longest_answer),
                abs((item[0] * item[1]) - target_grid_cells),
                -max(item),
                -(item[0] * item[1]),
                item[0],
                item[1],
            )
        )

        rows = args.rows_min
        cols = args.cols_min
        placed_crossword = None
        allow_disconnected_modes = (
            (False, True) if args.crossword_max_isolated_words > 0 else (False,)
        )
        for allow_disconnected in allow_disconnected_modes:
            for candidate_rows, candidate_cols in size_options:
                if time.monotonic() > placement_deadline:
                    break
                placed_crossword = place_words_crossword_letters(
                    answers,
                    candidate_rows,
                    candidate_cols,
                    wheel_tokens,
                    freq_map,
                    args.crossword_placement_attempts,
                    args.crossword_max_isolated_words,
                    args.crossword_isolated_word_min_freq,
                    allow_disconnected,
                    placement_deadline,
                    rng,
                    overlap_score_weight,
                )
                if placed_crossword is not None:
                    rows = candidate_rows
                    cols = candidate_cols
                    break
            if time.monotonic() > placement_deadline:
                break
            if placed_crossword is not None:
                break
        if placed_crossword is None:
            return None
        cells, h, v, paths, layout_stats = placed_crossword
    else:
        size = rng.randint(args.size_min, args.size_max)
        rows, cols = size, size
        placed_maze = place_words(
            answers, rows, cols, wheel_tokens, args.block_prob, rng
        )
        if placed_maze is None:
            return None
        cells, h, v, paths = placed_maze

    for answer in answers:
        path = paths.get(answer)
        if not path:
            return None
        if layout_mode == "crossword-letter" and not path_is_straight(path):
            return None
        if not path_spells_word(cells, path, answer):
            return None

    if layout_mode == "crossword-letter" and not validate_letter_grid(
        cells,
        paths,
        candidate_word_modes,
    ):
        return None

    answer_objects = [
        {
            "text": word,
            "path": paths[word],
            "freq": round(freq_map.get(word, 0.0), 4),
            "tokenCount": min_candidate_tokens[word],
            "allowedModes": sorted(
                candidate_word_modes.get(word, {"forward"}),
                key=lambda item: (item != "forward", item),
            ),
        }
        for word in answers
    ]
    answer_set = set(answers)
    bonus_min_candidate_tokens = {
        word: min_token_count(masks)
        for word, masks in bonus_candidate_word_masks.items()
    }

    def bonus_word_freq(word: str) -> float:
        return bonus_freq_map.get(word, freq_map.get(word, 0.0))

    candidate_words_by_freq = sorted(
        bonus_candidate_word_masks,
        key=lambda item: (-bonus_word_freq(item), item),
    )
    valid_words = [
        word
        for word in candidate_words_by_freq
        if word not in answer_set
        and bonus_min_candidate_tokens.get(word, 0) >= args.min_bonus_token_count
    ]
    bonus_words_ranked = sorted(
        valid_words,
        key=lambda item: (
            -bonus_min_candidate_tokens.get(item, 0),
            -len(item),
            -bonus_word_freq(item),
            item,
        ),
    )
    bonus_words = sorted(bonus_words_ranked[: args.max_bonus_words])

    combos: set[str] = set()
    for answer in answers:
        combos.update(generate_combos(answer, combo_sizes))

    signature = (
        layout_mode,
        tuple(wheel_tokens),
        tuple(sorted(answers)),
        tuple(tuple(row) for row in cells),
        tuple(tuple(row) for row in h),
        tuple(tuple(row) for row in v),
    )

    return {
        "id": level_id,
        "rows": rows,
        "cols": cols,
        "seed": seed_word,
        "layoutMode": layout_mode,
        "placementStats": layout_stats,
        "_signature": signature,
        "letterWheel": wheel_tokens,
        "combos": sorted(combos),
        "bonusWords": bonus_words,
        "answers": answer_objects,
        "walls": derive_walls_sparse(rows, cols, paths, h, v),
    }


def init_worker_context(
    combo_pool: list[str],
    lexicon_set: set[str],
    bonus_lexicon_set: set[str],
    freq_map: dict[str, float],
    bonus_freq_map: dict[str, float],
    combo_sizes: tuple[int, ...],
    args_dict: dict,
) -> None:
    global WORKER_COMBO_POOL
    global WORKER_LEXICON_SET
    global WORKER_BONUS_LEXICON_SET
    global WORKER_FREQ_MAP
    global WORKER_BONUS_FREQ_MAP
    global WORKER_COMBO_SIZES
    global WORKER_ARGS

    WORKER_COMBO_POOL = combo_pool
    WORKER_LEXICON_SET = lexicon_set
    WORKER_BONUS_LEXICON_SET = bonus_lexicon_set
    WORKER_FREQ_MAP = freq_map
    WORKER_BONUS_FREQ_MAP = bonus_freq_map
    WORKER_COMBO_SIZES = combo_sizes
    WORKER_ARGS = argparse.Namespace(**args_dict)


def build_level_worker(
    level_id: int,
    seed: int,
    crossword_level_time_limit: float,
) -> dict | None:
    if (
        WORKER_COMBO_POOL is None
        or WORKER_LEXICON_SET is None
        or WORKER_BONUS_LEXICON_SET is None
        or WORKER_FREQ_MAP is None
        or WORKER_BONUS_FREQ_MAP is None
        or WORKER_COMBO_SIZES is None
        or WORKER_ARGS is None
    ):
        raise RuntimeError("worker context not initialized")

    rng = random.Random(seed)
    return build_level(
        level_id,
        WORKER_COMBO_POOL,
        WORKER_LEXICON_SET,
        WORKER_BONUS_LEXICON_SET,
        WORKER_FREQ_MAP,
        WORKER_BONUS_FREQ_MAP,
        WORKER_COMBO_SIZES,
        WORKER_ARGS,
        rng,
        crossword_level_time_limit,
    )


def attempt_seed(base_seed: int, attempt_number: int) -> int:
    return (base_seed * 1_000_003 + attempt_number * 97_409) % (2**63)


def wheel_key(candidate: dict) -> str:
    wheel_tokens = [str(token) for token in candidate.get("letterWheel", [])]
    letter_bag = "".join(wheel_tokens)
    if letter_bag:
        return "".join(sorted(letter_bag))
    return "|".join(sorted(wheel_tokens))


def answer_text_set(candidate: dict) -> set[str]:
    return {
        str(answer.get("text", ""))
        for answer in candidate.get("answers", [])
        if isinstance(answer, dict)
    }


def answer_jaccard_similarity(candidate: dict, other: dict) -> float:
    candidate_answers = answer_text_set(candidate)
    other_answers = answer_text_set(other)
    union = candidate_answers.union(other_answers)
    if not union:
        return 0.0
    return len(candidate_answers.intersection(other_answers)) / len(union)


def intersection_count(candidate: dict) -> int:
    visits: dict[tuple[int, int], int] = {}
    for answer in candidate.get("answers", []):
        if not isinstance(answer, dict):
            continue
        for row, col in answer.get("path", []):
            key = (int(row), int(col))
            visits[key] = visits.get(key, 0) + 1
    return sum(1 for count in visits.values() if count >= 2)


def candidate_quality_key(candidate: dict, signature: tuple | None = None) -> tuple:
    stats = candidate.get("placementStats") or {}
    rows = int(candidate.get("rows", 0))
    cols = int(candidate.get("cols", 0))
    grid_cells = int(stats.get("gridCells", rows * cols))
    occupied = int(stats.get("occupiedCellCount", 0))
    fill_ratio = occupied / grid_cells if grid_cells > 0 else 0.0
    avg_answer_freq = 0.0
    answers = candidate.get("answers", [])
    if answers:
        avg_answer_freq = sum(
            float(answer.get("freq", 0.0)) for answer in answers
        ) / len(answers)
    connected = bool(stats.get("connected", True))
    isolated_words = int(stats.get("isolatedWordCount", 0))
    components = int(stats.get("componentCount", 1))
    quality_signature = (
        repr(signature) if signature is not None else str(candidate.get("seed", ""))
    )
    return (
        int(connected),
        round(fill_ratio, 6),
        intersection_count(candidate),
        -isolated_words,
        -components,
        -grid_cells,
        round(avg_answer_freq, 4),
        quality_signature,
    )


def log_generation_progress(
    level_count: int,
    attempts: int,
    requested_count: int,
    max_attempts: int,
    started_at: float,
    duplicate_stats: dict[str, int],
    overall_start_epoch: float | None = None,
    overall_work_completed_before: float = 0.0,
    overall_work_total: float = 0.0,
    is_final: bool = False,
) -> None:
    elapsed = max(0.001, time.monotonic() - started_at)
    hit_rate = level_count / attempts
    levels_per_sec = level_count / elapsed
    attempts_per_sec = attempts / elapsed
    remaining_levels = max(0, requested_count - level_count)
    remaining_attempts = max(0, max_attempts - attempts)

    eta_to_goal = (
        (remaining_levels / levels_per_sec) if levels_per_sec > 0 else float("inf")
    )
    eta_to_attempt_limit = (
        (remaining_attempts / attempts_per_sec)
        if attempts_per_sec > 0
        else float("inf")
    )
    eta_total = min(eta_to_goal, eta_to_attempt_limit)
    duplicate_total = sum(duplicate_stats.values())
    duplicate_rate = duplicate_total / attempts if attempts > 0 else 0.0

    overall_progress_text = ""
    if (
        overall_start_epoch is not None
        and overall_start_epoch > 0
        and overall_work_total > 0
    ):
        overall_done = max(0.0, overall_work_completed_before + level_count)
        percent_complete = min(100.0, (overall_done / overall_work_total) * 100.0)
        overall_progress_text = f" overallProgress={percent_complete:.1f}"

    print(
        "progress: "
        f"attempts={attempts}/{max_attempts} "
        f"levels={level_count}/{requested_count} "
        f"hitRate={hit_rate:.3f} "
        f"dups={duplicate_total} ({duplicate_rate:.3f}) "
        f"exact={duplicate_stats['exact']} "
        f"near={duplicate_stats['nearRejected']} "
        f"overlap={duplicate_stats['overlapRejected']} "
        f"swap={duplicate_stats['nearReplaced']} "
        f"levelsPerSec={levels_per_sec:.2f} "
        f"elapsed={elapsed:.1f}s "
        f"eta={format_eta(eta_total)}"
        f"{overall_progress_text}"
        f" status={'done' if is_final else 'running'}"
    )


def main() -> None:
    args = parse_args()
    combo_sizes = parse_combo_sizes(args.combo_sizes)
    wheel_token_sizes = parse_combo_sizes(args.wheel_token_sizes)
    worker_count = resolve_worker_count(args.workers)

    if args.min_answer_token_count <= 0:
        raise SystemExit("--min-answer-token-count must be >= 1")
    if args.max_answers < 0:
        raise SystemExit("--max-answers must be >= 0")
    if args.max_answers > 0 and args.max_answers < args.min_answers:
        raise SystemExit("--max-answers must be >= --min-answers when capped")
    if args.min_bonus_token_count <= 0:
        raise SystemExit("--min-bonus-token-count must be >= 1")
    if args.min_single_letter_tokens < 0:
        raise SystemExit("--min-single-letter-tokens must be >= 0")
    if args.max_single_letter_tokens < 0:
        raise SystemExit("--max-single-letter-tokens must be >= 0")
    if args.min_three_letter_tokens_large_wheel_size <= 0:
        raise SystemExit("--min-three-letter-tokens-large-wheel-size must be >= 1")
    if args.min_three_letter_tokens_large_wheel < 0:
        raise SystemExit("--min-three-letter-tokens-large-wheel must be >= 0")
    if args.min_single_letter_tokens > args.max_single_letter_tokens:
        raise SystemExit(
            "--min-single-letter-tokens must be <= --max-single-letter-tokens"
        )
    if args.min_single_letter_tokens > args.wheel_size:
        raise SystemExit("--min-single-letter-tokens must be <= --wheel-size")
    if args.min_single_letter_tokens > 0 and 1 not in wheel_token_sizes:
        raise SystemExit("--min-single-letter-tokens requires 1 in --wheel-token-sizes")
    if (
        args.wheel_size >= args.min_three_letter_tokens_large_wheel_size
        and args.min_three_letter_tokens_large_wheel > args.wheel_size
    ):
        raise SystemExit(
            "--min-three-letter-tokens-large-wheel must be <= --wheel-size"
        )
    if (
        args.wheel_size >= args.min_three_letter_tokens_large_wheel_size
        and args.min_three_letter_tokens_large_wheel > 0
        and 3 not in wheel_token_sizes
    ):
        wheel_token_sizes = tuple(sorted({*wheel_token_sizes, 3}))
    if args.target_min_answer_len <= 0:
        raise SystemExit("--target-min-answer-len must be >= 1")
    if args.combo_pool_max_words <= 0:
        raise SystemExit("--combo-pool-max-words must be >= 1")
    if args.wheel_sampling_pool_max <= 0:
        raise SystemExit("--wheel-sampling-pool-max must be >= 1")
    if args.short_answer_len <= 0:
        raise SystemExit("--short-answer-len must be >= 1")
    if args.preferred_max_short_answers < 0:
        raise SystemExit("--preferred-max-short-answers must be >= 0")
    if args.answer_length_weight < 0:
        raise SystemExit("--answer-length-weight must be >= 0")
    if args.preferred_answer_len_min <= 0:
        raise SystemExit("--preferred-answer-len-min must be >= 1")
    if args.preferred_answer_len_max < args.preferred_answer_len_min:
        raise SystemExit(
            "--preferred-answer-len-max must be >= --preferred-answer-len-min"
        )
    if args.preferred_answer_len_bonus < 0:
        raise SystemExit("--preferred-answer-len-bonus must be >= 0")
    if args.short_answer_penalty < 0:
        raise SystemExit("--short-answer-penalty must be >= 0")
    if args.long_word_bias_wheel_size <= 0:
        raise SystemExit("--long-word-bias-wheel-size must be >= 1")
    if args.long_word_target_min_len <= 0:
        raise SystemExit("--long-word-target-min-len must be >= 1")
    if args.long_word_relax_min_len <= 0:
        raise SystemExit("--long-word-relax-min-len must be >= 1")
    if args.long_word_target_min_len < args.long_word_relax_min_len:
        raise SystemExit(
            "--long-word-target-min-len must be >= --long-word-relax-min-len"
        )
    if args.min_answer_token_large_wheel_size <= 0:
        raise SystemExit("--min-answer-token-large-wheel-size must be >= 1")
    if args.min_answer_token_count_large_wheel <= 0:
        raise SystemExit("--min-answer-token-count-large-wheel must be >= 1")
    if not 0.0 <= args.near_duplicate_answer_jaccard <= 1.0:
        raise SystemExit("--near-duplicate-answer-jaccard must be between 0 and 1")
    if args.near_duplicate_window < 0:
        raise SystemExit("--near-duplicate-window must be >= 0")
    if args.progress_every_seconds < 0:
        raise SystemExit("--progress-every-seconds must be >= 0")
    if args.overall_start_epoch < 0:
        raise SystemExit("--overall-start-epoch must be >= 0")
    if args.overall_work_completed_before < 0:
        raise SystemExit("--overall-work-completed-before must be >= 0")
    if args.overall_work_total < 0:
        raise SystemExit("--overall-work-total must be >= 0")
    if args.overall_work_total > 0 and args.overall_start_epoch <= 0:
        raise SystemExit(
            "--overall-start-epoch must be > 0 when --overall-work-total is set"
        )
    if args.overall_work_total > 0 and (
        args.overall_work_completed_before > args.overall_work_total
    ):
        raise SystemExit(
            "--overall-work-completed-before must be <= --overall-work-total"
        )
    if args.layout_mode == "maze-path" and args.size_min > args.size_max:
        raise SystemExit("--size-min must be <= --size-max")
    if args.layout_mode == "crossword-letter":
        if args.rows_min > args.rows_max:
            raise SystemExit("--rows-min must be <= --rows-max")
        if args.cols_min > args.cols_max:
            raise SystemExit("--cols-min must be <= --cols-max")
        if min(args.rows_min, args.cols_min) <= 1:
            raise SystemExit("crossword-letter requires at least 2 rows/cols")
        if args.crossword_max_isolated_words < 0:
            raise SystemExit("--crossword-max-isolated-words must be >= 0")
        if args.crossword_isolated_word_min_freq < 0:
            raise SystemExit("--crossword-isolated-word-min-freq must be >= 0")
        if args.crossword_level_time_limit < 0:
            raise SystemExit("--crossword-level-time-limit must be >= 0")

    lexicon_path = resolve_path(args.lexicon)
    bonus_lexicon_path = (
        resolve_path(args.bonus_lexicon) if args.bonus_lexicon.strip() else lexicon_path
    )
    out_path = resolve_path(args.out)
    lexicon_payload = load_json(lexicon_path)
    lexicon_words: list[dict] = lexicon_payload.get("words", [])
    if bonus_lexicon_path == lexicon_path:
        bonus_lexicon_words = lexicon_words
    else:
        bonus_lexicon_payload = load_json(bonus_lexicon_path)
        bonus_lexicon_words: list[dict] = bonus_lexicon_payload.get("words", [])

    grid_cell_cap = (
        args.rows_max * args.cols_max
        if args.layout_mode == "crossword-letter"
        else args.size_max * args.size_max
    )
    max_word_len = min(args.max_word_len, max(2, grid_cell_cap * 3))
    combo_pool = build_combo_pool(
        lexicon_words,
        wheel_token_sizes,
        args.combo_pool_max_words,
    )
    lexicon_set = {
        entry["word"]
        for entry in lexicon_words
        if args.min_word_len <= len(entry["word"]) <= max_word_len
    }
    bonus_lexicon_set = {
        entry["word"]
        for entry in bonus_lexicon_words
        if args.min_word_len <= len(entry["word"]) <= max_word_len
    }
    freq_map = {entry["word"]: float(entry.get("freq", 0.0)) for entry in lexicon_words}
    bonus_freq_map = {
        entry["word"]: float(entry.get("freq", 0.0)) for entry in bonus_lexicon_words
    }

    levels: list[dict] = []
    seen_signatures: set[tuple] = set()
    wheel_to_level_indices: dict[str, list[int]] = {}
    duplicate_stats = {
        "exact": 0,
        "nearRejected": 0,
        "overlapRejected": 0,
        "nearReplaced": 0,
    }
    completed_attempts = 0
    started_at = time.monotonic()
    overall_start_epoch = (
        args.overall_start_epoch
        if args.overall_start_epoch > 0 and args.overall_work_total > 0
        else None
    )
    next_progress_at = (
        started_at + args.progress_every_seconds
        if args.progress_every_seconds > 0
        else float("inf")
    )

    def record_candidate(candidate: dict | None) -> None:
        if candidate is None or len(levels) >= args.count:
            return

        signature = candidate.pop("_signature")
        if signature in seen_signatures:
            duplicate_stats["exact"] += 1
            return

        candidate_wheel_key = wheel_key(candidate)
        candidate_quality = candidate_quality_key(candidate, signature)
        existing_indices = wheel_to_level_indices.get(candidate_wheel_key, [])
        if existing_indices:
            near_duplicate_index = existing_indices[0]
            near_duplicate_quality = candidate_quality_key(levels[near_duplicate_index])
            for index in existing_indices[1:]:
                existing_quality = candidate_quality_key(levels[index])
                if existing_quality > near_duplicate_quality:
                    near_duplicate_index = index
                    near_duplicate_quality = existing_quality

            if candidate_quality > near_duplicate_quality:
                duplicate_stats["nearReplaced"] += 1
                candidate["id"] = levels[near_duplicate_index]["id"]
                levels[near_duplicate_index] = candidate
                seen_signatures.add(signature)
            else:
                duplicate_stats["nearRejected"] += 1
                seen_signatures.add(signature)
            return

        if args.near_duplicate_window > 0 and args.near_duplicate_answer_jaccard > 0:
            recent_start = max(0, len(levels) - args.near_duplicate_window)
            for existing in levels[recent_start:]:
                similarity = answer_jaccard_similarity(candidate, existing)
                if similarity >= args.near_duplicate_answer_jaccard:
                    duplicate_stats["overlapRejected"] += 1
                    seen_signatures.add(signature)
                    return

        seen_signatures.add(signature)
        candidate["id"] = len(levels) + 1
        levels.append(candidate)
        wheel_to_level_indices.setdefault(candidate_wheel_key, []).append(
            len(levels) - 1
        )

    if worker_count == 1:
        for attempt_number in range(1, args.max_attempts + 1):
            if len(levels) >= args.count:
                break

            candidate = build_level(
                len(levels) + 1,
                combo_pool,
                lexicon_set,
                bonus_lexicon_set,
                freq_map,
                bonus_freq_map,
                combo_sizes,
                args,
                random.Random(attempt_seed(args.seed, attempt_number)),
                args.crossword_level_time_limit
                if args.crossword_level_time_limit > 0
                else dynamic_crossword_time_limit(completed_attempts, started_at),
            )
            completed_attempts = attempt_number
            record_candidate(candidate)

            now = time.monotonic()
            if now >= next_progress_at:
                log_generation_progress(
                    len(levels),
                    completed_attempts,
                    args.count,
                    args.max_attempts,
                    started_at,
                    duplicate_stats,
                    overall_start_epoch,
                    args.overall_work_completed_before,
                    args.overall_work_total,
                )
                next_progress_at = now + args.progress_every_seconds
    else:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=init_worker_context,
            initargs=(
                combo_pool,
                lexicon_set,
                bonus_lexicon_set,
                freq_map,
                bonus_freq_map,
                combo_sizes,
                vars(args),
            ),
        )
        in_flight: dict = {}
        submitted_attempts = 0
        max_in_flight = max(worker_count, worker_count * 2)

        try:
            while True:
                while (
                    len(levels) + len(in_flight) < args.count
                    and submitted_attempts < args.max_attempts
                    and len(in_flight) < max_in_flight
                ):
                    submitted_attempts += 1
                    crossword_time_limit = (
                        args.crossword_level_time_limit
                        if args.crossword_level_time_limit > 0
                        else dynamic_crossword_time_limit(
                            completed_attempts,
                            started_at,
                        )
                    )
                    future = executor.submit(
                        build_level_worker,
                        len(levels) + len(in_flight) + 1,
                        attempt_seed(args.seed, submitted_attempts),
                        crossword_time_limit,
                    )
                    in_flight[future] = submitted_attempts

                if not in_flight:
                    break

                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    in_flight.pop(future)
                    completed_attempts += 1
                    record_candidate(future.result())

                    now = time.monotonic()
                    if now >= next_progress_at:
                        log_generation_progress(
                            len(levels),
                            completed_attempts,
                            args.count,
                            args.max_attempts,
                            started_at,
                            duplicate_stats,
                            overall_start_epoch,
                            args.overall_work_completed_before,
                            args.overall_work_total,
                        )
                        next_progress_at = now + args.progress_every_seconds

                if len(levels) >= args.count or completed_attempts >= args.max_attempts:
                    break
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    if args.progress_every_seconds > 0:
        log_generation_progress(
            len(levels),
            completed_attempts,
            args.count,
            args.max_attempts,
            started_at,
            duplicate_stats,
            overall_start_epoch,
            args.overall_work_completed_before,
            args.overall_work_total,
            is_final=True,
        )

    payload = {
        "meta": {
            "seed": args.seed,
            "layoutMode": args.layout_mode,
            "requestedCount": args.count,
            "generatedCount": len(levels),
            "attempts": completed_attempts,
            "workers": worker_count,
            "sizeRange": [args.size_min, args.size_max],
            "rowsRange": [args.rows_min, args.rows_max],
            "colsRange": [args.cols_min, args.cols_max],
            "wheelSize": args.wheel_size,
            "wheelTokenSizes": list(wheel_token_sizes),
            "minSingleLetterTokens": args.min_single_letter_tokens,
            "maxSingleLetterTokens": args.max_single_letter_tokens,
            "minThreeLetterTokensLargeWheelSize": args.min_three_letter_tokens_large_wheel_size,
            "minThreeLetterTokensLargeWheel": args.min_three_letter_tokens_large_wheel,
            "comboSizes": list(combo_sizes),
            "minAnswers": args.min_answers,
            "maxAnswers": args.max_answers,
            "minAnswerTokenCount": args.min_answer_token_count,
            "minAnswerTokenLargeWheelSize": args.min_answer_token_large_wheel_size,
            "minAnswerTokenCountLargeWheel": args.min_answer_token_count_large_wheel,
            "minBonusTokenCount": args.min_bonus_token_count,
            "preferredAnswerLenMin": args.preferred_answer_len_min,
            "preferredAnswerLenMax": args.preferred_answer_len_max,
            "preferredAnswerLenBonus": args.preferred_answer_len_bonus,
            "shortAnswerPenalty": args.short_answer_penalty,
            "longWordBiasWheelSize": args.long_word_bias_wheel_size,
            "longWordTargetMinLen": args.long_word_target_min_len,
            "longWordRelaxMinLen": args.long_word_relax_min_len,
            "crosswordPlacementAttempts": args.crossword_placement_attempts,
            "crosswordMaxIsolatedWords": args.crossword_max_isolated_words,
            "crosswordIsolatedWordMinFreq": args.crossword_isolated_word_min_freq,
            "crosswordLevelTimeLimit": args.crossword_level_time_limit,
            "crosswordLevelTimeLimitDynamic": args.crossword_level_time_limit <= 0,
            "requireAllWheelTokensInAnswers": True,
            "preferTokenReuse": True,
            "nearDuplicateAnswerJaccard": args.near_duplicate_answer_jaccard,
            "nearDuplicateWindow": args.near_duplicate_window,
            "duplicateStats": {
                "exact": duplicate_stats["exact"],
                "nearRejected": duplicate_stats["nearRejected"],
                "overlapRejected": duplicate_stats["overlapRejected"],
                "nearReplaced": duplicate_stats["nearReplaced"],
            },
        },
        "levels": levels,
    }

    save_json(out_path, payload)
    print(
        f"Generated {len(levels)} levels (attempts: {completed_attempts}, workers: {worker_count}, duplicates: {sum(duplicate_stats.values())}) -> {out_path}"
    )


if __name__ == "__main__":
    main()

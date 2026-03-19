from __future__ import annotations

import argparse
import csv
import io
from collections import Counter
from contextlib import redirect_stdout
from itertools import combinations
from pathlib import Path
from statistics import median

from common import load_json, project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print concise answer-word analysis for a levels bundle."
    )
    parser.add_argument(
        "--bundle",
        default=str(project_path("data", "generated", "levels.bundle.json")),
        help="Path to exported levels bundle JSON.",
    )
    parser.add_argument(
        "--early-group-count",
        type=int,
        default=4,
        help="How many leading groups to treat as the early segment.",
    )
    parser.add_argument(
        "--top-repeats",
        type=int,
        default=10,
        help="How many top repeated words to show per segment.",
    )
    parser.add_argument(
        "--watch-words",
        default="STOP,TOPS,TOP,POT,POST,SPOT,POTS,OPTS,TONE,NOTE",
        help="Comma-separated answer words to print exact level positions for.",
    )
    parser.add_argument(
        "--report-out",
        default=str(project_path("data", "generated", "levels_bundle_analysis.txt")),
        help="Path to write a copy of the console analysis report.",
    )
    parser.add_argument(
        "--repeated-words-csv-out",
        "--repeated-words-early-csv-out",
        dest="repeated_words_early_csv_out",
        default=str(project_path("data", "generated", "repeated_words_early.csv")),
        help="Path to write repeated answer words CSV for the early segment.",
    )
    parser.add_argument(
        "--repeated-tokens-csv-out",
        "--repeated-tokens-early-csv-out",
        dest="repeated_tokens_early_csv_out",
        default=str(project_path("data", "generated", "repeated_tokens_early.csv")),
        help="Path to write repeated wheel tokens CSV for the early segment.",
    )
    parser.add_argument(
        "--repeated-words-all-csv-out",
        default=str(project_path("data", "generated", "repeated_words_all.csv")),
        help="Path to write repeated answer words CSV for the full bundle.",
    )
    parser.add_argument(
        "--repeated-tokens-all-csv-out",
        default=str(project_path("data", "generated", "repeated_tokens_all.csv")),
        help="Path to write repeated wheel tokens CSV for the full bundle.",
    )
    parser.add_argument(
        "--solution-words-csv-out",
        default=str(project_path("data", "generated", "solution_words_all.csv")),
        help=(
            "Path to write per-level solution words CSV rows as "
            "levelCode,word1,word2,..."
        ),
    )
    parser.add_argument(
        "--solution-words-review-csv-out",
        default=str(
            project_path("data", "generated", "solution_words_flagged_review.csv")
        ),
        help="Path to write heuristic review CSV for likely noisy solution words.",
    )
    parser.add_argument(
        "--solution-words-review-min-score",
        type=int,
        default=5,
        help="Minimum heuristic score required to include a word in review CSV.",
    )
    parser.add_argument(
        "--lexicon",
        default=str(project_path("data", "processed", "lexicon.json")),
        help="Lexicon JSON used for word-frequency and morphology heuristics.",
    )
    parser.add_argument(
        "--solution-words-unique-all-out",
        default=str(project_path("data", "generated", "solution_words_unique_all.txt")),
        help="Path to write sorted unique solution words for full bundle.",
    )
    parser.add_argument(
        "--solution-words-unique-early-out",
        default=str(
            project_path("data", "generated", "solution_words_unique_early.txt")
        ),
        help="Path to write sorted unique solution words for early packs.",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def parse_answer_lengths(level: dict) -> list[int]:
    lengths: list[int] = []
    for answer in level.get("answers", []):
        if not isinstance(answer, dict):
            continue
        text = str(answer.get("text", "")).strip()
        if text:
            lengths.append(len(text))
    return lengths


def infer_wheel_shape(level: dict) -> str:
    explicit = str(level.get("wheelShape", "")).strip()
    if explicit:
        return explicit

    wheel_tokens = [str(token) for token in level.get("letterWheel", [])]
    singles = sum(1 for token in wheel_tokens if len(token) == 1)
    doubles = sum(1 for token in wheel_tokens if len(token) == 2)
    triples = sum(1 for token in wheel_tokens if len(token) == 3)
    return f"{singles}/{doubles}/{triples}"


def format_shape_distribution(
    shape_counts: Counter[str], total: int, limit: int = 0
) -> str:
    if total <= 0 or not shape_counts:
        return "n/a"

    rows = sorted(shape_counts.items(), key=lambda item: (-item[1], item[0]))
    # If limit is 0 or negative, show all shapes
    max_items = len(rows) if limit <= 0 else max(1, limit)
    compact = ", ".join(
        f"{shape}:{(count / total) * 100.0:.0f}%" for shape, count in rows[:max_items]
    )
    return compact


def wheel_token_stats(level: dict) -> tuple[int, int]:
    wheel_tokens = [str(token) for token in level.get("letterWheel", [])]
    total_tokens = len(wheel_tokens)
    swap_sensitive_tokens = sum(1 for token in wheel_tokens if len(token) >= 2)
    return total_tokens, swap_sensitive_tokens


def parse_watch_words(raw: str) -> list[str]:
    words: list[str] = []
    for part in raw.split(","):
        token = part.strip().lower()
        if token:
            words.append(token)
    return words


def level_code(
    level_id: str,
    level_to_group_id: dict[str, str],
    level_to_group_pos: dict[str, int],
) -> str:
    group_id = level_to_group_id.get(level_id, "?")
    position = level_to_group_pos.get(level_id)
    if position is not None:
        return f"{group_id}{position}"
    return f"{group_id}#{level_id}"


def level_code_sort_key(code: str) -> tuple[str, int, str]:
    group = ""
    index = 0
    while index < len(code) and code[index].isalpha():
        group += code[index]
        index += 1
    suffix = code[index:]
    if suffix.isdigit():
        return group, int(suffix), code
    return group, 1_000_000_000, code


def repeated_rows_for_segment(
    level_ids: list[str],
    item_lists_by_level: dict[str, list[str]],
    level_to_group_id: dict[str, str],
    level_to_group_pos: dict[str, int],
) -> list[tuple[str, int, list[str]]]:
    item_counts: Counter[str] = Counter()
    item_level_codes: dict[str, set[str]] = {}
    for level_id in level_ids:
        items = item_lists_by_level.get(level_id, [])
        if not items:
            continue
        code = level_code(level_id, level_to_group_id, level_to_group_pos)
        for item in items:
            item_counts[item] += 1
            item_level_codes.setdefault(item, set()).add(code)

    rows = [
        (
            item,
            count,
            sorted(item_level_codes.get(item, set()), key=level_code_sort_key),
        )
        for item, count in item_counts.items()
        if count > 1
    ]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows


def write_repeated_csv(
    out_path: Path,
    item_column_name: str,
    rows: list[tuple[str, int, list[str]]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([item_column_name, "occurrences", "levels"])
        for item, count, level_codes in rows:
            writer.writerow([item, count, ",".join(level_codes)])


def solution_word_rows(
    group_order: list[dict],
    answer_words_by_level: dict[str, list[str]],
    level_to_group_id: dict[str, str],
    level_to_group_pos: dict[str, int],
) -> list[list[str]]:
    rows: list[list[str]] = []
    seen_level_ids: set[str] = set()

    for group in group_order:
        for raw_level_id in group.get("levelIds", []):
            if not isinstance(raw_level_id, str):
                continue
            level_id = raw_level_id
            if level_id in seen_level_ids or level_id not in answer_words_by_level:
                continue
            seen_level_ids.add(level_id)
            level_words = answer_words_by_level.get(level_id, [])
            rows.append(
                [
                    level_code(level_id, level_to_group_id, level_to_group_pos),
                    *level_words,
                ]
            )

    for level_id in sorted(answer_words_by_level):
        if level_id in seen_level_ids:
            continue
        rows.append(
            [
                level_code(level_id, level_to_group_id, level_to_group_pos),
                *answer_words_by_level.get(level_id, []),
            ]
        )

    return rows


def write_solution_words_csv(out_path: Path, rows: list[list[str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(row)


def load_lexicon_word_data(path: Path) -> tuple[dict[str, float], set[str]]:
    if not path.exists() or not path.is_file():
        return {}, set()
    payload = load_json(path)
    entries = payload.get("words", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return {}, set()

    freq_map: dict[str, float] = {}
    lexicon_words: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get("word", "")).strip().lower()
        if not word:
            continue
        raw_freq = entry.get("freq")
        freq = float(raw_freq) if isinstance(raw_freq, (int, float)) else 0.0
        freq_map[word] = freq
        lexicon_words.add(word)
    return freq_map, lexicon_words


def adjacent_repeat_count(word: str) -> int:
    repeats = 0
    for index in range(1, len(word)):
        if word[index] == word[index - 1]:
            repeats += 1
    return repeats


def count_vowels(word: str) -> int:
    return sum(1 for ch in word if ch in "aeiouy")


def has_morph_neighbor(word: str, lexicon_words: set[str]) -> bool:
    if not lexicon_words or len(word) <= 2:
        return False
    candidates = {
        f"{word}s",
        f"{word}ed",
        f"{word}er",
        f"{word}ing",
        f"{word}y",
    }
    if len(word) >= 4:
        candidates.add(word[:-1])
    if len(word) >= 5:
        candidates.add(word[:-2])
    return any(candidate in lexicon_words for candidate in candidates if candidate)


def review_word_signals(
    word: str,
    *,
    freq_map: dict[str, float],
    lexicon_words: set[str],
) -> tuple[int, list[str], float]:
    score = 0
    reasons: list[str] = []
    length = len(word)
    freq = freq_map.get(word, 0.0)
    vowel_count = count_vowels(word)

    if length <= 3:
        score += 2
        reasons.append("short_len")
    if length <= 4 and freq > 0 and freq < 3.4:
        score += 2
        reasons.append("low_freq_short")
    if length >= 5 and freq > 0 and freq < 2.6:
        score += 1
        reasons.append("low_freq")
    if length <= 4 and vowel_count == 0:
        score += 2
        reasons.append("no_vowels")
    if length <= 4 and all(ch in "aeiou" for ch in word):
        score += 2
        reasons.append("all_vowels")
    if length <= 4 and adjacent_repeat_count(word) > 0:
        score += 1
        reasons.append("double_letter_short")
    if length <= 4 and sum(1 for ch in word if ch in "jqxzwvky") >= 2:
        score += 1
        reasons.append("dense_rare_letters")
    if length <= 5 and not has_morph_neighbor(word, lexicon_words):
        score += 1
        reasons.append("no_morph_neighbor")

    return score, reasons, freq


def review_severity(score: int) -> str:
    if score >= 7:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def solution_word_review_rows(
    solution_rows: list[list[str]],
    *,
    freq_map: dict[str, float],
    lexicon_words: set[str],
    min_score: int,
) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in solution_rows:
        if not row:
            continue
        level = row[0]
        for word in row[1:]:
            score, reasons, freq = review_word_signals(
                word,
                freq_map=freq_map,
                lexicon_words=lexicon_words,
            )
            if score < min_score:
                continue
            rows.append(
                [
                    level,
                    word,
                    f"{freq:.3f}",
                    str(score),
                    review_severity(score),
                    "|".join(reasons),
                ]
            )

    rows.sort(key=lambda item: (-int(item[3]), item[1], item[0]))
    return rows


def write_solution_word_review_csv(out_path: Path, rows: list[list[str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["level", "word", "freq", "score", "severity", "reasons"])
        writer.writerows(rows)


def unique_words_for_levels(
    level_ids: list[str], answer_words_by_level: dict[str, list[str]]
) -> list[str]:
    words: set[str] = set()
    for level_id in level_ids:
        for word in answer_words_by_level.get(level_id, []):
            if word:
                words.add(word)
    return sorted(words)


def write_unique_words_txt(out_path: Path, words: list[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(words)
    if words:
        text += "\n"
    out_path.write_text(text, encoding="utf-8")


def level_frequency_stats(level: dict) -> tuple[float, float, float]:
    min_freq = float(level.get("minAnswerFreq", 0.0))
    avg_freq = float(level.get("avgAnswerFreq", 0.0))
    p25_freq = float(level.get("p25AnswerFreq", 0.0))
    if min_freq > 0 or avg_freq > 0 or p25_freq > 0:
        return min_freq, avg_freq, p25_freq

    freqs = sorted(
        float(item.get("freq", 0.0))
        for item in level.get("answers", [])
        if isinstance(item, dict)
    )
    if not freqs:
        return 0.0, 0.0, 0.0
    p25_index = max(0, min(len(freqs) - 1, int((len(freqs) - 1) * 0.25)))
    return freqs[0], (sum(freqs) / len(freqs)), freqs[p25_index]


def summarize_gaps(
    level_ids_by_word: dict[str, list[str]],
) -> tuple[int, dict[int, int]]:
    gaps: list[int] = []
    for ids in level_ids_by_word.values():
        ordered_ids = sorted(ids, key=level_code_sort_key)
        for idx in range(1, len(ordered_ids)):
            prev_code = level_code_sort_key(ordered_ids[idx - 1])
            curr_code = level_code_sort_key(ordered_ids[idx])
            gap = curr_code[1] - prev_code[1]
            gaps.append(gap)

    thresholds = (12, 16, 20)
    below = {threshold: 0 for threshold in thresholds}
    for gap in gaps:
        for threshold in thresholds:
            if gap < threshold:
                below[threshold] += 1

    return len(gaps), below


def pearson(values_x: list[float], values_y: list[float]) -> float:
    if len(values_x) != len(values_y) or len(values_x) < 2:
        return 0.0
    mean_x = sum(values_x) / len(values_x)
    mean_y = sum(values_y) / len(values_y)
    numerator = sum(
        (value_x - mean_x) * (value_y - mean_y)
        for value_x, value_y in zip(values_x, values_y)
    )
    denom_x = sum((value_x - mean_x) ** 2 for value_x in values_x) ** 0.5
    denom_y = sum((value_y - mean_y) ** 2 for value_y in values_y) ** 0.5
    if denom_x <= 0 or denom_y <= 0:
        return 0.0
    return numerator / (denom_x * denom_y)


def rank_values(values: list[float]) -> list[float]:
    indexed = sorted((value, idx) for idx, value in enumerate(values))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start
        while end + 1 < len(indexed) and indexed[end + 1][0] == indexed[start][0]:
            end += 1
        rank = (start + end + 2) / 2.0
        for pos in range(start, end + 1):
            ranks[indexed[pos][1]] = rank
        start = end + 1
    return ranks


def spearman(values_x: list[float], values_y: list[float]) -> float:
    if len(values_x) != len(values_y) or len(values_x) < 2:
        return 0.0
    return pearson(rank_values(values_x), rank_values(values_y))


def print_segment_summary(
    label: str,
    segment_group_ids: list[str],
    answer_words_by_level: dict[str, list[str]],
    level_to_group_id: dict[str, str],
    level_by_id: dict[str, dict],
    top_repeats: int,
) -> None:
    segment_level_ids = [
        level_id
        for level_id in sorted(answer_words_by_level, key=level_code_sort_key)
        if level_to_group_id.get(level_id) in segment_group_ids
    ]
    level_words = {
        level_id: answer_words_by_level[level_id] for level_id in segment_level_ids
    }
    segment_wheel_token_slots = 0
    segment_swap_sensitive_token_slots = 0
    for level_id in segment_level_ids:
        level = level_by_id.get(level_id)
        if level is None:
            continue
        level_token_slots, level_swap_sensitive_slots = wheel_token_stats(level)
        segment_wheel_token_slots += level_token_slots
        segment_swap_sensitive_token_slots += level_swap_sensitive_slots

    word_counter: Counter[str] = Counter()
    word_groups: dict[str, set[str]] = {}
    word_level_ids: dict[str, list[str]] = {}
    for level_id, words in level_words.items():
        group_id = level_to_group_id[level_id]
        for word in words:
            word_counter[word] += 1
            word_groups.setdefault(word, set()).add(group_id)
            word_level_ids.setdefault(word, []).append(level_id)

    total_slots = sum(word_counter.values())
    unique_words = len(word_counter)
    repeated_unique = sum(1 for count in word_counter.values() if count > 1)
    repeated_slots = sum(count for count in word_counter.values() if count > 1)
    dup2 = sum(1 for groups in word_groups.values() if len(groups) >= 2)
    dup3 = sum(1 for groups in word_groups.values() if len(groups) >= 3)
    dup4 = sum(1 for groups in word_groups.values() if len(groups) >= 4)

    pair_intersections: list[tuple[int, str, str]] = []
    group_word_sets: dict[str, set[str]] = {
        group_id: set() for group_id in segment_group_ids
    }
    for word, groups in word_groups.items():
        for group_id in groups:
            if group_id in group_word_sets:
                group_word_sets[group_id].add(word)

    for left, right in combinations(segment_group_ids, 2):
        overlap = len(group_word_sets[left].intersection(group_word_sets[right]))
        pair_intersections.append((overlap, left, right))

    pair_intersections.sort(reverse=True)
    pair_overlaps = [value for value, _, _ in pair_intersections]

    repeat_pairs, repeat_gap_below = summarize_gaps(word_level_ids)

    top_rows = sorted(
        (
            (len(word_groups[word]), word_counter[word], word)
            for word in word_counter
            if len(word_groups[word]) >= 2
        ),
        reverse=True,
    )

    print(
        f"\n[{label}] groups={','.join(segment_group_ids)} levels={len(segment_level_ids)}"
    )
    print(
        "  "
        + " ".join(
            [
                f"answerSlots={total_slots}",
                f"uniqueWords={unique_words}",
                f"repeatedSlots={repeated_slots}/{total_slots}"
                f" ({(repeated_slots / total_slots) if total_slots else 0.0:.3f})",
                f"repeatedUnique={repeated_unique}/{unique_words}"
                f" ({(repeated_unique / unique_words) if unique_words else 0.0:.3f})",
            ]
        )
    )
    if segment_wheel_token_slots > 0:
        print(
            "  "
            + " ".join(
                [
                    "swapSensitiveTokens="
                    f"{segment_swap_sensitive_token_slots}/{segment_wheel_token_slots}",
                    f"({segment_swap_sensitive_token_slots / segment_wheel_token_slots:.3f})",
                ]
            )
        )
    print(f"  crossGroupDup words>=2:{dup2} words>=3:{dup3} words>=4:{dup4}")

    if pair_intersections:
        avg_overlap = sum(pair_overlaps) / len(pair_overlaps)
        top_pairs = ", ".join(
            f"{left}-{right}:{overlap}"
            for overlap, left, right in pair_intersections[
                : min(3, len(pair_intersections))
            ]
        )
        print(
            f"  pairwiseIntersections avg={avg_overlap:.1f} max={pair_overlaps[0]} top={top_pairs}"
        )

    if repeat_pairs > 0:
        print(
            "  repeatGaps "
            f"pairs={repeat_pairs} "
            + " ".join(
                f"<{threshold}:{repeat_gap_below[threshold]}/{repeat_pairs}"
                f" ({repeat_gap_below[threshold] / repeat_pairs:.3f})"
                for threshold in (12, 16, 20)
            )
        )

    if top_rows:
        compact = ", ".join(
            f"{word}({occ}x/{groups}g)"
            for groups, occ, word in top_rows[: max(0, top_repeats)]
        )
        print(f"  topRepeated: {compact}")


def print_pack_summary(
    group_order: list[dict],
    level_by_id: dict[str, dict],
    answer_words_by_level: dict[str, list[str]],
) -> list[dict]:
    rows: list[dict] = []
    for group in group_order:
        group_id = str(group.get("id", "")).strip()
        group_level_ids = [
            level_id
            for level_id in group.get("levelIds", [])
            if isinstance(level_id, str) and level_id in level_by_id
        ]
        if not group_level_ids:
            continue

        answer_slots = 0
        short_slots = 0
        unique_words: set[str] = set()
        word_counts: Counter[str] = Counter()
        min_freqs: list[float] = []
        avg_freqs: list[float] = []
        p25_freqs: list[float] = []
        difficulties: list[float] = []
        shape_counts: Counter[str] = Counter()
        wheel_token_slots = 0
        swap_sensitive_token_slots = 0

        for level_id in group_level_ids:
            level = level_by_id[level_id]
            shape_counts[infer_wheel_shape(level)] += 1
            level_token_slots, level_swap_sensitive_slots = wheel_token_stats(level)
            wheel_token_slots += level_token_slots
            swap_sensitive_token_slots += level_swap_sensitive_slots
            words = answer_words_by_level.get(level_id, [])
            answer_slots += len(words)
            for word in words:
                unique_words.add(word)
                word_counts[word] += 1
                if len(word) <= 4:
                    short_slots += 1

            min_freq, avg_freq, p25_freq = level_frequency_stats(level)
            min_freqs.append(min_freq)
            avg_freqs.append(avg_freq)
            p25_freqs.append(p25_freq)

            difficulty_raw = level.get("difficulty")
            if isinstance(difficulty_raw, (int, float)):
                difficulties.append(float(difficulty_raw))

        repeated_slots = sum(count for count in word_counts.values() if count > 1)
        rows.append(
            {
                "groupId": group_id,
                "groupIndex": int(group.get("index", 0)),
                "levelCount": len(group_level_ids),
                "answerSlots": answer_slots,
                "uniqueWords": len(unique_words),
                "repeatedSlots": repeated_slots,
                "repeatedRatio": (repeated_slots / answer_slots)
                if answer_slots
                else 0.0,
                "shortRatio": (short_slots / answer_slots) if answer_slots else 0.0,
                "avgAnswers": (answer_slots / len(group_level_ids)),
                "avgMinFreq": (sum(min_freqs) / len(min_freqs)) if min_freqs else 0.0,
                "avgAvgFreq": (sum(avg_freqs) / len(avg_freqs)) if avg_freqs else 0.0,
                "avgP25Freq": (sum(p25_freqs) / len(p25_freqs)) if p25_freqs else 0.0,
                "avgDifficulty": (sum(difficulties) / len(difficulties))
                if difficulties
                else 0.0,
                "swapSensitiveTokenRatio": (
                    swap_sensitive_token_slots / wheel_token_slots
                )
                if wheel_token_slots
                else 0.0,
                "shapeMix": format_shape_distribution(
                    shape_counts,
                    len(group_level_ids),
                ),
                "targetAvgFreq": (
                    float(group.get("targetAvgAnswerFreq", 0.0))
                    if isinstance(group.get("targetAvgAnswerFreq"), (int, float))
                    else None
                ),
            }
        )

    if not rows:
        return []

    print("\nPack stats:")
    for row in rows:
        target_avg_freq = row["targetAvgFreq"]
        parts = [
            f"{row['groupId']}:",
            f"levels={row['levelCount']}",
            f"slots={row['answerSlots']}",
            f"avgAns={row['avgAnswers']:.2f}",
            f"uniq={row['uniqueWords']}",
            f"rep={row['repeatedRatio']:.3f}",
            f"short={row['shortRatio']:.3f}",
            f"freq[min/avg/p25]={row['avgMinFreq']:.3f}/{row['avgAvgFreq']:.3f}/{row['avgP25Freq']:.3f}",
            f"diff={row['avgDifficulty']:.3f}",
            f"swapTok={row['swapSensitiveTokenRatio']:.3f}",
            f"shapes={row['shapeMix']}",
        ]
        if isinstance(target_avg_freq, float):
            target_delta = row["avgAvgFreq"] - target_avg_freq
            parts.append(f"target={target_avg_freq:.3f}")
            parts.append(f"d={target_delta:+.3f}")
        print("  " + " ".join(parts))

    hardest_by_freq = sorted(
        rows, key=lambda item: (item["avgAvgFreq"], item["groupId"])
    )
    highest_reuse = sorted(
        rows,
        key=lambda item: (item["repeatedRatio"], item["answerSlots"]),
        reverse=True,
    )
    print(
        "Pack highlights: "
        + "hardestVocab="
        + ", ".join(
            f"{row['groupId']}({row['avgAvgFreq']:.3f})"
            for row in hardest_by_freq[: min(3, len(hardest_by_freq))]
        )
        + " highestReuse="
        + ", ".join(
            f"{row['groupId']}({row['repeatedRatio']:.3f})"
            for row in highest_reuse[: min(3, len(highest_reuse))]
        )
    )
    return rows


def print_progression_summary(rows: list[dict], start_group_index: int) -> None:
    late_rows = [row for row in rows if int(row["groupIndex"]) >= start_group_index]
    if len(late_rows) < 2:
        return

    freq_series = [float(row["avgAvgFreq"]) for row in late_rows]
    diff_series = [float(row["avgDifficulty"]) for row in late_rows]
    short_series = [float(row["shortRatio"]) for row in late_rows]
    index_series = [float(idx) for idx in range(len(late_rows))]

    adjacency_total = len(late_rows) - 1
    harder_adj_freq = sum(
        1
        for idx in range(1, len(freq_series))
        if freq_series[idx] <= freq_series[idx - 1]
    )
    harder_adj_diff = sum(
        1
        for idx in range(1, len(diff_series))
        if diff_series[idx] >= diff_series[idx - 1]
    )
    harder_adj_short = sum(
        1
        for idx in range(1, len(short_series))
        if short_series[idx] <= short_series[idx - 1]
    )

    target_deltas = [
        abs(float(row["avgAvgFreq"]) - float(row["targetAvgFreq"]))
        for row in late_rows
        if isinstance(row.get("targetAvgFreq"), float)
    ]
    avg_target_abs_delta = (
        (sum(target_deltas) / len(target_deltas)) if target_deltas else 0.0
    )

    print("Progression:")
    print(
        "  "
        + " ".join(
            [
                f"range={late_rows[0]['groupId']}->{late_rows[-1]['groupId']}",
                f"avgFreqDelta={freq_series[-1] - freq_series[0]:+.3f}",
                f"avgDiffDelta={diff_series[-1] - diff_series[0]:+.3f}",
            ]
        )
    )
    print(
        "  "
        + " ".join(
            [
                f"adjHarderByFreq={harder_adj_freq}/{adjacency_total}",
                f"({(harder_adj_freq / adjacency_total):.3f})",
                f"adjHarderByDiff={harder_adj_diff}/{adjacency_total}",
                f"({(harder_adj_diff / adjacency_total):.3f})",
                f"adjHarderByShort={harder_adj_short}/{adjacency_total}",
                f"({(harder_adj_short / adjacency_total):.3f})",
            ]
        )
    )
    print(
        "  "
        + " ".join(
            [
                f"corrIndexAvgFreq[p/s]={pearson(index_series, freq_series):+.3f}/{spearman(index_series, freq_series):+.3f}",
                f"corrIndexDiff[p/s]={pearson(index_series, diff_series):+.3f}/{spearman(index_series, diff_series):+.3f}",
                f"corrIndexShort[p/s]={pearson(index_series, short_series):+.3f}/{spearman(index_series, short_series):+.3f}",
                (
                    f"targetAvgAbsDelta={avg_target_abs_delta:.3f}"
                    if target_deltas
                    else "targetAvgAbsDelta=n/a"
                ),
            ]
        )
    )
    print(
        "  "
        + " ".join(
            [
                f"shortRatioDelta={short_series[-1] - short_series[0]:+.3f}",
                f"rangeStartShort={short_series[0]:.3f}",
                f"rangeEndShort={short_series[-1]:.3f}",
            ]
        )
    )


def print_difficulty_scoring_analysis(
    levels: list[dict],
    group_order: list[dict],
    level_by_id: dict[str, dict],
    start_group_index: int,
) -> None:
    """Analyze difficulty scoring components and their correlations."""
    if not levels:
        return

    # Collect metrics from all levels
    difficulties = []
    freq_scores = []
    int_eases = []
    len_eases = []
    int_ratios = []
    avg_lengths = []
    avg_freqs = []

    for level in levels:
        stats = level.get("placementStats", {})
        features = level.get("difficultyFeatures", {})

        difficulties.append(float(level.get("difficulty", 0)))
        freq_scores.append(float(features.get("freq", 0)))
        int_eases.append(float(features.get("intersectionEase", 0)))
        len_eases.append(float(features.get("lengthEase", 0)))
        int_ratios.append(float(stats.get("intersectionRatio", 0)))
        avg_lengths.append(float(stats.get("avgAnswerLength", 0)))
        avg_freqs.append(float(features.get("avgAnswerFreq", 0)))

    # Difficulty distribution
    sorted_diff = sorted(difficulties)
    n = len(sorted_diff)

    print("\nDifficulty scoring:")
    print(
        f"  distribution: min={min(difficulties):.4f}, max={max(difficulties):.4f}, "
        f"mean={sum(difficulties) / n:.4f}, median={sorted_diff[n // 2]:.4f}"
    )
    print(
        f"  percentiles: p10={sorted_diff[int(n * 0.1)]:.4f}, "
        f"p25={sorted_diff[int(n * 0.25)]:.4f}, p50={sorted_diff[int(n * 0.5)]:.4f}, "
        f"p75={sorted_diff[int(n * 0.75)]:.4f}, p90={sorted_diff[int(n * 0.9)]:.4f}"
    )

    # Correlations with difficulty
    corr_freq = pearson(difficulties, freq_scores)
    corr_int = pearson(difficulties, int_eases)
    corr_len = pearson(difficulties, len_eases)
    corr_avg_freq = pearson(difficulties, avg_freqs)

    print(
        f"  correlations: freq={corr_freq:+.3f}, intersectionEase={corr_int:+.3f}, "
        f"lengthEase={corr_len:+.3f}, avgAnswerFreq={corr_avg_freq:+.3f}"
    )

    # Group-level trends (E to AZ)
    late_groups = [
        g for g in group_order if int(g.get("index", 0)) >= start_group_index
    ]
    if len(late_groups) < 2:
        return

    group_metrics = []
    for group in late_groups:
        level_ids = [
            lid
            for lid in group.get("levelIds", [])
            if isinstance(lid, str) and lid in level_by_id
        ]
        if not level_ids:
            continue

        group_diffs = []
        group_int_eases = []
        group_len_eases = []
        group_int_ratios = []
        group_avg_lens = []

        for lid in level_ids:
            level = level_by_id[lid]
            stats = level.get("placementStats", {})
            features = level.get("difficultyFeatures", {})

            group_diffs.append(float(level.get("difficulty", 0)))
            group_int_eases.append(float(features.get("intersectionEase", 0)))
            group_len_eases.append(float(features.get("lengthEase", 0)))
            group_int_ratios.append(float(stats.get("intersectionRatio", 0)))
            group_avg_lens.append(float(stats.get("avgAnswerLength", 0)))

        def avg(lst):
            return sum(lst) / len(lst) if lst else 0.0

        group_metrics.append(
            {
                "label": group.get("id", ""),
                "difficulty": avg(group_diffs),
                "intEase": avg(group_int_eases),
                "lenEase": avg(group_len_eases),
                "intRatio": avg(group_int_ratios),
                "avgLen": avg(group_avg_lens),
            }
        )

    if len(group_metrics) < 2:
        return

    # Calculate trends
    def trend(data):
        n = len(data)
        x = list(range(n))
        sum_x = sum(x)
        sum_y = sum(data)
        sum_xy = sum(i * d for i, d in enumerate(data))
        sum_x2 = sum(i * i for i in x)
        denom = n * sum_x2 - sum_x * sum_x
        return (n * sum_xy - sum_x * sum_y) / denom if denom else 0.0

    diff_trend = trend([g["difficulty"] for g in group_metrics])
    int_ease_trend = trend([g["intEase"] for g in group_metrics])
    len_ease_trend = trend([g["lenEase"] for g in group_metrics])
    int_ratio_trend = trend([g["intRatio"] for g in group_metrics])
    avg_len_trend = trend([g["avgLen"] for g in group_metrics])

    print(
        f"  trends (E->AZ): difficulty={diff_trend:+.6f}, intEase={int_ease_trend:+.6f}, "
        f"lenEase={len_ease_trend:+.6f}, intRatio={int_ratio_trend:+.6f}, avgLen={avg_len_trend:+.6f}"
    )

    # First and last group summary
    first = group_metrics[0]
    last = group_metrics[-1]
    print(
        f"  range summary: E(diff={first['difficulty']:.3f}, intRatio={first['intRatio']:.3f}, "
        f"avgLen={first['avgLen']:.3f}) -> AZ(diff={last['difficulty']:.3f}, intRatio={last['intRatio']:.3f}, avgLen={last['avgLen']:.3f})"
    )


def print_word_length_distribution(
    levels: list[dict],
    group_order: list[dict],
    level_by_id: dict[str, dict],
    start_group_index: int,
) -> None:
    """Analyze word length distribution by group."""
    from collections import Counter

    # Collect word length distribution for each group
    group_data = []
    for group in group_order:
        label = group.get("id", "")
        level_ids = [
            lid
            for lid in group.get("levelIds", [])
            if isinstance(lid, str) and lid in level_by_id
        ]
        if not level_ids:
            continue

        length_counts: Counter[int] = Counter()
        total = 0

        for level_id in level_ids:
            level = level_by_id[level_id]
            for answer in level.get("answers", []):
                if isinstance(answer, dict):
                    word_len = len(answer.get("text", ""))
                    if word_len >= 3:
                        length_counts[word_len] += 1
                        total += 1

        if total > 0:
            group_data.append(
                {
                    "label": label,
                    "index": int(group.get("index", 0)),
                    "lengths": length_counts,
                    "total": total,
                }
            )

    if not group_data:
        return

    # Print header
    lengths = list(range(3, 8))  # 3-7 letter words
    print("\nWord length distribution:")
    print(f"  {'Group':<5}   3L%    4L%    5L%    6L%    7L%")

    # Print each group (show E onwards in condensed form)
    late_groups = [g for g in group_data if g["index"] >= start_group_index]

    # Show first 5 and last 5 of late groups
    shown_groups = (
        late_groups[:5] + late_groups[-5:] if len(late_groups) > 10 else late_groups
    )

    for g in shown_groups:
        row = f"{g['label']:<5}"
        for l in lengths:
            count = g["lengths"].get(l, 0)
            pct = (count / g["total"] * 100) if g["total"] else 0
            row += f" {pct:>5.1f}"
        print(f"  {row}")

    # Calculate and show trends
    def trend(data: list[float]) -> float:
        n = len(data)
        if n < 2:
            return 0.0
        x = list(range(n))
        sum_x = sum(x)
        sum_y = sum(data)
        sum_xy = sum(i * d for i, d in enumerate(data))
        sum_x2 = sum(i * i for i in x)
        denom = n * sum_x2 - sum_x * sum_x
        return (n * sum_xy - sum_x * sum_y) / denom if denom else 0.0

    if len(late_groups) >= 2:
        print("  trends (E->AZ):", end="")
        for length in lengths:
            pcts = []
            for g in late_groups:
                count = g["lengths"].get(length, 0)
                pct = (count / g["total"] * 100) if g["total"] else 0
                pcts.append(pct)
            t = trend(pcts)
            direction = "↓" if t < -0.05 else ("↑" if t > 0.05 else "→")
            print(f" {length}L={direction}{abs(t):.3f}", end="")
        print()

        # Show E vs AZ comparison
        first = late_groups[0]
        last = late_groups[-1]
        e_3l = (
            (first["lengths"].get(3, 0) / first["total"] * 100) if first["total"] else 0
        )
        az_3l = (
            (last["lengths"].get(3, 0) / last["total"] * 100) if last["total"] else 0
        )
        e_4l = (
            (first["lengths"].get(4, 0) / first["total"] * 100) if first["total"] else 0
        )
        az_4l = (
            (last["lengths"].get(4, 0) / last["total"] * 100) if last["total"] else 0
        )
        print(
            f"  range: E(3L={e_3l:.1f}%, 4L={e_4l:.1f}%) -> AZ(3L={az_3l:.1f}%, 4L={az_4l:.1f}%)"
        )


def run_analysis(args: argparse.Namespace) -> None:
    bundle_path = resolve_path(args.bundle)
    payload = load_json(bundle_path)
    groups = [item for item in payload.get("groups", []) if isinstance(item, dict)]
    levels = [item for item in payload.get("levels", []) if isinstance(item, dict)]

    answer_count_distribution: Counter[int] = Counter()
    answer_length_distribution: Counter[int] = Counter()
    answer_counts: list[int] = []
    total_answer_words = 0
    answer_word_counter: Counter[str] = Counter()
    wheel_shape_counter: Counter[str] = Counter()
    global_wheel_token_slots = 0
    global_swap_sensitive_token_slots = 0
    answer_words_by_level: dict[str, list[str]] = {}
    wheel_tokens_by_level: dict[str, list[str]] = {}
    level_by_id: dict[str, dict] = {}

    group_order = sorted(
        groups,
        key=lambda item: (
            int(item.get("index", 1_000_000)),
            str(item.get("id", "")),
        ),
    )
    ordered_group_ids = [str(item.get("id", "")).strip() for item in group_order]

    level_to_group_id: dict[str, str] = {}
    level_to_group_pos: dict[str, int] = {}
    for group in group_order:
        group_id = str(group.get("id", "")).strip()
        for pos, level_id in enumerate(group.get("levelIds", []), start=1):
            if isinstance(level_id, str):
                level_to_group_id[level_id] = group_id
                level_to_group_pos[level_id] = pos

    for level in levels:
        level_id = str(level.get("id", ""))
        level_by_id[level_id] = level
        answer_lengths = parse_answer_lengths(level)
        wheel_shape_counter[infer_wheel_shape(level)] += 1
        level_token_slots, level_swap_sensitive_slots = wheel_token_stats(level)
        global_wheel_token_slots += level_token_slots
        global_swap_sensitive_token_slots += level_swap_sensitive_slots
        answer_count = len(answer_lengths)
        answer_counts.append(answer_count)
        total_answer_words += answer_count
        answer_count_distribution[answer_count] += 1
        answer_length_distribution.update(answer_lengths)
        words_for_level: list[str] = []
        for answer in level.get("answers", []):
            if not isinstance(answer, dict):
                continue
            word = str(answer.get("text", "")).strip().lower()
            if not word:
                continue
            words_for_level.append(word)
            answer_word_counter[word] += 1
        answer_words_by_level[level_id] = words_for_level
        tokens_for_level: list[str] = []
        for token in level.get("letterWheel", []):
            token_text = str(token).strip().lower()
            if token_text:
                tokens_for_level.append(token_text)
        wheel_tokens_by_level[level_id] = tokens_for_level

    unique_answer_words = len(answer_word_counter)
    repeated_answer_slots = sum(
        count for count in answer_word_counter.values() if count > 1
    )
    repeated_unique_words = sum(
        1 for count in answer_word_counter.values() if count > 1
    )

    avg_answers = (total_answer_words / len(levels)) if levels else 0.0
    median_answers = median(answer_counts) if answer_counts else 0
    min_answers = min(answer_counts) if answer_counts else 0
    max_answers = max(answer_counts) if answer_counts else 0

    common_lengths = sorted(
        answer_length_distribution.items(), key=lambda item: (-item[1], item[0])
    )[:4]
    length_summary = ", ".join(
        f"len{length}:{count}" for length, count in common_lengths
    )

    print(f"Bundle: {bundle_path}")
    print(
        "Global: "
        f"levels={len(levels)} groups={len(ordered_group_ids)} "
        f"answerSlots={total_answer_words} uniqueWords={unique_answer_words} "
        f"answersPerLevel[min/med/avg/max]={min_answers}/{median_answers}/{avg_answers:.2f}/{max_answers}"
    )
    print(
        "Global repeats: "
        f"repeatedSlots={repeated_answer_slots}/{total_answer_words}"
        f" ({(repeated_answer_slots / total_answer_words) if total_answer_words else 0.0:.3f}) "
        f"repeatedUnique={repeated_unique_words}/{unique_answer_words}"
        f" ({(repeated_unique_words / unique_answer_words) if unique_answer_words else 0.0:.3f})"
    )
    if length_summary:
        print(f"Global common lengths: {length_summary}")
    if wheel_shape_counter:
        print(
            "Global wheel shapes: "
            + format_shape_distribution(wheel_shape_counter, len(levels), limit=5)
        )
    if global_wheel_token_slots:
        print(
            "Global swap-sensitive tokens: "
            f"{global_swap_sensitive_token_slots}/{global_wheel_token_slots} "
            f"({global_swap_sensitive_token_slots / global_wheel_token_slots:.3f})"
        )

    early_group_count = max(0, min(args.early_group_count, len(ordered_group_ids)))
    early_group_ids = ordered_group_ids[:early_group_count]
    late_group_ids = ordered_group_ids[early_group_count:]

    pack_rows = print_pack_summary(group_order, level_by_id, answer_words_by_level)
    print_progression_summary(pack_rows, early_group_count)
    print_difficulty_scoring_analysis(
        levels, group_order, level_by_id, early_group_count
    )
    print_word_length_distribution(levels, group_order, level_by_id, early_group_count)

    if early_group_ids:
        print_segment_summary(
            "EARLY",
            early_group_ids,
            answer_words_by_level,
            level_to_group_id,
            level_by_id,
            args.top_repeats,
        )
    if late_group_ids:
        print_segment_summary(
            "LATE",
            late_group_ids,
            answer_words_by_level,
            level_to_group_id,
            level_by_id,
            args.top_repeats,
        )

    watch_words = parse_watch_words(args.watch_words)
    if watch_words:
        print("\nWatch words:")
        for word in watch_words:
            hit_codes = []
            for level_id in sorted(answer_words_by_level):
                if word not in answer_words_by_level[level_id]:
                    continue
                group_id = level_to_group_id.get(level_id, "?")
                pos = level_to_group_pos.get(level_id)
                code = (
                    f"{group_id}{pos}" if pos is not None else f"{group_id}#{level_id}"
                )
                hit_codes.append(code)
            hits = ", ".join(hit_codes) if hit_codes else "none"
            print(f"  {word.upper()}: {len(hit_codes)} -> {hits}")

    all_level_ids = sorted(answer_words_by_level)
    early_level_ids = [
        level_id
        for level_id in all_level_ids
        if level_to_group_id.get(level_id) in early_group_ids
    ]

    repeated_early_word_rows = repeated_rows_for_segment(
        early_level_ids,
        answer_words_by_level,
        level_to_group_id,
        level_to_group_pos,
    )
    repeated_early_token_rows = repeated_rows_for_segment(
        early_level_ids,
        wheel_tokens_by_level,
        level_to_group_id,
        level_to_group_pos,
    )
    repeated_all_word_rows = repeated_rows_for_segment(
        all_level_ids,
        answer_words_by_level,
        level_to_group_id,
        level_to_group_pos,
    )
    repeated_all_token_rows = repeated_rows_for_segment(
        all_level_ids,
        wheel_tokens_by_level,
        level_to_group_id,
        level_to_group_pos,
    )
    all_solution_word_rows = solution_word_rows(
        group_order,
        answer_words_by_level,
        level_to_group_id,
        level_to_group_pos,
    )
    lexicon_path = resolve_path(args.lexicon)
    lexicon_freq_map, lexicon_words = load_lexicon_word_data(lexicon_path)
    solution_review_rows = solution_word_review_rows(
        all_solution_word_rows,
        freq_map=lexicon_freq_map,
        lexicon_words=lexicon_words,
        min_score=max(0, int(args.solution_words_review_min_score)),
    )
    unique_all_solution_words = unique_words_for_levels(
        all_level_ids, answer_words_by_level
    )
    unique_early_solution_words = unique_words_for_levels(
        early_level_ids,
        answer_words_by_level,
    )

    if args.repeated_words_early_csv_out.strip():
        repeated_words_early_out = resolve_path(args.repeated_words_early_csv_out)
        write_repeated_csv(repeated_words_early_out, "word", repeated_early_word_rows)
        print(
            f"\nRepeated early words CSV written -> {repeated_words_early_out} "
            f"rows={len(repeated_early_word_rows)}"
        )

    if args.repeated_tokens_early_csv_out.strip():
        repeated_tokens_early_out = resolve_path(args.repeated_tokens_early_csv_out)
        write_repeated_csv(
            repeated_tokens_early_out, "token", repeated_early_token_rows
        )
        print(
            f"Repeated early tokens CSV written -> {repeated_tokens_early_out} "
            f"rows={len(repeated_early_token_rows)}"
        )

    if args.repeated_words_all_csv_out.strip():
        repeated_words_all_out = resolve_path(args.repeated_words_all_csv_out)
        write_repeated_csv(repeated_words_all_out, "word", repeated_all_word_rows)
        print(
            f"Repeated full words CSV written -> {repeated_words_all_out} "
            f"rows={len(repeated_all_word_rows)}"
        )

    if args.repeated_tokens_all_csv_out.strip():
        repeated_tokens_all_out = resolve_path(args.repeated_tokens_all_csv_out)
        write_repeated_csv(repeated_tokens_all_out, "token", repeated_all_token_rows)
        print(
            f"Repeated full tokens CSV written -> {repeated_tokens_all_out} "
            f"rows={len(repeated_all_token_rows)}"
        )

    if args.solution_words_csv_out.strip():
        solution_words_out = resolve_path(args.solution_words_csv_out)
        write_solution_words_csv(solution_words_out, all_solution_word_rows)
        print(
            f"Solution words CSV written -> {solution_words_out} "
            f"rows={len(all_solution_word_rows)}"
        )

    if args.solution_words_review_csv_out.strip():
        solution_words_review_out = resolve_path(args.solution_words_review_csv_out)
        write_solution_word_review_csv(solution_words_review_out, solution_review_rows)
        print(
            f"Solution words review CSV written -> {solution_words_review_out} "
            f"rows={len(solution_review_rows)}"
        )

    if args.solution_words_unique_all_out.strip():
        solution_words_unique_all_out = resolve_path(args.solution_words_unique_all_out)
        write_unique_words_txt(solution_words_unique_all_out, unique_all_solution_words)
        print(
            f"Solution words unique-all TXT written -> {solution_words_unique_all_out} "
            f"rows={len(unique_all_solution_words)}"
        )

    if args.solution_words_unique_early_out.strip():
        solution_words_unique_early_out = resolve_path(
            args.solution_words_unique_early_out
        )
        write_unique_words_txt(
            solution_words_unique_early_out, unique_early_solution_words
        )
        print(
            f"Solution words unique-early TXT written -> {solution_words_unique_early_out} "
            f"rows={len(unique_early_solution_words)}"
        )


def main() -> None:
    args = parse_args()
    report_buffer = io.StringIO()
    with redirect_stdout(report_buffer):
        run_analysis(args)

    report = report_buffer.getvalue()
    print(report, end="")

    report_out = resolve_path(args.report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(report, encoding="utf-8")
    print(f"\nAnalysis report written -> {report_out}")


if __name__ == "__main__":
    main()

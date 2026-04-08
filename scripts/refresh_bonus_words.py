from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json, project_path, save_json
from generate_boards import candidate_words_from_wheel, min_token_count

LEVELS_DIR = project_path("src", "data")
BONUS_LEXICON_PATH = project_path("data", "processed", "lexicon_bonus.json")


def load_bonus_lexicon(path: Path) -> tuple[set[str], dict[str, float]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    words = payload.get("words", [])
    lexicon_set: set[str] = set()
    freq_map: dict[str, float] = {}
    for item in words:
        if not isinstance(item, dict):
            continue
        word = item.get("word")
        if not isinstance(word, str) or not word:
            continue
        token = word.strip().lower()
        if not token:
            continue
        lexicon_set.add(token)
        freq_map[token] = float(item.get("freq", 0.0))

    return lexicon_set, freq_map


def normalize_answer_words(level: dict) -> set[str]:
    out: set[str] = set()
    for answer in level.get("answers", []):
        if not isinstance(answer, dict):
            continue
        text = str(answer.get("text", "")).strip().lower()
        if text:
            out.add(text)
    return out


def normalize_wheel(level: dict) -> list[str]:
    out: list[str] = []
    for token in level.get("letterWheel", []):
        if not isinstance(token, str):
            continue
        text = token.strip().lower()
        if text:
            out.append(text)
    return out


def normalize_bonus_words(level: dict) -> list[str]:
    out: list[str] = []
    for token in level.get("bonusWords", []):
        if not isinstance(token, str):
            continue
        text = token.strip().lower()
        if text:
            out.append(text)
    return sorted(out)


def compute_bonus_words(
    wheel_tokens: list[str],
    answer_words: set[str],
    bonus_lexicon_set: set[str],
    bonus_freq_map: dict[str, float],
    min_word_len: int,
    max_word_len: int,
    max_candidate_words: int,
    min_bonus_token_count: int,
    max_bonus_words: int,
) -> list[str]:
    bonus_forward_masks, _ = candidate_words_from_wheel(
        wheel_tokens,
        bonus_lexicon_set,
        min_word_len,
        max_word_len,
        max_candidate_words,
        "forward",
    )
    bonus_reverse_masks, _ = candidate_words_from_wheel(
        wheel_tokens,
        bonus_lexicon_set,
        min_word_len,
        max_word_len,
        max_candidate_words,
        "reverse",
    )

    bonus_candidate_word_masks: dict[str, set[int]] = {}
    for masks_map in (bonus_forward_masks, bonus_reverse_masks):
        for word, masks in masks_map.items():
            bonus_candidate_word_masks.setdefault(word, set()).update(masks)

    bonus_min_candidate_tokens = {
        word: min_token_count(masks)
        for word, masks in bonus_candidate_word_masks.items()
        if masks
    }

    def bonus_word_freq(word: str) -> float:
        return bonus_freq_map.get(word, 0.0)

    candidate_words_by_freq = sorted(
        bonus_candidate_word_masks,
        key=lambda item: (-bonus_word_freq(item), item),
    )

    valid_words = [
        word
        for word in candidate_words_by_freq
        if word not in answer_words
        and bonus_min_candidate_tokens.get(word, 0) >= min_bonus_token_count
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
    return sorted(bonus_words_ranked[:max_bonus_words])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh bonusWords in exported levels from bonus lexicon and wheel tokens."
    )
    parser.add_argument(
        "--levels-dir",
        default=str(LEVELS_DIR),
        help="Directory containing levels.*.json files.",
    )
    parser.add_argument(
        "--bonus-lexicon",
        default=str(BONUS_LEXICON_PATH),
        help="Bonus lexicon JSON path.",
    )
    parser.add_argument("--min-word-len", type=int, default=3)
    parser.add_argument("--max-word-len", type=int, default=12)
    parser.add_argument("--max-candidate-words", type=int, default=2500)
    parser.add_argument("--min-bonus-token-count", type=int, default=2)
    parser.add_argument("--max-bonus-words", type=int, default=220)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files.",
    )
    args = parser.parse_args()

    levels_dir = Path(args.levels_dir)
    bonus_lexicon_path = Path(args.bonus_lexicon)

    bonus_lexicon_set, bonus_freq_map = load_bonus_lexicon(bonus_lexicon_path)
    print(
        f"Loaded bonus lexicon: {len(bonus_lexicon_set)} words from {bonus_lexicon_path}"
    )

    files = sorted(levels_dir.glob("levels.*.json"))
    files = [path for path in files if path.stem != "levels._meta"]

    total_levels = 0
    changed_levels = 0
    changed_files = 0

    for path in files:
        payload = load_json(path)
        levels = payload.get("levels", [])
        if not isinstance(levels, list):
            continue

        file_changed = False
        updated_levels: list = []
        for level in levels:
            if not isinstance(level, dict):
                updated_levels.append(level)
                continue

            total_levels += 1
            wheel_tokens = normalize_wheel(level)
            answer_words = normalize_answer_words(level)
            current_bonus = normalize_bonus_words(level)
            next_bonus = compute_bonus_words(
                wheel_tokens,
                answer_words,
                bonus_lexicon_set,
                bonus_freq_map,
                min_word_len=int(args.min_word_len),
                max_word_len=int(args.max_word_len),
                max_candidate_words=int(args.max_candidate_words),
                min_bonus_token_count=int(args.min_bonus_token_count),
                max_bonus_words=int(args.max_bonus_words),
            )

            if current_bonus != next_bonus:
                changed_levels += 1
                file_changed = True
                level_id = level.get("id", "?")
                print(
                    f"  {level_id}: bonusWords {len(current_bonus)} -> {len(next_bonus)}"
                )
                updated = dict(level)
                updated["bonusWords"] = next_bonus
                updated_levels.append(updated)
            else:
                updated_levels.append(level)

        if file_changed:
            changed_files += 1
            if not args.dry_run:
                payload["levels"] = updated_levels
                save_json(path, payload)
            print(f"  {path.name}: updated" + (" (dry-run)" if args.dry_run else ""))

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Levels scanned:   {total_levels}")
    print(f"Levels changed:   {changed_levels}")
    print(f"Files changed:    {changed_files}")
    if args.dry_run:
        print("(dry-run — no files were written)")


if __name__ == "__main__":
    main()

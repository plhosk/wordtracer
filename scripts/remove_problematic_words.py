from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import load_json, project_path, save_json

PROBLEMATIC_TXT = project_path("plans", "problematic.txt")
LEVELS_DIR = project_path("src", "data")


def load_problematic_words(txt_path: Path) -> set[str]:
    words: set[str] = set()
    with txt_path.open("r", encoding="utf-8") as f:
        for line in f:
            token = line.strip().lower()
            if token:
                words.add(token)
    return words


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


def derive_walls_from_paths(
    rows: int, cols: int, paths: list[list[tuple[int, int]]]
) -> tuple[list[list[int]], list[list[int]]]:
    h = [[1 for _ in range(cols)] for _ in range(rows - 1)]
    v = [[1 for _ in range(cols - 1)] for _ in range(rows)]
    for path in paths:
        for idx in range(1, len(path)):
            open_edge(h, v, path[idx - 1], path[idx])
    return h, v


def derive_walls_sparse(
    rows: int,
    cols: int,
    paths: list[list[tuple[int, int]]],
    h: list[list[int]],
    v: list[list[int]],
) -> dict[str, list[int]]:
    occupied: set[tuple[int, int]] = set()
    for path in paths:
        for cell in path:
            occupied.add((cell[0], cell[1]))

    walls: dict[str, list[int]] = {}
    for r, c in occupied:
        if (r - 1, c) not in occupied:
            top = 1
        elif r > 0:
            top = h[r - 1][c]
        else:
            top = 1

        if (r + 1, c) not in occupied:
            bottom = 1
        elif r < rows - 1:
            bottom = h[r][c]
        else:
            bottom = 1

        if (r, c - 1) not in occupied:
            left = 1
        elif c > 0:
            left = v[r][c - 1]
        else:
            left = 1

        if (r, c + 1) not in occupied:
            right = 1
        elif c < cols - 1:
            right = v[r][c]
        else:
            right = 1

        walls[f"{r},{c}"] = [top, right, bottom, left]

    return walls


def answer_path_tuples(answer: dict) -> list[tuple[int, int]]:
    return [(int(p[0]), int(p[1])) for p in answer.get("path", [])]


def process_level(level: dict, problematic: set[str]) -> tuple[dict, int, int]:
    answers = level.get("answers", [])
    bonus_words = level.get("bonusWords", [])

    original_answer_words = {
        str(a.get("text", "")).strip().lower() for a in answers if isinstance(a, dict)
    }
    problematic_answers = original_answer_words & problematic

    filtered_answers = [
        a
        for a in answers
        if isinstance(a, dict)
        and str(a.get("text", "")).strip().lower() not in problematic
    ]

    filtered_bonus = [w for w in bonus_words if w.lower() not in problematic]
    bonus_removed = len(bonus_words) - len(filtered_bonus)
    answers_removed = len(answers) - len(filtered_answers)

    if answers_removed == 0 and bonus_removed == 0:
        return level, 0, 0

    rows = int(level.get("rows", 0))
    cols = int(level.get("cols", 0))
    surviving_paths = [answer_path_tuples(a) for a in filtered_answers]
    h, v = derive_walls_from_paths(rows, cols, surviving_paths)
    new_walls = derive_walls_sparse(rows, cols, surviving_paths, h, v)

    modified = dict(level)
    modified["answers"] = filtered_answers
    modified["bonusWords"] = filtered_bonus
    modified["walls"] = new_walls

    return modified, answers_removed, bonus_removed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove problematic words from level data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files.",
    )
    args = parser.parse_args()

    problematic = load_problematic_words(PROBLEMATIC_TXT)
    print(f"Loaded {len(problematic)} problematic words from {PROBLEMATIC_TXT}")

    group_files = sorted(LEVELS_DIR.glob("levels.*.json"))
    group_files = [f for f in group_files if f.stem != "levels._meta"]

    total_levels = 0
    total_levels_modified = 0
    total_answers_removed = 0
    total_bonus_removed = 0

    for group_file in group_files:
        payload = load_json(group_file)
        levels = payload.get("levels", [])
        if not isinstance(levels, list):
            continue

        group_id = payload.get("groupId", group_file.stem)
        modified_levels: list[dict] = []
        group_answers_removed = 0
        group_bonus_removed = 0

        for level in levels:
            if not isinstance(level, dict):
                modified_levels.append(level)
                continue
            total_levels += 1
            new_level, ans_rm, bonus_rm = process_level(level, problematic)
            modified_levels.append(new_level)
            if ans_rm > 0 or bonus_rm > 0:
                total_levels_modified += 1
                group_answers_removed += ans_rm
                group_bonus_removed += bonus_rm
                level_id = level.get("id", "?")
                parts = []
                if ans_rm:
                    removed_words = sorted(
                        str(a.get("text", ""))
                        for a in level.get("answers", [])
                        if isinstance(a, dict)
                        and str(a.get("text", "")).strip().lower() in problematic
                    )
                    parts.append(f"answers [{', '.join(removed_words)}]")
                if bonus_rm:
                    parts.append(f"bonus({bonus_rm})")
                print(f"  {level_id}: removed {' + '.join(parts)}")

        total_answers_removed += group_answers_removed
        total_bonus_removed += group_bonus_removed

        if group_answers_removed > 0 or group_bonus_removed > 0:
            if not args.dry_run:
                payload["levels"] = modified_levels
                save_json(group_file, payload)
            print(
                f"  {group_file.name}: {group_answers_removed} answers, "
                f"{group_bonus_removed} bonus words removed"
                + (" (dry-run)" if args.dry_run else "")
            )

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Levels scanned:          {total_levels}")
    print(f"Levels modified:         {total_levels_modified}")
    print(f"Answer words removed:    {total_answers_removed}")
    print(f"Bonus words removed:     {total_bonus_removed}")
    if args.dry_run:
        print("(dry-run — no files were written)")


if __name__ == "__main__":
    main()

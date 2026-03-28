from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from common import load_json, project_path

ENGLISH_FREQ: dict[str, float] = {
    "a": 8.55,
    "b": 1.60,
    "c": 3.16,
    "d": 3.87,
    "e": 12.10,
    "f": 2.18,
    "g": 2.09,
    "h": 4.96,
    "i": 7.33,
    "j": 0.22,
    "k": 0.81,
    "l": 4.21,
    "m": 2.53,
    "n": 7.17,
    "o": 7.47,
    "p": 2.07,
    "q": 0.10,
    "r": 6.33,
    "s": 6.73,
    "t": 8.94,
    "u": 2.68,
    "v": 1.06,
    "w": 1.83,
    "x": 0.19,
    "y": 1.72,
    "z": 0.11,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate frequency of single-letter tokens in level letter wheels."
    )
    parser.add_argument(
        "--bundle",
        default=str(project_path("data", "generated", "levels.bundle.json")),
        help="Path to exported levels bundle JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle_path = Path(args.bundle)
    payload = load_json(bundle_path)
    levels = [item for item in payload.get("levels", []) if isinstance(item, dict)]

    single_token_counter: Counter[str] = Counter()
    expanded_letter_counter: Counter[str] = Counter()
    total_tokens = 0
    total_single = 0

    for level in levels:
        for token in level.get("letterWheel", []):
            text = str(token).strip().lower()
            if not text:
                continue
            total_tokens += 1
            expanded_letter_counter.update(text)
            if len(text) == 1:
                total_single += 1
                single_token_counter[text] += 1

    total_expanded = sum(expanded_letter_counter.values())

    print(f"Bundle: {bundle_path}")
    print(f"Levels: {len(levels)}")
    print(f"Total wheel tokens: {total_tokens}")
    print(
        f"Single-letter tokens: {total_single} ({total_single / total_tokens:.3%})"
        if total_tokens
        else ""
    )
    print(
        f"Expanded letter positions: {total_expanded} "
        f"(avg {total_expanded / len(levels):.1f} per level)"
    )

    print(
        f"\n{'Letter':<8} {'English':>8} "
        f"{'Token%':>8} {'Δtok':>7} "
        f"{'All%':>8} {'Δall':>7}"
    )
    print("-" * 50)

    for letter in sorted(ENGLISH_FREQ):
        eng = ENGLISH_FREQ[letter]
        tok_pct = (
            single_token_counter[letter] / total_single * 100 if total_single else 0
        )
        delta_tok = tok_pct - eng
        all_pct = (
            expanded_letter_counter[letter] / total_expanded * 100
            if total_expanded
            else 0
        )
        delta_all = all_pct - eng
        print(
            f"{letter:<8} "
            f"{eng:>7.2f}% "
            f"{tok_pct:>7.2f}% {delta_tok:>+6.2f} "
            f"{all_pct:>7.2f}% {delta_all:>+6.2f}"
        )


if __name__ == "__main__":
    main()

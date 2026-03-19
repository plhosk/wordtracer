from __future__ import annotations

import argparse
from collections import defaultdict
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
        description="Extract configurable letter combo mappings from lexicon."
    )
    parser.add_argument(
        "--lexicon",
        default=str(project_path("data", "processed", "lexicon.json")),
        help="Path to lexicon JSON.",
    )
    parser.add_argument(
        "--out",
        default=str(project_path("data", "processed", "combos.json")),
        help="Path for combo mapping JSON output.",
    )
    parser.add_argument(
        "--combo-sizes",
        default=",".join(str(size) for size in DEFAULT_COMBO_SIZES),
        help="Comma-separated combo sizes, e.g. '1,2'. Default: 1,2",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def main() -> None:
    args = parse_args()
    combo_sizes = parse_combo_sizes(args.combo_sizes)
    lexicon_path = resolve_path(args.lexicon)
    out_path = resolve_path(args.out)

    lexicon = load_json(lexicon_path)
    words = lexicon.get("words", [])

    combo_to_words: dict[str, list[str]] = defaultdict(list)
    word_to_combos: dict[str, list[str]] = {}
    word_freq: dict[str, float] = {}

    for entry in words:
        word = entry["word"]
        freq = float(entry.get("freq", 0.0))
        combos = generate_combos(word, combo_sizes)
        word_to_combos[word] = combos
        word_freq[word] = freq
        for combo in combos:
            combo_to_words[combo].append(word)

    for combo in combo_to_words:
        combo_to_words[combo].sort(key=lambda item: (-word_freq.get(item, 0.0), item))

    words_per_combo = [len(bucket) for bucket in combo_to_words.values()]
    avg_words_per_combo = (
        round(sum(words_per_combo) / len(words_per_combo), 4)
        if words_per_combo
        else 0.0
    )

    payload = {
        "meta": {
            "comboSizes": list(combo_sizes),
            "wordCount": len(word_to_combos),
            "comboCount": len(combo_to_words),
            "avgWordsPerCombo": avg_words_per_combo,
        },
        "wordToCombos": word_to_combos,
        "comboToWords": dict(combo_to_words),
    }

    save_json(out_path, payload)
    print(f"Wrote combos for {len(word_to_combos)} words to {out_path}")


if __name__ == "__main__":
    main()

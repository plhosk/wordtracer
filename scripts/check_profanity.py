#!/usr/bin/env python3
"""Check solution words against the profane blocklist for substring matches >= 65%."""

import json
import glob
import os
from difflib import SequenceMatcher

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "src", "data")
BLOCKLIST_PATH = os.path.join(
    SCRIPT_DIR, "..", "data", "raw", "blocklists", "words.json"
)
THRESHOLD = 0.65
MIN_SUBSTR_LEN = 4


def load_blocklist():
    with open(BLOCKLIST_PATH) as f:
        words = json.load(f)
    return sorted(
        set(w.lower().strip() for w in words if len(w.strip()) >= MIN_SUBSTR_LEN)
    )


def load_solution_words():
    words = []
    files = sorted(glob.glob(os.path.join(DATA_DIR, "levels.*.json")))
    files = [f for f in files if not f.endswith("_meta.json")]
    for fpath in files:
        with open(fpath) as f:
            data = json.load(f)
        group_id = data.get("groupId", "?")
        for level in data.get("levels", []):
            level_id = level.get("id", "?")
            for answer in level.get("answers", []):
                text = answer["text"].lower()
                words.append((text, level_id, group_id))
    return words


def main():
    blocklist = load_blocklist()
    print(f"Blocklist: {len(blocklist)} entries loaded (>= {MIN_SUBSTR_LEN} chars)\n")

    solution_words = load_solution_words()
    print(f"Solution word entries: {len(solution_words)}\n")

    unique_words = {}
    for text, level_id, group_id in solution_words:
        if text not in unique_words:
            unique_words[text] = []
        unique_words[text].append((level_id, group_id))

    print(f"Unique solution words: {len(unique_words)}\n")
    print(f"Substring match threshold: {THRESHOLD:.0%}")
    print(f"Minimum substring length: {MIN_SUBSTR_LEN}")
    print(
        f"Ratio = longest_common_substring_len / max(len(solution), len(blocklist))\n"
    )

    # For each solution word, find the best match and all blocklist words that match
    # ratio = LCS_len / max(len(solution), len(blocklist))
    flagged = []

    for word in sorted(unique_words):
        best_ratio = 0
        matches = []
        for bw in blocklist:
            sm = SequenceMatcher(None, word, bw)
            match = sm.find_longest_match(0, len(word), 0, len(bw))
            if match.size < MIN_SUBSTR_LEN:
                continue
            denominator = max(len(word), len(bw))
            ratio = match.size / denominator
            if ratio >= THRESHOLD:
                substring = word[match.a : match.a + match.size]
                matches.append((bw, ratio, substring))
                if ratio > best_ratio:
                    best_ratio = ratio

        if matches:
            matches.sort(key=lambda x: (-x[1], x[0]))
            flagged.append((word, best_ratio, matches, unique_words[word]))

    flagged.sort(key=lambda x: (-x[1], x[0]))

    print("=" * 120)
    print(
        f"{'Solution Word':<22} {'Best%':>6}  {'Matching Blocklist Words (top per match substring)'}"
    )
    print("-" * 120)

    for word, best_ratio, matches, levels in flagged:
        level_str = ", ".join(lid for lid, _ in levels[:5])
        if len(levels) > 5:
            level_str += f" +{len(levels) - 5}"

        # Group matches by shared substring for clarity
        seen_substrings = set()
        top_matches = []
        for bw, ratio, substr in matches:
            if substr not in seen_substrings:
                seen_substrings.add(substr)
                top_matches.append(f"'{substr}' ← {bw} ({ratio:.0%})")
            if len(top_matches) >= 4:
                remaining = len(matches) - len(top_matches)
                if remaining > 0:
                    top_matches.append(f"... +{remaining} more")
                break

        match_str = " | ".join(top_matches)
        print(f"{word:<22} {best_ratio:>5.0%}   {match_str}")
        print(f"{'':22} {'':6}   Levels: {level_str}")
        print()

    print("=" * 120)
    print(
        f"\nTotal flagged solution words: {len(flagged)} out of {len(unique_words)} unique words"
    )


if __name__ == "__main__":
    main()

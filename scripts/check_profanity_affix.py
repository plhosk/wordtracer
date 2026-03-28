#!/usr/bin/env python3
"""Check solution words against blocklist by testing word + common affixes."""

import json
import glob
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "src", "data")
BLOCKLIST_PATH = os.path.join(
    SCRIPT_DIR, "..", "data", "raw", "blocklists", "words.json"
)

SUFFIXES = [
    "s",
    "es",
    "ed",
    "er",
    "ers",
    "ing",
    "ings",
    "est",
    "ly",
    "y",
    "ish",
    "ness",
    "ment",
    "ful",
    "less",
    "able",
    "tion",
    "ous",
    "ity",
    "ist",
]
PREFIXES = ["re", "un", "pre", "dis", "mis", "over", "out", "de", "anti", "co", "ex"]


def load_blocklist():
    with open(BLOCKLIST_PATH) as f:
        words = json.load(f)
    return set(w.lower().strip() for w in words if w.strip())


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
    print(f"Blocklist: {len(blocklist)} entries\n")

    solution_words = load_solution_words()
    print(f"Solution word entries: {len(solution_words)}\n")

    unique_words = {}
    for text, level_id, group_id in solution_words:
        if text not in unique_words:
            unique_words[text] = []
        unique_words[text].append((level_id, group_id))

    print(f"Unique solution words: {len(unique_words)}\n")

    flagged = []

    for word in sorted(unique_words):
        hits = []

        if word in blocklist:
            hits.append(("exact", word, word))

        # Direction 1: solution is the stem, blocklist has stem+affix
        for suf in SUFFIXES:
            formed = word + suf
            if formed in blocklist:
                hits.append((f"sol→bl +{suf}", word, formed))

        for pre in PREFIXES:
            formed = pre + word
            if formed in blocklist:
                hits.append((f"sol→bl {pre}+", word, formed))

        # Direction 2: solution has affix, blocklist has the stem
        for suf in SUFFIXES:
            if word.endswith(suf) and len(word) - len(suf) >= 3:
                stem = word[: -len(suf)]
                if stem in blocklist:
                    hits.append((f"bl→sol -{suf}", stem, word))
            if (
                suf in ("ed", "ing", "er", "y")
                and word.endswith(suf)
                and len(word) - len(suf) >= 3
            ):
                stem = word[: -len(suf)]
                if len(stem) >= 2 and stem[-1] == stem[-2]:
                    undoubled = stem[:-1]
                    if undoubled in blocklist:
                        hits.append((f"bl→sol -{stem[-1]}{suf}", undoubled, word))

        for pre in PREFIXES:
            if word.startswith(pre) and len(word) - len(pre) >= 3:
                stem = word[len(pre) :]
                if stem in blocklist:
                    hits.append((f"bl→sol {pre}-", stem, word))

        if hits:
            flagged.append((word, hits, unique_words[word]))

    flagged.sort(key=lambda x: x[0])

    print("=" * 120)
    print(
        f"{'Solution Word':<22} {'Match Type':<18} {'Blocklist Entry':<30} {'Levels'}"
    )
    print("-" * 120)

    for word, hits, levels in flagged:
        level_str = ", ".join(lid for lid, _ in levels[:5])
        if len(levels) > 5:
            level_str += f" +{len(levels) - 5}"
        for i, (match_type, base, blocklist_word) in enumerate(hits):
            lvl = level_str if i == 0 else ""
            print(
                f"{word if i == 0 else '':<22} {match_type:<18} {blocklist_word:<30} {lvl}"
            )
        print()

    print("=" * 120)
    print(
        f"\nTotal flagged: {len(flagged)} solution words with blocklist affix matches"
    )

    exact = sum(1 for _, hits, _ in flagged if any(h[0] == "exact" for h in hits))
    suffix_only = sum(
        1 for _, hits, _ in flagged if not any(h[0] == "exact" for h in hits)
    )
    stem_hits = sum(
        1
        for _, hits, _ in flagged
        if any(h[0].startswith("sol→bl") for h in hits)
        and not any(h[0].startswith("bl→sol") for h in hits)
        and not any(h[0] == "exact" for h in hits)
    )
    affix_hits = sum(
        1
        for _, hits, _ in flagged
        if any(h[0].startswith("bl→sol") for h in hits)
        and not any(h[0].startswith("sol→bl") for h in hits)
        and not any(h[0] == "exact" for h in hits)
    )
    both = sum(
        1
        for _, hits, _ in flagged
        if any(h[0].startswith("bl→sol") for h in hits)
        and any(h[0].startswith("sol→bl") for h in hits)
    )
    print(f"  Exact matches:               {exact}")
    print(f"  Solution is stem (sol→bl):   {stem_hits}")
    print(f"  Solution has affix (bl→sol): {affix_hits}")
    print(f"  Both directions:             {both}")


if __name__ == "__main__":
    main()

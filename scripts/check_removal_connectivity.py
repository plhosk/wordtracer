from __future__ import annotations

from pathlib import Path

from common import load_json, project_path

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


def load_all_levels() -> list[tuple[str, dict]]:
    results: list[tuple[str, dict]] = []
    for file_path in sorted(LEVELS_DIR.glob("levels.*.json")):
        suffix = file_path.stem.split(".", 1)[1]
        if suffix == "_meta":
            continue
        payload = load_json(file_path)
        for level in payload.get("levels", []):
            if isinstance(level, dict):
                level_id = str(level.get("id", ""))
                if level_id:
                    results.append((level_id, level))
    return results


def get_word_cells(level: dict) -> dict[str, set[tuple[int, int]]]:
    result: dict[str, set[tuple[int, int]]] = {}
    for answer in level.get("answers", []):
        if not isinstance(answer, dict):
            continue
        text = str(answer.get("text", "")).strip().lower()
        if not text:
            continue
        cells: set[tuple[int, int]] = set()
        for point in answer.get("path", []):
            if isinstance(point, (list, tuple)) and len(point) == 2:
                cells.add((int(point[0]), int(point[1])))
        if cells:
            result.setdefault(text, set()).update(cells)
    return result


def are_connected_after_removal(
    word_cells: dict[str, set[tuple[int, int]]],
    remove_word: str,
) -> tuple[bool, list[list[str]]]:
    remaining = {w: cells for w, cells in word_cells.items() if w != remove_word}
    if len(remaining) <= 1:
        return True, [list(remaining.keys())]

    words = list(remaining.keys())
    n = len(words)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if remaining[words[i]] & remaining[words[j]]:
                union(i, j)

    roots: dict[int, list[str]] = {}
    for i, w in enumerate(words):
        roots.setdefault(find(i), []).append(w)

    components = list(roots.values())
    return len(components) == 1, components


def main() -> None:
    problematic = load_problematic_words(PROBLEMATIC_TXT)
    print(f"Loaded {len(problematic)} problematic words from {PROBLEMATIC_TXT}")

    all_levels = load_all_levels()
    print(f"Loaded {len(all_levels)} levels from {LEVELS_DIR}")
    print()

    results: list[dict] = []

    for level_id, level in all_levels:
        word_cells = get_word_cells(level)
        hits = problematic & word_cells.keys()
        for word in sorted(hits):
            total_words = len(word_cells)
            connected, components = are_connected_after_removal(word_cells, word)
            results.append(
                {
                    "word": word,
                    "level": level_id,
                    "status": "SAFE" if connected else "DISCONNECTED",
                    "components": components if not connected else None,
                    "word_count": total_words,
                }
            )

    disconnected = [r for r in results if r["status"] == "DISCONNECTED"]
    safe = [r for r in results if r["status"] == "SAFE"]

    print("=" * 80)
    print("REMOVAL CONNECTIVITY ANALYSIS")
    print("=" * 80)
    print()
    print(f"Total occurrences checked: {len(results)}")
    print(f"  SAFE (removal keeps connectivity): {len(safe)}")
    print(f"  DISCONNECTED (removal splits graph): {len(disconnected)}")
    print()

    if disconnected:
        print("-" * 80)
        print("DISCONNECTED - removing the word splits the level into components:")
        print("-" * 80)
        for r in sorted(
            disconnected,
            key=lambda x: (
                -(x["word_count"] - 1 - max(len(c) for c in x["components"])),
                x["level"],
                x["word"],
            ),
        ):
            disconnected_count = (
                r["word_count"] - 1 - max(len(c) for c in r["components"])
            )
            comps_desc = []
            for comp in r["components"]:
                comps_desc.append("[" + ", ".join(comp) + "]")
            print(
                f"  {r['level']:>5}  word='{r['word']}'  "
                f"disconnected_words={disconnected_count}  "
                f"components={' | '.join(comps_desc)}"
            )
        print()

    if safe:
        print("-" * 80)
        print("SAFE - removing the word does NOT break connectivity:")
        print("-" * 80)
        for r in sorted(safe, key=lambda x: (x["level"], x["word"])):
            print(
                f"  {r['level']:>5}  word='{r['word']}'  "
                f"remaining_words={r['word_count'] - 1}"
            )
        print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if disconnected:
        print()
        print(
            "The following occurrences CANNOT be removed without disconnecting other words:"
        )
        level_words: dict[str, list[str]] = {}
        for r in disconnected:
            level_words.setdefault(r["level"], []).append(r["word"])
        for level, words in sorted(level_words.items()):
            print(f"  {level}: {', '.join(sorted(words))}")
    else:
        print(
            "All problematic word occurrences can be safely removed without disconnection."
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

from common import load_json, project_path, save_json

LEVELS_DIR = project_path("src", "data")
LEXICON_PATH = project_path("data", "processed", "lexicon.json")
BONUS_LEXICON_PATH = project_path("data", "processed", "lexicon_bonus.json")
WORDNET_DICTIONARY_PATH = project_path("data", "processed", "wordnet_dictionary.json")
PROBLEMATIC_TXT = project_path("plans", "problematic.txt")


def load_problematic_words() -> set[str]:
    words: set[str] = set()
    with PROBLEMATIC_TXT.open("r", encoding="utf-8") as f:
        for line in f:
            token = line.strip().lower()
            if token:
                words.add(token)
    return words


def load_lexicon_set(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    return {w["word"] for w in words if isinstance(w, dict) and w.get("word")}


def load_freq_map(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    return {
        w["word"]: w.get("freq", 0.0)
        for w in words
        if isinstance(w, dict) and w.get("word")
    }


def normalize_lexicon_word(raw: str) -> str | None:
    word = raw.strip().lower()
    if not word:
        return None
    if not word.isascii() or not word.isalpha():
        return None
    if len(word) < 3 or len(word) > 12:
        return None
    return word


def load_extra_lexicon(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as f:
        data: Any = json.load(f)

    out: set[str] = set()

    if isinstance(data, dict) and isinstance(data.get("words"), list):
        for entry in data["words"]:
            if not isinstance(entry, dict):
                continue
            word = entry.get("word")
            if not isinstance(word, str):
                continue
            normalized = normalize_lexicon_word(word)
            if normalized is not None:
                out.add(normalized)
        return out

    if isinstance(data, dict):
        for key in data.keys():
            if not isinstance(key, str):
                continue
            normalized = normalize_lexicon_word(key)
            if normalized is not None:
                out.add(normalized)
        return out

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, str):
                continue
            normalized = normalize_lexicon_word(item)
            if normalized is not None:
                out.add(normalized)
        return out

    raise ValueError(f"Unsupported lexicon JSON format: {path}")


def load_wordfreq_lexicon(
    top_n: int,
    min_zipf: float,
    min_len: int = 3,
    max_len: int = 12,
) -> tuple[set[str], dict[str, float]]:
    from wordfreq import top_n_list, zipf_frequency

    words: set[str] = set()
    freq_map: dict[str, float] = {}

    for raw in top_n_list("en", top_n):
        if not isinstance(raw, str):
            continue
        word = raw.strip().lower()
        if not word.isascii() or not word.isalpha():
            continue
        if len(word) < min_len or len(word) > max_len:
            continue
        freq = float(zipf_frequency(word, "en"))
        if freq < min_zipf:
            continue
        words.add(word)
        freq_map[word] = freq

    return words, freq_map


def wheel_letter_pool(wheel_tokens: list[str]) -> Counter[str]:
    pool: Counter[str] = Counter()
    for token in wheel_tokens:
        pool.update(token)
    return pool


def token_text(token: str, mode: str) -> str:
    if mode == "reverse" and len(token) >= 2:
        return token[::-1]
    return token


def wheel_candidate_words_for_mode(
    lexicon: set[str],
    wheel_tokens: list[str],
    mode: str,
    min_len: int = 3,
    max_len: int = 12,
) -> set[str]:
    found: set[str] = set()

    def walk(current: str, used_mask: int) -> None:
        if len(current) >= min_len and current in lexicon:
            found.add(current)
        if len(current) >= max_len:
            return

        for idx, token in enumerate(wheel_tokens):
            if used_mask & (1 << idx):
                continue
            nxt = current + token_text(token, mode)
            if len(nxt) > max_len:
                continue
            walk(nxt, used_mask | (1 << idx))

    walk("", 0)
    return found


def words_from_wheel(
    lexicon: set[str], wheel_tokens: list[str], min_len: int = 3, max_len: int = 12
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for mode in ("forward", "reverse"):
        words = wheel_candidate_words_for_mode(
            lexicon,
            wheel_tokens,
            mode,
            min_len=min_len,
            max_len=max_len,
        )
        for word in words:
            result.setdefault(word, set()).add(mode)
    return result


def get_answer_word_cells(level: dict) -> dict[str, list[tuple[int, int]]]:
    result: dict[str, list[tuple[int, int]]] = {}
    for answer in level.get("answers", []):
        if not isinstance(answer, dict):
            continue
        text = str(answer.get("text", "")).strip().lower()
        path = answer.get("path", [])
        cells = [(int(p[0]), int(p[1])) for p in path]
        if text and cells:
            result[text] = cells
    return result


def find_components(word_cells: dict[str, set[tuple[int, int]]]) -> list[list[str]]:
    words = list(word_cells.keys())
    if not words:
        return []
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
            if word_cells[words[i]] & word_cells[words[j]]:
                union(i, j)

    roots: dict[int, list[str]] = {}
    for i, w in enumerate(words):
        roots.setdefault(find(i), []).append(w)
    return list(roots.values())


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


def component_index_by_cell(
    components: list[list[str]], word_cells: dict[str, list[tuple[int, int]]]
) -> dict[tuple[int, int], int]:
    index: dict[tuple[int, int], int] = {}
    for comp_idx, component in enumerate(components):
        for word in component:
            for cell in word_cells[word]:
                index[cell] = comp_idx
    return index


def straight_line_paths(
    rows: int, cols: int, length: int
) -> list[list[tuple[int, int]]]:
    paths: list[list[tuple[int, int]]] = []
    if length > rows and length > cols:
        return paths
    for r in range(rows):
        for c in range(cols - length + 1):
            paths.append([(r, c + i) for i in range(length)])
    for r in range(rows - length + 1):
        for c in range(cols):
            paths.append([(r + i, c) for i in range(length)])
    return paths


def grid_letters(
    word_cells: dict[str, list[tuple[int, int]]],
) -> dict[tuple[int, int], str]:
    letters: dict[tuple[int, int], str] = {}
    for word, cells in word_cells.items():
        for i, (r, c) in enumerate(cells):
            if (r, c) not in letters:
                letters[(r, c)] = word[i]
    return letters


def find_bridging_placements(
    level: dict,
    word_cells: dict[str, list[tuple[int, int]]],
    components: list[list[str]],
    candidate_words: set[str],
    candidate_word_modes: dict[str, set[str]] | None,
    existing_words: set[str],
    freq_map: dict[str, float],
    excluded_words: set[str],
) -> list[dict]:
    rows = int(level.get("rows", 0))
    cols = int(level.get("cols", 0))
    letters = grid_letters(word_cells)
    comp_by_cell = component_index_by_cell(components, word_cells)

    max_word_len = rows if rows >= cols else cols

    placements: list[dict] = []

    for word in sorted(candidate_words):
        if word in existing_words or word in excluded_words:
            continue
        wlen = len(word)
        if wlen > max_word_len:
            continue

        for path in straight_line_paths(rows, cols, wlen):
            touched_components: set[int] = set()
            overlap_count = 0
            letter_map: dict[tuple[int, int], str] = {}
            all_match = True

            for i, (r, c) in enumerate(path):
                cell = (r, c)
                letter_map[cell] = word[i]
                existing_letter = letters.get(cell)
                if existing_letter is not None:
                    if existing_letter != word[i]:
                        all_match = False
                        break
                    overlap_count += 1
                    comp_idx = comp_by_cell.get(cell)
                    if comp_idx is not None:
                        touched_components.add(comp_idx)

            if not all_match:
                continue
            if len(touched_components) < 2:
                continue

            comp_mask = 0
            for comp_idx in touched_components:
                comp_mask |= 1 << comp_idx

            freq = freq_map.get(word, 0.0)
            score = overlap_count * 100 + len(word) * 10 + freq * 5
            placements.append(
                {
                    "word": word,
                    "allowed_modes": sorted(
                        candidate_word_modes.get(word, {"forward"})
                        if candidate_word_modes is not None
                        else {"forward"},
                        key=lambda item: (item != "forward", item),
                    ),
                    "path": path,
                    "path_set": set(path),
                    "letter_map": letter_map,
                    "component_ids": touched_components,
                    "component_mask": comp_mask,
                    "overlap_count": overlap_count,
                    "freq": freq,
                    "score": score,
                    "path_str": " -> ".join(
                        f"({r},{c})={word[i]}" for i, (r, c) in enumerate(path)
                    ),
                }
            )

    placements.sort(key=lambda p: p["score"], reverse=True)
    return placements


def placements_compatible(a: dict, b: dict) -> bool:
    if a["word"] == b["word"]:
        return False
    common_cells = a["path_set"] & b["path_set"]
    for cell in common_cells:
        if a["letter_map"][cell] != b["letter_map"][cell]:
            return False
    return True


def components_connected_by_placements(
    component_count: int, placements: list[dict]
) -> bool:
    if component_count <= 1:
        return True

    parent = list(range(component_count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for placement in placements:
        component_ids = sorted(placement["component_ids"])
        base = component_ids[0]
        for comp_idx in component_ids[1:]:
            union(base, comp_idx)

    root = find(0)
    for comp_idx in range(1, component_count):
        if find(comp_idx) != root:
            return False
    return True


def build_solution(indices: tuple[int, ...], placements: list[dict]) -> dict:
    chosen = [placements[idx] for idx in indices]
    words = [p["word"] for p in chosen]
    total_score = sum(p["score"] for p in chosen)
    total_overlap = sum(p["overlap_count"] for p in chosen)
    total_freq = sum(p["freq"] for p in chosen)
    return {
        "words": words,
        "placements": chosen,
        "num_words": len(chosen),
        "score": total_score,
        "total_overlap": total_overlap,
        "total_freq": total_freq,
        "path_str": " | ".join(f"{p['word']}: {p['path_str']}" for p in chosen),
    }


def find_bridging_word_sets(
    level: dict,
    word_cells: dict[str, list[tuple[int, int]]],
    components: list[list[str]],
    candidate_words: set[str],
    candidate_word_modes: dict[str, set[str]] | None,
    existing_words: set[str],
    freq_map: dict[str, float],
    excluded_words: set[str],
    max_words: int = 3,
) -> list[dict]:
    placements = find_bridging_placements(
        level,
        word_cells,
        components,
        candidate_words,
        candidate_word_modes,
        existing_words,
        freq_map,
        excluded_words,
    )

    if not placements:
        return []

    component_count = len(components)
    compatible: dict[tuple[int, int], bool] = {}

    def is_compatible(i: int, j: int) -> bool:
        key = (i, j) if i < j else (j, i)
        if key not in compatible:
            compatible[key] = placements_compatible(
                placements[key[0]], placements[key[1]]
            )
        return compatible[key]

    solutions: list[dict] = []

    for i in range(len(placements)):
        if components_connected_by_placements(component_count, [placements[i]]):
            solutions.append(build_solution((i,), placements))

    if max_words >= 2:
        for i, j in combinations(range(len(placements)), 2):
            if not is_compatible(i, j):
                continue
            if not components_connected_by_placements(
                component_count, [placements[i], placements[j]]
            ):
                continue
            solutions.append(build_solution((i, j), placements))

    if max_words >= 3:
        for i, j, k in combinations(range(len(placements)), 3):
            if not is_compatible(i, j):
                continue
            if not is_compatible(i, k):
                continue
            if not is_compatible(j, k):
                continue
            if not components_connected_by_placements(
                component_count, [placements[i], placements[j], placements[k]]
            ):
                continue
            solutions.append(build_solution((i, j, k), placements))

    solutions.sort(
        key=lambda s: (
            s["num_words"],
            -s["score"],
            -s["total_overlap"],
            -s["total_freq"],
        )
    )
    return solutions


def apply_solution_to_level(level: dict, best: dict) -> tuple[dict, int]:
    rows = int(level.get("rows", 0))
    cols = int(level.get("cols", 0))

    answers = [a for a in level.get("answers", []) if isinstance(a, dict)]
    bonus_words = [w for w in level.get("bonusWords", []) if isinstance(w, str)]
    selected_words = {w.lower() for w in best["words"]}

    appended_answers = [
        {
            "text": placement["word"],
            "path": [[r, c] for r, c in placement["path"]],
            "allowedModes": placement.get("allowed_modes", ["forward"]),
        }
        for placement in best["placements"]
    ]

    filtered_bonus = [w for w in bonus_words if w.lower() not in selected_words]
    bonus_removed = len(bonus_words) - len(filtered_bonus)

    all_answers = answers + appended_answers
    all_paths = [answer_path_tuples(a) for a in all_answers]
    h, v = derive_walls_from_paths(rows, cols, all_paths)
    new_walls = derive_walls_sparse(rows, cols, all_paths, h, v)

    modified = dict(level)
    modified["answers"] = all_answers
    modified["bonusWords"] = filtered_bonus
    modified["walls"] = new_walls
    return modified, bonus_removed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and optionally apply bridge words for disconnected levels."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write selected bridging words into level data files.",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=3,
        help="Maximum bridge words per level (1-3, default: 3).",
    )
    parser.add_argument(
        "--include-wordnet-dictionary",
        action="store_true",
        help=(
            "Include data/processed/wordnet_dictionary.json as an extra, "
            "less-common bridge lexicon source."
        ),
    )
    parser.add_argument(
        "--extra-lexicon",
        action="append",
        default=[],
        help=(
            "Additional JSON lexicon path(s). Supports lexicon format "
            "({'words':[{'word':...}]}) or dictionary-key format ({word: definition})."
        ),
    )
    parser.add_argument(
        "--expansive-wordfreq",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After normal search, retry unresolved levels using a larger wordfreq-based "
            "candidate set. Enabled by default."
        ),
    )
    parser.add_argument(
        "--expansive-wordfreq-top-n",
        type=int,
        default=400000,
        help="wordfreq top-N vocabulary size for expansive fallback (default: 400000).",
    )
    parser.add_argument(
        "--expansive-wordfreq-min-zipf",
        type=float,
        default=2.5,
        help="Minimum wordfreq Zipf for expansive fallback candidates (default: 2.5).",
    )
    args = parser.parse_args()

    max_words = max(1, min(3, int(args.max_words)))

    main_lexicon = load_lexicon_set(LEXICON_PATH)
    bonus_lexicon = load_lexicon_set(BONUS_LEXICON_PATH)
    combined_lexicon = main_lexicon | bonus_lexicon

    extra_sources: list[Path] = []
    if args.include_wordnet_dictionary:
        extra_sources.append(WORDNET_DICTIONARY_PATH)
    for raw in args.extra_lexicon:
        extra_sources.append(Path(raw))

    extra_total = 0
    for source in extra_sources:
        words = load_extra_lexicon(source)
        combined_lexicon |= words
        extra_total += len(words)

    freq_map = load_freq_map(LEXICON_PATH)
    expansive_lexicon: set[str] = set(combined_lexicon)
    expansive_freq_map: dict[str, float] = dict(freq_map)

    wordfreq_added = 0
    if args.expansive_wordfreq:
        try:
            wf_words, wf_freq_map = load_wordfreq_lexicon(
                top_n=max(1, int(args.expansive_wordfreq_top_n)),
                min_zipf=float(args.expansive_wordfreq_min_zipf),
                min_len=3,
                max_len=12,
            )
        except ImportError:
            wf_words, wf_freq_map = set(), {}
            print(
                "warning: wordfreq dependency missing; expansive fallback disabled for this run"
            )
        if wf_words:
            expansive_lexicon |= wf_words
            wordfreq_added = len(wf_words)
            for word, wf_freq in wf_freq_map.items():
                expansive_freq_map[word] = max(
                    expansive_freq_map.get(word, 0.0), wf_freq
                )

    excluded_words = load_problematic_words()
    print(
        f"Lexicon: {len(main_lexicon)} + {len(bonus_lexicon)} bonus = {len(combined_lexicon)} total"
    )
    if extra_sources:
        print(
            f"Extra lexicon sources: {len(extra_sources)} files, {extra_total} words merged"
        )
    if args.expansive_wordfreq:
        print(
            "Expansive fallback: "
            f"wordfreq top_n={args.expansive_wordfreq_top_n}, "
            f"min_zipf={args.expansive_wordfreq_min_zipf}, "
            f"added_words={wordfreq_added}, "
            f"expanded_total={len(expansive_lexicon)}"
        )
    print(f"Excluded (problematic): {len(excluded_words)} words")

    group_files = sorted(
        f for f in LEVELS_DIR.glob("levels.*.json") if f.stem != "levels._meta"
    )

    total_disconnected = 0
    total_fixable = 0
    total_applied = 0
    total_words_added = 0
    total_bonus_removed = 0
    selections: list[dict] = []

    for group_file in group_files:
        payload = load_json(group_file)
        levels = payload.get("levels", [])
        if not isinstance(levels, list):
            continue

        modified_levels: list = []
        group_modified = False

        for level in levels:
            if not isinstance(level, dict):
                modified_levels.append(level)
                continue

            word_cells = get_answer_word_cells(level)
            cell_sets = {w: set(cells) for w, cells in word_cells.items()}
            components = find_components(cell_sets)

            if len(components) <= 1:
                modified_levels.append(level)
                continue

            level_id = level.get("id", "?")
            total_disconnected += 1

            wheel_tokens = level.get("letterWheel", [])
            candidate_word_modes = words_from_wheel(combined_lexicon, wheel_tokens)
            candidate_words = set(candidate_word_modes.keys())
            existing_words = set(word_cells.keys())

            comp_desc = []
            for comp in sorted(components, key=len, reverse=True):
                comp_desc.append("[" + ", ".join(comp) + "]")

            solutions = find_bridging_word_sets(
                level,
                word_cells,
                components,
                candidate_words,
                candidate_word_modes,
                existing_words,
                freq_map,
                excluded_words,
                max_words=max_words,
            )
            solution_source = "base"

            if not solutions and args.expansive_wordfreq:
                expansive_modes = words_from_wheel(expansive_lexicon, wheel_tokens)
                expansive_words = set(expansive_modes.keys())
                solutions = find_bridging_word_sets(
                    level,
                    word_cells,
                    components,
                    expansive_words,
                    expansive_modes,
                    existing_words,
                    expansive_freq_map,
                    excluded_words,
                    max_words=max_words,
                )
                if solutions:
                    solution_source = "wordfreq"

            level_bonus_words = {
                str(w).strip().lower()
                for w in level.get("bonusWords", [])
                if isinstance(w, str)
            }

            if solutions:
                total_fixable += 1
                best = solutions[0]
                promoted_from_bonus = [
                    w for w in best["words"] if w in level_bonus_words
                ]

                if args.apply:
                    updated_level, bonus_removed = apply_solution_to_level(level, best)
                    modified_levels.append(updated_level)
                    group_modified = True
                    total_applied += 1
                    total_words_added += best["num_words"]
                    total_bonus_removed += bonus_removed
                else:
                    modified_levels.append(level)

                selections.append(
                    {
                        "level_id": level_id,
                        "best": best,
                        "num_solutions": len(solutions),
                        "bonus_promotions": promoted_from_bonus,
                    }
                )
                print(
                    f"  {level_id:>5}  bridge='{' + '.join(best['words'])}'  "
                    f"source={solution_source}  "
                    f"words={best['num_words']}  "
                    f"freq={best['total_freq']:.2f}  "
                    f"overlap={best['total_overlap']}  "
                    f"bonus_rm={len(promoted_from_bonus)}  "
                    f"candidates={len(solutions)}  "
                    f"{best['path_str']}"
                )
            else:
                print(
                    f"  {level_id:>5}  NO BRIDGE FOUND  components: {' | '.join(comp_desc)}"
                )
                modified_levels.append(level)

        if args.apply and group_modified:
            payload["levels"] = modified_levels
            save_json(group_file, payload)

    print()
    print("=" * 80)
    print(f"Disconnected levels: {total_disconnected}")
    print(f"Fixable with bridging: {total_fixable}")
    print(f"Not fixable: {total_disconnected - total_fixable}")
    if args.apply:
        print(f"Applied fixes: {total_applied}")
        print(f"Words added to answers: {total_words_added}")
        print(f"Bonus words removed: {total_bonus_removed}")
    print()
    print("SELECTED BRIDGING WORDS:")
    print(
        f"{'Level':>6}  {'Words':>3}  {'Bridge':>24}  {'Freq':>6}  {'Overlap':>7}  {'BonusRm':>7}"
    )
    print("-" * 74)
    for sel in selections:
        b = sel["best"]
        print(
            f"{sel['level_id']:>6}  {b['num_words']:>3}  {' + '.join(b['words']):>24}  "
            f"{b['total_freq']:>6.2f}  {b['total_overlap']:>7}  {len(sel['bonus_promotions']):>7}"
        )


if __name__ == "__main__":
    main()

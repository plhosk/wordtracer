from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bridge_disconnected import (
    apply_solution_to_level,
    find_bridging_word_sets,
    find_components,
    load_extra_lexicon,
    words_from_wheel,
)


class BridgeDisconnectedTests(unittest.TestCase):
    def test_two_word_chain_connects_three_components(self) -> None:
        level = {"rows": 3, "cols": 8}
        word_cells = {
            "ab": [(1, 0), (1, 1)],
            "cd": [(1, 3), (1, 4)],
            "ef": [(1, 6), (1, 7)],
        }
        components = find_components({w: set(cells) for w, cells in word_cells.items()})

        solutions = find_bridging_word_sets(
            level=level,
            word_cells=word_cells,
            components=components,
            candidate_words={"bxc", "dye"},
            candidate_word_modes=None,
            existing_words=set(word_cells.keys()),
            freq_map={"bxc": 1.0, "dye": 1.0},
            excluded_words=set(),
            max_words=3,
        )

        self.assertTrue(solutions)
        self.assertEqual(solutions[0]["num_words"], 2)
        self.assertEqual(set(solutions[0]["words"]), {"bxc", "dye"})
        self.assertFalse(any(solution["num_words"] == 1 for solution in solutions))

    def test_prefers_single_word_solution_when_available(self) -> None:
        level = {"rows": 3, "cols": 4}
        word_cells = {
            "ab": [(0, 1), (0, 2)],
            "cd": [(2, 1), (2, 2)],
        }
        components = find_components({w: set(cells) for w, cells in word_cells.items()})

        solutions = find_bridging_word_sets(
            level=level,
            word_cells=word_cells,
            components=components,
            candidate_words={"axc", "byd"},
            candidate_word_modes=None,
            existing_words=set(word_cells.keys()),
            freq_map={"axc": 1.0, "byd": 5.0},
            excluded_words=set(),
            max_words=3,
        )

        self.assertTrue(solutions)
        self.assertEqual(solutions[0]["num_words"], 1)
        self.assertTrue(any(solution["num_words"] == 2 for solution in solutions))

    def test_apply_removes_promoted_bonus_word(self) -> None:
        level = {
            "rows": 3,
            "cols": 5,
            "bonusWords": ["apes", "other"],
            "answers": [
                {
                    "text": "apt",
                    "path": [[0, 0], [0, 1], [0, 2]],
                    "allowedModes": ["forward"],
                },
                {
                    "text": "sue",
                    "path": [[2, 2], [2, 3], [2, 4]],
                    "allowedModes": ["forward"],
                },
            ],
        }
        best = {
            "words": ["apes"],
            "placements": [
                {
                    "word": "apes",
                    "path": [(0, 1), (1, 1), (2, 1), (2, 2)],
                }
            ],
        }

        updated, bonus_removed = apply_solution_to_level(level, best)

        self.assertEqual(bonus_removed, 1)
        self.assertEqual(updated["bonusWords"], ["other"])
        self.assertEqual(len(updated["answers"]), 3)
        self.assertEqual(updated["answers"][-1]["text"], "apes")
        self.assertEqual(updated["answers"][-1]["allowedModes"], ["forward"])
        self.assertIn("0,1", updated["walls"])
        self.assertIn("2,2", updated["walls"])

    def test_words_from_wheel_respects_token_boundaries(self) -> None:
        wheel_tokens = ["us", "og", "a", "le", "d", "e", "b"]
        modes = words_from_wheel(
            {"seal", "adobe", "usable", "useable"},
            wheel_tokens,
            min_len=3,
            max_len=12,
        )

        self.assertNotIn("seal", modes)
        self.assertNotIn("adobe", modes)
        self.assertIn("usable", modes)
        self.assertIn("useable", modes)

    def test_load_extra_lexicon_accepts_dictionary_key_format(self) -> None:
        payload = {
            "dea": "definition",
            "GPA": "definition",
            "aard-vark": "bad",
            "xx": "too short",
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "extra.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            words = load_extra_lexicon(path)

        self.assertIn("dea", words)
        self.assertIn("gpa", words)
        self.assertNotIn("aard-vark", words)
        self.assertNotIn("xx", words)


if __name__ == "__main__":
    unittest.main()

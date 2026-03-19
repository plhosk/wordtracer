from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

WORD_RE = re.compile(r"^[a-z]+$")
REPEATED_TRIPLE_RE = re.compile(r"(.)\1\1")
DEFAULT_COMBO_SIZES: tuple[int, ...] = (1, 2)

FALLBACK_WORDS = [
    "able",
    "about",
    "above",
    "actor",
    "after",
    "again",
    "agent",
    "agree",
    "ahead",
    "album",
    "alert",
    "alien",
    "alone",
    "among",
    "angle",
    "apple",
    "arena",
    "argue",
    "arise",
    "audio",
    "avoid",
    "award",
    "basic",
    "beach",
    "begin",
    "below",
    "birth",
    "black",
    "block",
    "board",
    "brain",
    "brand",
    "break",
    "brown",
    "build",
    "cable",
    "carry",
    "cause",
    "chain",
    "chair",
    "chase",
    "check",
    "chest",
    "chief",
    "choice",
    "civil",
    "class",
    "clean",
    "clear",
    "clock",
    "close",
    "cloud",
    "coach",
    "coast",
    "color",
    "count",
    "craft",
    "dance",
    "dream",
    "earth",
    "event",
    "every",
    "faith",
    "field",
    "final",
    "flame",
    "focus",
    "frame",
    "fresh",
    "front",
    "giant",
    "globe",
    "grace",
    "grand",
    "green",
    "group",
    "guard",
    "guide",
    "happy",
    "heart",
    "house",
    "human",
    "image",
    "joint",
    "light",
    "lunch",
    "major",
    "metal",
    "model",
    "music",
    "ocean",
    "panel",
    "paper",
    "peace",
    "phase",
    "place",
    "plane",
    "plant",
    "point",
    "power",
    "press",
    "price",
    "prime",
    "print",
    "queen",
    "quick",
    "quiet",
    "radio",
    "range",
    "rapid",
    "river",
    "route",
    "scale",
    "score",
    "shape",
    "share",
    "shift",
    "shore",
    "skill",
    "sleep",
    "small",
    "smart",
    "smile",
    "solid",
    "sound",
    "space",
    "spare",
    "speak",
    "spice",
    "sport",
    "stack",
    "stage",
    "start",
    "state",
    "stone",
    "storm",
    "story",
    "style",
    "sugar",
    "table",
    "teach",
    "theme",
    "there",
    "thick",
    "thing",
    "touch",
    "track",
    "trade",
    "train",
    "trust",
    "truth",
    "under",
    "union",
    "value",
    "video",
    "voice",
    "watch",
    "water",
    "white",
    "world",
    "youth",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def project_path(*parts: str) -> Path:
    return repo_root().joinpath(*parts)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def normalize_word(raw: str) -> str | None:
    word = raw.strip().lower()
    if not word or not word.isascii() or not WORD_RE.fullmatch(word):
        return None
    return word


def parse_word_line(line: str) -> tuple[str, float | None] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split()
    word = normalize_word(parts[0])
    if word is None:
        return None
    if len(parts) == 1:
        return word, None
    try:
        return word, float(parts[1])
    except ValueError:
        return word, None


def read_word_file(path: Path) -> list[tuple[str, float | None]]:
    rows: list[tuple[str, float | None]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            parsed = parse_word_line(line)
            if parsed is not None:
                rows.append(parsed)
    return rows


def fallback_words(limit: int) -> list[tuple[str, float]]:
    limited = FALLBACK_WORDS[: max(1, min(limit, len(FALLBACK_WORDS)))]
    # Rough decreasing zipf-like scale for local development.
    return [(word, round(6.0 - (idx * 0.01), 4)) for idx, word in enumerate(limited)]


def read_blocklist(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()

    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError(f"expected JSON array in blocklist file: {path}")

        words: set[str] = set()
        for entry in payload:
            if not isinstance(entry, str):
                continue
            # Normalize: lowercase, strip spaces/hyphens
            normalized = entry.lower().strip()
            # Only add if it's pure a-z (skip leetspeak like "ar5e" which would compact to real words)
            if normalized and all("a" <= ch <= "z" or ch in " -" for ch in normalized):
                compact = "".join(ch for ch in normalized if "a" <= ch <= "z")
                if compact:
                    words.add(compact)
        return words

    words: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            word = normalize_word(line)
            if word:
                words.add(word)
    return words


def keep_word_shape(word: str) -> bool:
    if REPEATED_TRIPLE_RE.search(word):
        return False
    counts = Counter(word)
    if counts.most_common(1)[0][1] >= max(4, len(word) - 1):
        return False
    return True


def parse_combo_sizes(raw: str) -> tuple[int, ...]:
    sizes: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        value = int(token)
        if value <= 0:
            raise ValueError(f"combo sizes must be positive: {raw}")
        sizes.append(value)
    if not sizes:
        raise ValueError(f"no combo sizes provided: {raw}")
    return tuple(sorted(set(sizes)))


def generate_combos(word: str, sizes: Iterable[int] | None = None) -> list[str]:
    combo_sizes = tuple(
        sorted({size for size in (sizes or DEFAULT_COMBO_SIZES) if size > 0})
    )
    if not combo_sizes:
        return []

    seen: set[str] = set()
    out: list[str] = []
    for size in combo_sizes:
        for idx in range(len(word) - size + 1):
            combo = word[idx : idx + size]
            if combo not in seen:
                out.append(combo)
                seen.add(combo)
    return out


def can_build_from_letters(word: str, letters: Iterable[str] | Counter) -> bool:
    if isinstance(letters, Counter):
        pool = letters.copy()
    else:
        pool = Counter(letters)
    need = Counter(word)
    for char, amount in need.items():
        if pool[char] < amount:
            return False
    return True


def build_trie(words: Iterable[str]) -> dict:
    root: dict = {}
    for word in words:
        node = root
        for char in word:
            node = node.setdefault(char, {})
        node["$"] = word
    return root

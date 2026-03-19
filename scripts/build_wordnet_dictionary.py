from __future__ import annotations

import argparse
from pathlib import Path

from common import normalize_word, project_path, save_json


POS_PRIORITY = {
    "n": 0,
    "v": 1,
    "a": 2,
    "s": 3,
    "r": 4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build flattened WordNet dictionary for fallback definitions."
    )
    parser.add_argument(
        "--source",
        default=str(project_path("data", "raw", "wordnet", "wordnet.json")),
        help="Path to WordNet JSON source.",
    )
    parser.add_argument(
        "--out",
        default=str(project_path("data", "processed", "wordnet_dictionary.json")),
        help="Output path for flattened word->definition map.",
    )
    parser.add_argument(
        "--stats-out",
        default=str(project_path("data", "processed", "wordnet_dictionary_stats.json")),
        help="Output path for dictionary build stats.",
    )
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_path(*path.parts)


def ranked_id_to_synset_key(ranked_id: str) -> str | None:
    parts = ranked_id.split(".", 1)
    if len(parts) != 2:
        return None
    pos, offset = parts
    if not offset.isdigit() or not pos:
        return None
    return f"{pos}{int(offset)}"


def clean_gloss(raw: str) -> str:
    return " ".join(raw.split())


def main() -> None:
    args = parse_args()
    source_path = resolve_path(args.source)
    if not source_path.exists() or not source_path.is_file():
        raise SystemExit(f"WordNet source not found: {source_path}")

    import json

    with source_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    synsets = payload.get("synset")
    lemma_ranked = payload.get("lemmaRanked")
    lemma_plain = payload.get("lemma")
    if not isinstance(synsets, dict) or not isinstance(lemma_ranked, dict):
        raise SystemExit(
            "Invalid WordNet JSON: expected 'synset' and 'lemmaRanked' maps"
        )
    if not isinstance(lemma_plain, dict):
        lemma_plain = {}

    definitions: dict[str, str] = {}
    definition_scores: dict[str, tuple[int, int, int]] = {}
    kept_from_ranked = 0
    kept_from_lemma_fallback = 0
    dropped_bad_lemma = 0
    dropped_no_gloss = 0
    duplicate_replaced = 0
    duplicate_skipped = 0

    for lemma_key, ranked_synsets in lemma_ranked.items():
        if "." not in lemma_key:
            dropped_bad_lemma += 1
            continue

        pos, lemma_text = lemma_key.split(".", 1)
        normalized = normalize_word(lemma_text)
        if normalized is None:
            dropped_bad_lemma += 1
            continue

        gloss = ""
        rank_index = 0
        source_rank = 0

        if isinstance(ranked_synsets, list):
            for idx, ranked_id in enumerate(ranked_synsets):
                synset_key = ranked_id_to_synset_key(str(ranked_id))
                if synset_key is None:
                    continue
                synset = synsets.get(synset_key)
                if not isinstance(synset, dict):
                    continue
                candidate = clean_gloss(str(synset.get("gloss", "")).strip())
                if candidate:
                    gloss = candidate
                    rank_index = idx
                    break

        if not gloss:
            fallback_synsets = lemma_plain.get(lemma_key, [])
            if isinstance(fallback_synsets, list):
                for idx, synset_key in enumerate(fallback_synsets):
                    synset = synsets.get(str(synset_key))
                    if not isinstance(synset, dict):
                        continue
                    candidate = clean_gloss(str(synset.get("gloss", "")).strip())
                    if candidate:
                        gloss = candidate
                        rank_index = idx
                        source_rank = 1
                        break

        if not gloss:
            dropped_no_gloss += 1
            continue

        score = (POS_PRIORITY.get(pos, 9), source_rank, rank_index)
        existing_score = definition_scores.get(normalized)
        if existing_score is not None and existing_score <= score:
            duplicate_skipped += 1
            continue
        if existing_score is not None and existing_score > score:
            duplicate_replaced += 1

        definitions[normalized] = gloss
        definition_scores[normalized] = score
        if source_rank == 0:
            kept_from_ranked += 1
        else:
            kept_from_lemma_fallback += 1

    ordered = {word: definitions[word] for word in sorted(definitions)}
    stats = {
        "source": str(source_path),
        "synsetCount": len(synsets),
        "lemmaRankedCount": len(lemma_ranked),
        "lemmaCount": len(lemma_plain),
        "definitionCount": len(ordered),
        "keptFromRanked": kept_from_ranked,
        "keptFromLemmaFallback": kept_from_lemma_fallback,
        "droppedBadLemma": dropped_bad_lemma,
        "droppedNoGloss": dropped_no_gloss,
        "duplicateReplaced": duplicate_replaced,
        "duplicateSkipped": duplicate_skipped,
    }

    out_path = resolve_path(args.out)
    stats_path = resolve_path(args.stats_out)
    save_json(out_path, ordered)
    save_json(stats_path, stats)

    print(f"Wrote {len(ordered)} WordNet definitions to {out_path}")
    print(f"Wrote stats to {stats_path}")


if __name__ == "__main__":
    main()

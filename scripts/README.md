# Scripts Index

This directory contains the level-build pipeline and supporting tools.

Use `npm run levels:build` for the normal build path.

Default build profile args live in `scripts/levels_build.args`.

High-level tuning guidance lives in `scripts/levels_build_tuning.md`.

## Primary pipeline files

- `generate_all.py` - orchestrates full build (lexicons, combos, generation, scoring, export, analysis, dictionary lookup)
- `build_lexicon.py` - builds filtered lexicon JSON (+ stats) from Wikipedia + includelists
- `extract_combos.py` - builds combo/token data from lexicon
- `generate_boards.py` - generates candidate levels for wheel/layout constraints
- `score_levels.py` - scores and ranks candidate levels
- `export_levels.py` - assembles final packs with novelty/difficulty constraints
- `analyze_levels_bundle.py` - reports bundle quality metrics and repeated-word/token CSVs
- `build_wordnet_dictionary.py` - flattens WordNet source into fallback word->definition JSON
- `build_dictionary_lookup.py` - builds app dictionary lookup JSON from bundle + layered dictionary sources

## Supporting tools

- `tune_wheel_token_shapes.py` - helper for wheel-shape sweep experiments
- `common.py` - shared helpers used by multiple scripts

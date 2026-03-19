# Level Build Pipeline and Tuning Guide

This guide covers the full `npm run levels:build` pipeline and the highest-impact tunables at each stage.

Goal: avoid tunnel vision on one metric (for example only early-pack repetition) when the real bottleneck is in a different stage.

## Pipeline map

`scripts/generate_all.py` runs these stages:

1. Main lexicon build (`build_lexicon.py`)
2. Bonus lexicon build (`build_lexicon.py` with relaxed bonus args)
3. Combo extraction (`extract_combos.py`)
4. Candidate generation (`generate_boards.py`)
5. Candidate scoring (`score_levels.py`)
6. Group export/selection (`export_levels.py`)
7. Bundle analysis (`analyze_levels_bundle.py`) and dictionary lookup build

Important: many failures and repetition outcomes are decided in stage 6 even when stage 1/4 supply is large.

## Stage-by-stage tuning

## Stage 1: Main lexicon supply

What it controls: which words can ever appear as answers.

**Frequency source:** wordfreq package only. Run from project root with `uv run` to ensure dependencies are available.

Highest-impact knobs:

- `--min-zipf` (default 2.0) — words below this are excluded
- `--three-letter-max-zipf` (default -0.5) — gate for 3-letter words
- blocklists (`data/raw/blocklists/*.json`) — profanity, inappropriate content
- re-enable list (`data/raw/re-enable/re-enable.txt`) — curated puzzle-appropriate words

**Re-enable list purpose:**

Filters out words that pass wordfreq but are poor puzzle words:
- Proper nouns (italy, monday, january)
- Acronyms/abbreviations (http, ceo, usa, etc)
- Slang/informal (pwn, woot, yeet)
- Historical Unicode forms (ſ = long s)

Primary diagnostics:

- `data/processed/lexicon_stats.json` (`wordCount`, `filterDrops`, `rowsWithGuessedFreq`)

Common trap:

- Bigger lexicon does not automatically fix novelty failures if downstream constraints are tighter than candidate diversity.

## Stage 2: Bonus lexicon supply

What it controls: bonus/valid word breadth, not primary answer selection.

Highest-impact knobs:

- `--bonus-min-zipf` (default 1.5) — lower threshold allows rarer bonus words
- `--bonus-three-letter-min-zipf` (default 3.0) — stricter gate for 3-letter bonus words

**Bonus word selection per level:**

1. Find all words spellable from wheel tokens (from bonus lexicon)
2. Filter: not an answer + uses ≥2 wheel tokens
3. Rank by: token count → word length → frequency
4. Select top 220 max

Use this when bonus word quality is the issue, not when answer repetition is the issue.

## Stage 3: Combo extraction

What it controls: token/combo universe used by generation/scoring.

Highest-impact knobs:

- `--combo-sizes`
- `--wheel-token-sizes`

Typically stable; tune only when token policy changes.

## Stage 4: Candidate generation

What it controls: how many viable candidates are created before export constraints.

Highest-impact knobs:

- `--group-size-targets` — levels per group (default: 12,18,24,30,50)
- `--group-oversamples` — generation multiplier
- `--group-min-answers` — minimum answer count per level
- `--group-freq-floors` — minimum average word frequency per group
- `--combo-pool-max-words`
- `--wheel-sampling-pool-max`

**Wheel shapes** (configured in `AUTO_GROUP_WHEEL_SHAPE_MIX_RAW`):

| Wheel Size | Shapes | Notes |
|------------|--------|-------|
| 3 | 2 | Intro levels, simple |
| 4 | 4 | Adds triple intro |
| 5 | 6 | Full variety |
| 6 | 7 | Full variety |
| 7 | 10 | Full spectrum easy→hard |

Format: `singles/doubles/triples:weight` — weight determines relative frequency.

Primary diagnostics:

- manifest run counts and repeated export shortfalls by group/shape
- repeated failures in the same group despite selector tweaks

## Stage 5: Candidate scoring

What it controls: ranking pressure among generated candidates.

Highest-impact knobs (in practice):

- mostly inherited from stage 4 token/answer constraints and combo policy

This stage is usually not the first tuning target unless ranking behavior is clearly misaligned.

## Stage 6: Group export and novelty/difficulty selection

What it controls: final pack composition, repetition behavior, spacing, and target-curve adherence.

**Group labels:** Excel-style (A-Z, then AA-AZ, BA-BZ, etc.)

**Difficulty curve:**

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `--group-difficulty-target-avg-freq-start` | 4.35 | Group E target (house, water) |
| `--group-difficulty-target-avg-freq-end` | 2.75 | Final group target (ephemeral, symbiosis) |
| `--group-difficulty-target-power` | 1.4 | Curve shape (higher = slower initial progress) |
| `--group-difficulty-target-weight` | 2.5 | Penalty weight for deviation from target |

Zipf reference:
- 4.0+: Very common (butterfly, hypothesis)
- 3.0-4.0: Common (metaphor, paradigm)
- 2.5-3.0: Challenging (ephemeral, zeitgeist)
- 2.0-2.5: Hardcore (serendipity, surreptitious)
- <2.0: Obscure (most players won't recognize)

Highest-impact knobs:

- `--group-strict-novelty-early-groups`
- `--group-size-undershoot-ratio`
- `--group-reuse-budget-ratio`
- `--group-cross-pack-short-word-max-reuse`
- `--group-cross-pack-long-word-max-reuse`
- `--group-three-letter-signature-early-groups`

Primary diagnostics:

- `Unable to fill group with novelty constraints ... run=merged`
- analysis deltas vs target curve (`d=...`, `targetAvgAbsDelta`)

## Stage 7: Analysis and verification

What it controls: visibility and regression detection.

Key outputs:

- `data/generated/levels_bundle_analysis.txt` — full summary
- `data/generated/repeated_words_early.csv` — early group repeats
- `data/generated/repeated_words_all.csv` — all repeated words
- `data/generated/solution_words_flagged_review.csv` — words needing review

## Highest-leverage knobs (cross-stage shortlist)

If you can only touch a few values, start here:

1. `--group-size-targets`
2. `--group-oversamples`
3. `--group-freq-floors`
4. `--group-size-undershoot-ratio`
5. `--group-strict-novelty-early-groups`
6. `--group-reuse-budget-ratio`
7. `--group-cross-pack-short-word-max-reuse`
8. `--group-cross-pack-long-word-max-reuse`
9. `--combo-pool-max-words`
10. `--wheel-sampling-pool-max`
11. `--group-difficulty-target-avg-freq-start/end`
12. `--group-difficulty-target-weight`

## Symptom -> first moves

### Export fails on novelty fill (any group)

1. Increase supply: oversample and/or lower target for that group.
2. Lower floor pressure for the stressed pack range.
3. Increase undershoot before relaxing novelty caps.
4. Relax novelty caps only if product goals require fixed pack sizes.

### Repetition too high (especially early packs)

1. Tighten cross-pack short/long reuse caps.
2. Expand signature controls (`three-letter` and short-word signatures).
3. Increase candidate supply before increasing strict novelty.

### Late packs miss intended difficulty curve

1. Increase late oversample first.
2. Recalibrate `target-avg-freq start/end` to practical range.
3. Tune `difficulty-target-weight` if selector is over/under-chasing targets.

## Recommended iteration loop

1. Change 1-2 knobs per run.
2. Run focused test (A-D) for early issues, full run for progression issues.
3. Compare analysis + repeated-word/token CSVs against previous baseline.
4. Keep only changes that improve the intended objective without major regressions.

## Guardrails

- Do not optimize one metric in isolation.
- Prefer supply/target changes before relaxing novelty protections.
- If undershoot is enabled, track actual emitted pack sizes and player-facing impact.
- Always run from project root with `uv run` to ensure dependencies (wordfreq, lemminflect).
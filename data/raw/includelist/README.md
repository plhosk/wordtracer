`data/raw/includelist/includelist.json` is an explicit includelist used by level generation.

Words here are force-included into both lexicons built by `scripts/generate_all.py`:
- main lexicon (`data/processed/lexicon.json`)
- bonus lexicon (`data/processed/lexicon_bonus.json`)

Use this list for words that should be kept even if they are uncommon or missing from corpus sources.

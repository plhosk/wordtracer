# Third-Party Notices

This project uses third-party data sources and build inputs for level generation
and dictionary lookup.

Machine-readable source inventory lives in `data/raw/LICENSES.json`.

## Sources

### Re-Enable word list

- Source: <https://github.com/JakesMD/Re-Enable>
- License: MIT

### Wikipedia word frequency

- Source: <https://github.com/IlyaSemenov/wikipedia-word-frequency>
- License: MIT

### Profane words blocklist

- Source: <https://github.com/zautumnz/profane-words>
- License: WTFPL

### Webster's Unabridged Dictionary

- Source: <https://www.gutenberg.org/ebooks/29765>
- License status: public domain in the USA via Project Gutenberg source text

### wordfreq

- Source: <https://github.com/rspeer/wordfreq>
- License: Apache License 2.0
- Upstream note: `wordfreq` includes additional notice and attribution details
  for some bundled data; see upstream `NOTICE.md`
- Used by this project during level generation

### WordNet 3.0

- Source: <https://wordnet.princeton.edu/>
- License: WordNet 3.0 license
- Local input: `data/raw/wordnet/wordnet.json` (from `wordnet-to-json` conversion)

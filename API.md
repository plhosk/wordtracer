# Word Tracer API

REST API for the Word Tracer game engine. Enables LLM agents and other clients to interact with the game.

**Base URL:** `http://localhost:3001`

---

## Core Gameplay Loop

These endpoints are the minimal set needed to play through levels.

### Create Game

```
POST /api/games
```

Creates a new game starting at the first level (A1). All progress (completed levels, solved words) is persisted automatically.

**Body:** `{}` (optional, ignored)

**Returns:** `gameId`, `level`, `state`

**Note:** Prefer continuing with your existing game rather than creating a new one. The client should persist `gameId` for later reference. There's currently no security so it's best to avoid taking over an existing game that you didn't start.

### Get Current Level

```
GET /api/games/:id/level
```

Returns level details and progress: wheel tokens, current grid, word starts, solved/bonus words, remaining word count, and completion status.

### Get Wheel State

```
GET /api/games/:id/wheel
```

Returns the current letter wheel tokens, direction, and version.

### Submit Word

```
POST /api/games/:id/submit
```

Submits a word guess. Words must be made from at least two tokens in any order (the order of tokens in the wheel is arbitrary). Each token can only be used once.

The wheel has a `tokenDirection` state. Tokens with 2+ letters can be reversed by toggling the direction, but it is forbidden to mix forward and reverse tokens.

When submitting a word you can optionally toggle the token direction first in the same request using `toggleTokenDirectionFirst`.

**Body:** `{ "word": string, "version": number, "toggleTokenDirectionFirst"?: boolean }`

**Returns:** `version`, `result`, `word`, `levelComplete`

**Results:**
- `solved` - Word is a valid answer and was added
- `already-solved` - Word was already solved in this session
- `bonus` - Word is a valid bonus word and was added
- `already-bonus` - Bonus word was already found
- `wrong-direction` - Word cannot be spelled with current token direction, but can in the other direction
- `not-spellable` - Word cannot be spelled with the letter wheel in either direction
- `not-accepted` - Word is spellable in the current direction but is not in the level's word list

### Toggle Token Direction

```
POST /api/games/:id/token-direction
```

Reverses 2+ letter tokens on the wheel (e.g., "on" ↔ "no").

**Body:** `{ "version": number }`

### Get Grid (Simple)

```
GET /api/games/:id/grid
```

Returns the grid in two formats:
- `gridRowsCurrent` - Array of row strings with revealed letters, `*` for unrevealed word starts, `.` for other unrevealed cells, and spaces for empty cells
- `gridColsCurrent` - Array of column strings (same format, transposed for reading vertical words)
- `gridRowsStart` - Array of row strings - starting grid, useful to locate word starts that may be covered by revealed letters
- `gridColsStart` - Array of column strings (same format, transposed for reading vertical words)
- `wordStarts` - Array of word start objects with `pos` ([row,col], 0-indexed), `dir`, and `len`

The grid is useful for showing known letters in unsolved words, which can help narrow down the search space. In a partially solved grid, use wordStarts or compare gridRowsStart/gridColsStart (showing * for word starts) against gridRowsCurrent/gridColsCurrent to identify partially solved words with the most revealed letters.

### Get Grid (Object)

```
GET /api/games/:id/grid/object
```

Returns grid cells with coordinates, revealed letters, word start positions, and walls.

### Next Level

```
POST /api/games/:id/next
```

Advances to the next level after completing the current one.

**Body:** `{ "version": number }`

---

## Level Navigation

### Jump to Level

```
POST /api/games/:id/jump
```

Switches to a different level. Progress is automatically persisted, and any previously saved state for the target level is restored.

**Body:** `{ "levelName": string, "version": number }`

Example: `{ "levelName": "A5", "version": 3 }`

### Reset Current Level

```
POST /api/games/:id/reset-level
```

Clears progress for the current level only (solved words, bonus words, and hint state) while keeping overall game and pack progress intact.

**Body:** `{ "version": number }`

**Returns:**
- `version` - Updated game version
- `level` - Current level name
- `state` - Current level state payload (same shape as `GET /api/games/:id/level`)

---

## Game Management

Games track the current level, completed levels, and per-level progress (solved/bonus words). All changes are persisted automatically.

### List Games

```
GET /api/games
```

Returns all games (id and current level name), sorted by most recently updated.

### Get Game State

```
GET /api/games/:id
```

Returns version, current level, and progress across all level packs.

### Delete Game

```
DELETE /api/games/:id
```

Permanently deletes the game and all associated data, including completed levels and per-level progress.

---

## Level Reference

Browse available levels without a game.

### List Level Groups

```
GET /api/levels
```

Returns all level groups (packs) with level counts.

### Get Levels in Group

```
GET /api/groups/:id/levels
```

Returns all levels within a specific group (e.g., group "A"). Each level is identified by its name (e.g., "A1", "A2").

### Get Level Details

```
GET /api/levels/:name
```

Returns static level info: dimensions, wheel, word count, walls, grid layout (`gridRows`/`gridCols` with `*` for word starts), and `wordStarts` array.

---

## Dictionary

Lookup word definitions from the game's dictionary.

### Get Dictionary Entry

```
GET /api/dictionary/:word
```

Returns the canonical form and definition for a word, or `null` if not found. Note: some valid solution words are missing from the dictionary, so it can't be used to filter possible solutions.

**Returns:** `{ canonical: string, definition: string }` | `null`

### Check Word Exists

```
GET /api/dictionary/:word/exists
```

Checks if a word is in the dictionary.

**Returns:** `{ exists: boolean }`

---

## Hints

Get spoiler-free hints for unsolved words.

### Get Hint

```
GET /api/games/:id/hint
```

Returns a hint for an unsolved word in the current level. The hint is a sanitized excerpt from the word's definition with the answer word and related forms removed.

**Returns:**
- `excerpt` - Sanitized definition excerpt
- `truncatedStart` - Whether the excerpt was truncated at the start
- `truncatedEnd` - Whether the excerpt was truncated at the end
- `hintCount` - Total hints used for this level
- `canRefresh` - Whether hint refresh is available
- `version` - Current game version (incremented after this mutation)

Returns `{ hint: null }` if no hints available (all words solved or excluded).

### Refresh Hint

```
POST /api/games/:id/hint/refresh
```

Excludes the current hint and requests a new one. Can only be used once per level.

**Returns:** Same as GET hint

**Errors:**
- `400` - Hint refresh already used or no current hint to refresh

---

## Concurrency

All mutation endpoints require a `version` field that must match the current game version.

**Version mismatch response:**
- HTTP status: `409 Conflict`
- `{ "error": "VERSION_MISMATCH", "message": "Session was modified by another request" }`

Re-fetch the game state to get the current version, then retry.

---

## Server Operations

### Health Check

```
GET /health
```

Returns server status and loaded level count.

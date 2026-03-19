# Word Tracer

Word Tracer is a minimal word puzzle game with crossword-style boards and a swipeable letter wheel. Trace words from the wheel to reveal the grid, clear each level, and keep an eye out for bonus words.

Fully offline and ad-free.

## Start Playing

```bash
npm install
npm run dev
```

Then open the local Vite URL shown in your terminal.

## How It Plays

- Swipe across the letter wheel to build a word.
- Correct answers reveal letters on the board.
- Complete every answer in the grid to finish the level.
- Use the swap button to reverse multi-letter tokens when a word needs the other direction.

## Features

- Crossword-like hidden grid that fills in as you solve words
- Swipe-based letter wheel input for mouse and touch
- Bonus word tracking
- Optional dictionary lookups for found words
- Spoiler-light hint system with one refresh per level
- Multiple level packs with saved progress
- Light and dark themes
- Web and Android support via Vite and Capacitor

## API

An optional Node server exposes the game through a REST API for tools, agents, and external clients. See how many levels your LLM agent can solve!

```bash
npm run server:watch
```

The API runs on `http://localhost:3001` by default. Full endpoint documentation lives in `API.md`.

## Level Generation

Levels are pre-generated through a Python-based build pipeline that assembles lexicons, token combos, candidate boards, scoring, final pack export, and dictionary lookup data. A large set of generated levels are distributed with the game.

```bash
npm run levels:build
```

Pipeline notes live in `scripts/README.md`, and tuning guidance lives in `scripts/levels_build_tuning.md`.

## Development

Useful scripts:

```bash
npm run dev           # start the Vite web app
npm run check         # run TypeScript and ESLint
npm run build         # build the web app
npm run build:server  # build the Node API server
npm run server        # build and start the API server
npm run server:watch  # rebuild and restart the API server on changes
npm run preview       # preview the production web build locally
```

Android helpers:

```bash
npm run cap:sync      # build web assets and sync them into Capacitor
npm run android:build # build a debug APK
npm run android:open  # open the Android project in Android Studio
npm run android:run   # sync and run the app on Android
```

## Licensing

Project and third-party notices for bundled data sources are documented in `THIRD_PARTY_NOTICES.md`.

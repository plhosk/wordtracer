## Project

Word Tracer, a crossword-like puzzle game for web and android. Uses vanilla TypeScript/CSS bundled with Vite, Capacitor, and an optional Node server API.

## Agent Directives

- Don't add comments to code unless requested.
- Try not to use underscore prefixes for unused variables and parameters, unless their use would save a significant amount of refactoring.
- Avoid starting any background commands or servers.
- Invoke Python commands from the project root through `uv`, e.g. `uv run python ...`.
- Avoid running the full level build or commands that are expected to use high CPU for >1min. Instead provide the command to the user.

## Build Commands

```bash
npm run check      # A full check, runs tsc and eslint with the proper configs.
npm run build      # Production web build, only for final deployment.
```

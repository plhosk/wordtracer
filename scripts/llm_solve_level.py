#!/usr/bin/env python3
"""
LLM-based level solver using OpenCode HTTP API.
Tests whether LLM agents can solve puzzles similarly to human players.
Simulates multi-turn gameplay where correct guesses reveal letters.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from common import load_json, project_path

DEFAULT_MODEL = "alibaba-coding-plan/glm-5"
DEFAULT_BASE_URL = "http://localhost:4096"
MAX_TURNS = 30  # Prevent infinite loops


@dataclass
class GameState:
    """Tracks the state of a game in progress."""

    solved_words: set[str] = field(default_factory=set)
    revealed_cells: dict[tuple[int, int], str] = field(default_factory=dict)
    bonus_words: set[str] = field(default_factory=set)
    turns: int = 0
    guesses: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Have an LLM attempt to solve puzzle levels."
    )
    parser.add_argument(
        "--bundle",
        default=str(project_path("data", "generated", "levels.bundle.json")),
        help="Path to levels bundle JSON.",
    )
    parser.add_argument(
        "--groups",
        default="E,AZ",
        help="Comma-separated group IDs to test (e.g., 'E,G,M,AZ').",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="Number of levels to sample per group.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model ID to use for solving (format: provider/model).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay between requests in seconds.",
    )
    parser.add_argument(
        "--out",
        default=str(project_path("data", "generated", "llm_solve_results.json")),
        help="Output path for results JSON.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="OpenCode server base URL.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show prompts and responses for debugging.",
    )
    parser.add_argument(
        "--agent",
        default="minimal",
        help="Agent to use for solving.",
    )
    return parser.parse_args()


def format_wall_grid(
    level: dict, revealed_cells: dict[tuple[int, int], str] | None = None
) -> str:
    """Format the wall structure as ASCII art. Shows connections and revealed letters.

    Users see walls between cells, not the letters. The walls define which
    cells are connected (no wall) vs separated (wall present).
    When letters are revealed (after solving words), they are shown in the cells.
    """
    rows = level.get("rows", 10)
    cols = level.get("cols", 10)
    walls = level.get("walls", {})
    cells = level.get("cells", [])
    revealed = revealed_cells or {}

    # Determine which cells are occupied (part of any word)
    occupied = set()
    for answer in level.get("answers", []):
        for r, c in answer.get("path", []):
            occupied.add((r, c))

    if not occupied:
        return "Empty grid"

    # Find bounds of occupied cells
    min_row = min(r for r, c in occupied)
    max_row = max(r for r, c in occupied)
    min_col = min(c for r, c in occupied)
    max_col = max(c for r, c in occupied)

    h_walls = walls.get("h", [])  # Horizontal walls (between rows, below cells)
    v_walls = walls.get("v", [])  # Vertical walls (between columns, to left of cells)

    lines = []

    # Build the grid row by row (only occupied region)
    for r in range(min_row, max_row + 1):
        # Top boundary for first row, or horizontal walls above this row
        if r == min_row:
            top_line = ""
            for c in range(min_col, max_col + 1):
                if (r, c) in occupied:
                    top_line += "+---"
                else:
                    # Check if cell below is occupied
                    if (r + 1, c) in occupied:
                        top_line += "+---"
                    else:
                        top_line += "    "
            lines.append(top_line.rstrip())

        # Cell content and vertical walls
        cell_line = ""
        for c in range(min_col, max_col + 1):
            if (r, c) in occupied:
                # Left wall or boundary
                if c == min_col:
                    cell_line += "|"
                else:
                    # Check if there's a wall to the left
                    has_wall = True  # Default to wall if data missing
                    if r < len(v_walls) and c - 1 < len(v_walls[r]):
                        has_wall = v_walls[r][c - 1] == 1
                    # Also check if left neighbor is occupied - if not, show wall
                    if (r, c - 1) not in occupied:
                        has_wall = True
                    cell_line += "|" if has_wall else " "

                # Cell content - show letter if revealed, otherwise placeholder
                if (r, c) in revealed:
                    letter = revealed[(r, c)].upper()
                    cell_line += f" {letter} "
                else:
                    cell_line += " . "
            else:
                # Empty cell - check if we need to show anything
                left_occupied = (r, c - 1) in occupied if c > min_col else False
                above_occupied = (r - 1, c) in occupied if r > min_row else False
                below_occupied = (r + 1, c) in occupied if r < max_row else False
                right_occupied = (r, c + 1) in occupied if c < max_col else False

                if left_occupied or above_occupied or below_occupied or right_occupied:
                    # This empty cell is adjacent to occupied cells
                    if left_occupied:
                        # Continue the line from left
                        if c == min_col:
                            cell_line += "|"
                        else:
                            has_wall = True
                            if r < len(v_walls) and c - 1 < len(v_walls[r]):
                                has_wall = v_walls[r][c - 1] == 1
                            cell_line += "|" if has_wall else " "
                    else:
                        cell_line += " "
                    cell_line += "   "
                else:
                    cell_line += "    "

        # Right boundary for this row
        rightmost_occupied_in_row = any(
            (r, c) in occupied for c in range(min_col, max_col + 1)
        )
        if rightmost_occupied_in_row:
            cell_line += "|"
        lines.append(cell_line.rstrip())

        # Bottom walls (horizontal walls below this row)
        bottom_line = ""
        for c in range(min_col, max_col + 1):
            curr_occupied = (r, c) in occupied
            below_occupied = (r + 1, c) in occupied if r < max_row else False

            if curr_occupied or below_occupied:
                # Check if there's a horizontal wall between these cells
                has_wall = True  # Default to wall
                if curr_occupied and below_occupied:
                    # Both cells occupied - check for internal wall
                    if r < len(h_walls) and c < len(h_walls[r]):
                        has_wall = h_walls[r][c] == 1
                elif curr_occupied and not below_occupied:
                    # Only current cell occupied - this is a boundary
                    has_wall = True
                elif not curr_occupied and below_occupied:
                    # Only below cell occupied - this is a boundary
                    has_wall = True

                if has_wall:
                    bottom_line += "+---"
                else:
                    bottom_line += "+   "
            else:
                bottom_line += "    "

        lines.append(bottom_line.rstrip())

    return "\n".join(lines)


def format_word_lengths(level: dict, solved_words: set[str] | None = None) -> str:
    """Describe word lengths without revealing positions or letters.

    Users can deduce word lengths from the wall structure by counting
    connected cells, but not exact positions until letters are revealed.
    Shows remaining words to find if some have been solved.
    """
    answers = level.get("answers", [])
    if not answers:
        return "No words to find."

    solved = solved_words or set()

    # Get lengths of unsolved words
    remaining_lengths = []
    for answer in answers:
        word = answer.get("text", "").lower()
        if word not in solved:
            remaining_lengths.append(len(answer.get("path", [])))

    if not remaining_lengths:
        return "All words found!"

    remaining_lengths.sort()

    # Group by length
    length_counts: dict[int, int] = {}
    for length in remaining_lengths:
        length_counts[length] = length_counts.get(length, 0) + 1

    parts = []
    for length in sorted(length_counts.keys()):
        count = length_counts[length]
        if count == 1:
            parts.append(f"1 word of {length} letters")
        else:
            parts.append(f"{count} words of {length} letters")

    return ", ".join(parts)


def format_initial_prompt(level: dict) -> str:
    """Format the initial prompt for starting a new game.

    Shows the wall structure, wheel tokens, and instructions.
    """
    wall_grid = format_wall_grid(level)
    wheel = level.get("letterWheel", [])
    wheel_str = ", ".join(f'"{token}"' for token in wheel)

    # Also show the reversed versions of multi-letter tokens
    reversed_tokens = []
    for token in wheel:
        if len(token) >= 2:
            reversed_tokens.append(token[::-1])
    reversed_str = (
        ", ".join(f'"{t}"' for t in reversed_tokens) if reversed_tokens else "none"
    )

    answers = level.get("answers", [])
    num_words = len(answers)
    word_lengths = format_word_lengths(level)

    prompt = f"""You are playing a word puzzle game called Word Tracer.

## Your Goal:
Find {num_words} hidden words using the letter tokens on the wheel.

## The Wheel:
You have these letter tokens available: {wheel_str}

Token swap mechanic:
- Multi-letter tokens can be reversed: {reversed_str}
- When spelling a word, ALL tokens must be in the same state (all original or all reversed)
- You cannot mix original and reversed tokens in the same word
- Single-letter tokens stay the same regardless

Example: If tokens are "em", "it", "s":
- Original state: "em", "it", "s" → can spell "items", "times"
- Reversed state: "me", "ti", "s" → can spell "mites", "times"

## The Grid:
The puzzle grid has cells connected by paths (no walls between them). Walls block movement between cells. Words are hidden along connected paths through the grid.

```
{wall_grid}
```

In this ASCII representation:
- "+" and "-" and "|" show walls
- "." marks cells with hidden letters
- Connected cells (no wall between them) can be part of the same word
- Words follow paths through connected cells, turning at corners like a maze

## Word Info:
{word_lengths}

## How to Play:
1. Examine the wheel tokens and think of valid English words you can spell
2. Words follow connected paths in the grid (cells with no wall between them)
3. A word path can turn corners - it's not limited to straight lines
4. Submit ONE word by swiping the tokens in order on the wheel
5. If correct, the letters will be revealed on the grid
6. Find all {num_words} words to complete the level

## Your Task:
Guess ONE word you think is hidden in this puzzle. You have no revealed letters yet, so make your best guess based on the wheel tokens and word lengths. Remember: each word must use tokens that are all in the same state (all original or all reversed).

Format: Reply with just the word in UPPERCASE.
"""
    return prompt


def format_turn_prompt(level: dict, state: GameState, last_result: str) -> str:
    """Format a prompt for a subsequent turn, showing revealed letters."""

    wall_grid = format_wall_grid(level, state.revealed_cells)
    wheel = level.get("letterWheel", [])
    wheel_str = ", ".join(f'"{token}"' for token in wheel)

    # Show reversed tokens
    reversed_tokens = []
    for token in wheel:
        if len(token) >= 2:
            reversed_tokens.append(token[::-1])
    reversed_str = (
        ", ".join(f'"{t}"' for t in reversed_tokens) if reversed_tokens else "none"
    )

    answers = level.get("answers", [])
    num_remaining = sum(
        1 for a in answers if a.get("text", "").lower() not in state.solved_words
    )
    word_lengths = format_word_lengths(level, state.solved_words)

    # List solved words
    solved_list = (
        ", ".join(sorted(w.upper() for w in state.solved_words))
        if state.solved_words
        else "none"
    )

    prompt = f"""Continue playing Word Tracer.

## Wheel Tokens: {wheel_str}
Reversed options: {reversed_str}

## Current Grid (revealed letters shown):
```
{wall_grid}
```

## Progress:
- Solved words: {solved_list}
- Remaining: {num_remaining} words
- {word_lengths}

## Last Guess Result:
{last_result}

## Your Task:
Guess ONE word you think is hidden. Use the revealed letters to help you find remaining words. Remember: each word must use tokens that are all in the same state (all original or all reversed).

Format: Reply with just the word in UPPERCASE.
"""
    return prompt


def parse_single_word(response_text: str) -> str | None:
    """Parse a single word from LLM response.

    Returns the first valid word found, or None if no valid word.
    """
    # Pattern 1: Bold markdown words like **BELOW** or **WORD**
    match = re.search(r"\*\*([A-Z]+)\*\*", response_text)
    if match:
        word = match.group(1).lower()
        if len(word) >= 3:
            return word

    # Pattern 2: Words after arrow like → BELOW or -> BELOW
    match = re.search(r"[→\-]>\s*([A-Za-z]+)", response_text)
    if match:
        word = match.group(1).lower()
        if len(word) >= 3:
            return word

    # Pattern 3: Standalone lines that are just uppercase words (3+ chars)
    for line in response_text.strip().split("\n"):
        line = line.strip()
        # Check if line is just a word (possibly with number prefix like "1. WORD")
        match = re.match(r"^(\d+\.\s*)?([A-Z]{3,})$", line)
        if match:
            return match.group(2).lower()

    # Pattern 4: Lines starting with a word followed by explanation like "BELOW is..."
    for line in response_text.strip().split("\n"):
        match = re.match(r"^([A-Z]{3,})(?:\s|$|[^A-Z])", line.strip())
        if match:
            return match.group(1).lower()

    # Pattern 5: Look for any 3+ letter word that could be a guess
    match = re.search(r"\b([A-Z]{3,})\b", response_text)
    if match:
        return match.group(1).lower()

    return None


def submit_word(word: str, level: dict, state: GameState) -> tuple[bool, str]:
    """Submit a word and update game state.

    Returns (is_correct, result_message).
    """
    word_lower = word.lower().strip()
    answers = level.get("answers", [])
    cells = level.get("cells", [])

    # Check if already solved
    if word_lower in state.solved_words:
        return False, f"'{word.upper()}' was already solved."

    # Check if it's a correct answer
    for answer in answers:
        if answer.get("text", "").lower() == word_lower:
            # Found a correct answer!
            state.solved_words.add(word_lower)

            # Reveal letters for this word
            for r, c in answer.get("path", []):
                if r < len(cells) and c < len(cells[r]):
                    state.revealed_cells[(r, c)] = cells[r][c]

            # Check for auto-solve (if all cells of another answer are now revealed)
            auto_solved = check_auto_solve(level, state)

            result = f"Correct! '{word.upper()}' solved."
            if auto_solved:
                result += f" Auto-solved: {', '.join(w.upper() for w in auto_solved)}"

            return True, result

    # Check if it's a bonus word
    bonus_words = [w.lower() for w in level.get("bonusWords", [])]
    valid_words = [w.lower() for w in level.get("validWords", [])]

    if word_lower in bonus_words or word_lower in valid_words:
        if word_lower in state.bonus_words:
            return False, f"'{word.upper()}' already found as bonus."
        state.bonus_words.add(word_lower)
        return False, f"'{word.upper()}' is a bonus word! Keep looking for main words."

    # Not a valid word
    return False, f"'{word.upper()}' is not in this puzzle."


def check_auto_solve(level: dict, state: GameState) -> list[str]:
    """Check if any unsolved answers are fully revealed and auto-solve them.

    Returns list of auto-solved words.
    """
    cells = level.get("cells", [])
    auto_solved = []

    for answer in level.get("answers", []):
        word = answer.get("text", "").lower()
        if word in state.solved_words:
            continue

        # Check if all cells are revealed
        path = answer.get("path", [])
        if all(state.revealed_cells.get((r, c)) is not None for r, c in path):
            state.solved_words.add(word)
            auto_solved.append(word)

    return auto_solved


def create_session(client: httpx.Client) -> str:
    """Create a new session and return its ID."""
    response = client.post("/session", json={})
    response.raise_for_status()
    data = response.json()
    return data["id"]


def delete_session(client: httpx.Client, session_id: str) -> None:
    """Delete a session."""
    try:
        client.delete(f"/session/{session_id}").raise_for_status()
    except Exception:
        pass


def send_message(
    client: httpx.Client,
    session_id: str,
    prompt: str,
    model: str,
    agent: str = "minimal",
    timeout: float = 300.0,
) -> str:
    """Send a message to the session and return the assistant's response text."""
    # Parse model ID - format is "provider/model"
    parts = model.split("/", 1)
    if len(parts) == 2:
        provider_id, model_id = parts[0], parts[1]
    else:
        provider_id, model_id = model, model

    response = client.post(
        f"/session/{session_id}/message",
        json={
            "parts": [{"type": "text", "text": prompt}],
            "model": {
                "providerID": provider_id,
                "modelID": model_id,
            },
            "agent": agent,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()

    # Extract text from response parts
    # Response format: { info: Message, parts: Part[] }
    text_parts = []
    for part in data.get("parts", []):
        if part.get("type") == "text":
            text_parts.append(part.get("text", ""))
        elif part.get("type") == "step-start":
            # Steps contain tool calls, skip
            pass
        elif part.get("type") == "step-finish":
            # Step completion, skip
            pass

    return "".join(text_parts)


def solve_level(
    level: dict,
    client: httpx.Client,
    model: str,
    agent: str = "minimal",
    verbose: bool = False,
) -> dict[str, Any]:
    """Have the LLM attempt to solve a level with multi-turn gameplay."""
    level_id = level.get("id", 0)
    actual_words = {a.get("text", "").lower() for a in level.get("answers", [])}
    num_answers = len(actual_words)

    state = GameState()
    start_time = time.time()
    session_id = None

    try:
        # Create session
        session_id = create_session(client)

        # Initial prompt
        prompt = format_initial_prompt(level)

        if verbose:
            print("\n" + "=" * 60)
            print(f"TURN 1 - Initial prompt (Level {level_id}):")
            print("=" * 60)
            print(prompt[:1000] + "..." if len(prompt) > 1000 else prompt)

        # Game loop
        last_result = ""
        while state.turns < MAX_TURNS:
            state.turns += 1

            # Get LLM's guess
            response_text = send_message(client, session_id, prompt, model, agent=agent)

            if verbose:
                print(f"\n--- Turn {state.turns} Response ---")
                print(response_text[:500])

            # Parse the guess
            guess = parse_single_word(response_text)

            if guess is None:
                last_result = "Could not understand your guess. Please reply with just a word in UPPERCASE."
                prompt = format_turn_prompt(level, state, last_result)
                state.guesses.append("???")
                continue

            state.guesses.append(guess)

            # Submit the guess
            is_correct, result_msg = submit_word(guess, level, state)
            last_result = result_msg

            if verbose:
                print(f"Guess: {guess.upper()} -> {result_msg}")

            # Check if level complete
            if state.solved_words >= actual_words:
                break

            # Prepare next turn prompt
            prompt = format_turn_prompt(level, state, last_result)

        elapsed = time.time() - start_time

        # Calculate metrics
        correct = state.solved_words & actual_words
        missed = actual_words - state.solved_words

        accuracy = len(correct) / num_answers if num_answers else 0.0
        efficiency = num_answers / state.turns if state.turns else 0.0

        if verbose:
            print("\n" + "=" * 60)
            print("GAME OVER")
            print("=" * 60)
            print(f"Solved: {sorted(correct)}")
            print(f"Missed: {sorted(missed)}")
            print(f"Bonus:  {sorted(state.bonus_words)}")
            print(f"Turns:  {state.turns}")
            print(f"Guesses: {state.guesses}")

        result = {
            "level_id": level_id,
            "group": level.get("group", "unknown"),
            "difficulty": level.get("difficulty", 0),
            "num_answers": num_answers,
            "solved_words": sorted(correct),
            "missed_words": sorted(missed),
            "bonus_words": sorted(state.bonus_words),
            "all_guesses": state.guesses,
            "turns": state.turns,
            "accuracy": round(accuracy, 4),
            "efficiency": round(efficiency, 4),
            "elapsed_seconds": round(elapsed, 2),
            "model": model,
        }

    except Exception as e:
        result = {
            "level_id": level_id,
            "error": str(e),
            "elapsed_seconds": time.time() - start_time,
        }
    finally:
        if session_id:
            delete_session(client, session_id)

    return result


def main() -> None:
    args = parse_args()

    # Initialize HTTP client
    client = httpx.Client(base_url=args.base_url, timeout=300.0)
    print(f"Connected to OpenCode server at {args.base_url}")

    # Load bundle
    bundle = load_json(Path(args.bundle))
    groups = {g["id"]: g for g in bundle.get("groups", [])}
    levels_by_id = {l["id"]: l for l in bundle.get("levels", [])}

    # Parse target groups
    target_groups = [g.strip() for g in args.groups.split(",")]

    # Collect results
    all_results = []

    for group_id in target_groups:
        group = groups.get(group_id)
        if not group:
            print(f"Warning: Group '{group_id}' not found")
            continue

        level_ids = group.get("levelIds", [])
        if not level_ids:
            print(f"Warning: Group '{group_id}' has no levels")
            continue

        # Sample levels
        sample_ids = random.sample(level_ids, min(args.samples, len(level_ids)))

        print(f"\nGroup {group_id}: sampling {len(sample_ids)} levels...")

        for i, level_id in enumerate(sample_ids, 1):
            level = levels_by_id.get(level_id)
            if not level:
                continue

            # Add group info to level
            level["group"] = group_id

            if args.verbose:
                print(f"  [{i}/{len(sample_ids)}] Solving level {level_id}...")
            else:
                print(
                    f"  [{i}/{len(sample_ids)}] Solving level {level_id}...",
                    end=" ",
                    flush=True,
                )

            result = solve_level(
                level, client, args.model, agent=args.agent, verbose=args.verbose
            )
            result["group"] = group_id
            all_results.append(result)

            if "error" in result:
                print(f"ERROR: {result['error']}")
            elif not args.verbose:
                turns = result.get("turns", 0)
                accuracy = result.get("accuracy", 0)
                print(
                    f"accuracy={accuracy:.0%} in {turns} turns ({len(result['solved_words'])}/{result['num_answers']} words)"
                )

            # Delay between requests
            if i < len(sample_ids):
                time.sleep(args.delay)

    # Calculate summary statistics
    print("\n" + "=" * 60)
    print("Summary Results")
    print("=" * 60)

    # Group by group_id
    by_group: dict[str, list] = {}
    for r in all_results:
        if "error" not in r:
            g = r.get("group", "unknown")
            by_group.setdefault(g, []).append(r)

    for group_id in target_groups:
        results = by_group.get(group_id, [])
        if not results:
            continue

        avg_accuracy = sum(r["accuracy"] for r in results) / len(results)
        avg_efficiency = sum(r["efficiency"] for r in results) / len(results)
        avg_turns = sum(r["turns"] for r in results) / len(results)
        avg_time = sum(r["elapsed_seconds"] for r in results) / len(results)

        print(f"\nGroup {group_id}:")
        print(f"  Samples: {len(results)}")
        print(f"  Avg Accuracy: {avg_accuracy:.1%}")
        print(f"  Avg Efficiency: {avg_efficiency:.2f} words/turn")
        print(f"  Avg Turns: {avg_turns:.1f}")
        print(f"  Avg Time: {avg_time:.1f}s")

    # Save results
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(
            {
                "model": args.model,
                "groups": target_groups,
                "samples_per_group": args.samples,
                "results": all_results,
            },
            f,
            indent=2,
        )

    print(f"\nResults saved to {out_path}")

    # Close client
    client.close()


if __name__ == "__main__":
    main()

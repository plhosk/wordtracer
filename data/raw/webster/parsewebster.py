from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

ASCII_ALPHA_UPPERCASE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ-"
MULTI_WORD_DEFINITION_SEPARATOR = "; "
DEFINITION_PREFIX = "Defn: "
DEFINITION_ITEM_PREFIX_NUMERICAL = "1."
DEFINITION_ITEM_PREFIX_ALPHABETIZED = "(a)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse Webster dictionary text into JSON."
    )
    here = Path(__file__).resolve().parent
    parser.add_argument(
        "input",
        nargs="?",
        default=str(here / "webster.txt"),
        help="Path to source dictionary text (default: webster.txt).",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=str(here / "webster.json"),
        help="Output JSON file path (default: webster.json).",
    )
    parser.add_argument(
        "--encoding",
        default="auto",
        help=(
            "Input file encoding. Use 'auto' to try utf-8-sig then mac_roman "
            "(default: auto)."
        ),
    )
    parser.add_argument(
        "--sort-into-alpha-arrays",
        action="store_true",
        help="Store data as 26 dictionaries grouped by first letter.",
    )
    parser.add_argument(
        "--progress-step",
        type=float,
        default=5.0,
        help="Progress report interval in percent (default: 5).",
    )
    parser.add_argument(
        "--min-definition-length",
        type=int,
        default=4,
        help=(
            "Drop entries with stripped definitions shorter than this length "
            "(default: 4)."
        ),
    )
    parser.add_argument(
        "--keep-short-definitions",
        action="store_true",
        help="Keep short definitions and skip cleanup length filtering.",
    )
    return parser.parse_args()


def has_itemized_definition_prefix(text: str) -> bool:
    return text.startswith(DEFINITION_ITEM_PREFIX_NUMERICAL) or text.startswith(
        DEFINITION_ITEM_PREFIX_ALPHABETIZED
    )


def continue_definition(definition: str | None, text: str) -> str:
    if definition is None:
        return text
    if definition.endswith(" "):
        return definition + text
    return definition + " " + text


def finish_current_word(
    compiled_dictionary: dict[str, str] | list[dict[str, str]],
    current_word: str | None,
    definition: str | None,
    word_trimming_characters: str,
    sort_into_alpha_arrays: bool,
) -> None:
    if current_word is not None and definition is not None:
        cleaned_definition = definition.strip()
        all_words = current_word.split(";")

        for a_word in all_words:
            cleaned_word = a_word.strip(word_trimming_characters).lower()
            if not cleaned_word:
                continue

            if sort_into_alpha_arrays and isinstance(compiled_dictionary, list):
                ascii_value = ord(cleaned_word[0]) - ord("a")
                if ascii_value < 0 or ascii_value >= 26:
                    raise ValueError(
                        f"Unexpected unicode value for first character of word {cleaned_word}"
                    )

                bucket = cast(list[dict[str, str]], compiled_dictionary)[ascii_value]
                if cleaned_word not in bucket:
                    bucket[cleaned_word] = cleaned_definition
                else:
                    bucket[cleaned_word] = (
                        bucket[cleaned_word] + "\n\n" + cleaned_definition
                    )
            else:
                dictionary = cast(dict[str, str], compiled_dictionary)
                if cleaned_word not in dictionary:
                    dictionary[cleaned_word] = cleaned_definition
                else:
                    dictionary[cleaned_word] = (
                        dictionary[cleaned_word] + "\n\n" + cleaned_definition
                    )
    elif current_word is not None and definition is None and not sort_into_alpha_arrays:
        dictionary = cast(dict[str, str], compiled_dictionary)
        if current_word not in dictionary:
            print(f"No definition found for '{current_word}'")


def build_dictionary(
    file_text: str, progress_step: float, sort_into_alpha_arrays: bool
) -> dict[str, str] | list[dict[str, str]]:
    allowable_word_definition_characters = (
        ASCII_ALPHA_UPPERCASE + MULTI_WORD_DEFINITION_SEPARATOR
    )
    allowed_character_set = set(allowable_word_definition_characters)
    word_trimming_characters = " \t\r\n-"

    if sort_into_alpha_arrays:
        compiled_dictionary: dict[str, str] | list[dict[str, str]] = [
            {} for _ in range(26)
        ]
    else:
        compiled_dictionary = {}

    total_dictionary_length = len(file_text)
    consumed = 0
    last_progress_report = 0.0

    current_word: str | None = None
    definition: str | None = None

    for raw_line in file_text.splitlines(keepends=True):
        line_text = raw_line.rstrip("\r\n")

        is_word = bool(line_text.strip()) and all(
            character in allowed_character_set for character in line_text
        )

        if is_word:
            finish_current_word(
                compiled_dictionary,
                current_word,
                definition,
                word_trimming_characters,
                sort_into_alpha_arrays,
            )
            current_word = line_text
            definition = None
        elif line_text.startswith(DEFINITION_PREFIX):
            cleaned_text = line_text[5:]
            definition = continue_definition(definition, cleaned_text)
        elif has_itemized_definition_prefix(line_text):
            definition = continue_definition(definition, line_text)
        elif definition is not None:
            definition = continue_definition(definition, line_text)

        consumed += len(raw_line)
        if progress_step > 0 and total_dictionary_length > 0:
            calculated_percent_complete = 100.0 * (consumed / total_dictionary_length)
            if calculated_percent_complete > last_progress_report + progress_step:
                print(f"Progress: {int(calculated_percent_complete)}%")
                last_progress_report = calculated_percent_complete

    finish_current_word(
        compiled_dictionary,
        current_word,
        definition,
        word_trimming_characters,
        sort_into_alpha_arrays,
    )

    return compiled_dictionary


def clean_dictionary(
    compiled_dictionary: dict[str, str] | list[dict[str, str]],
    min_definition_length: int,
    keep_short_definitions: bool,
) -> int:
    if keep_short_definitions:
        return 0

    removed = 0

    def should_drop(definition: str) -> bool:
        stripped = definition.strip()
        if not stripped:
            return True
        if len(stripped) < min_definition_length:
            return True
        if not any(character.isalnum() for character in stripped):
            return True
        return False

    if isinstance(compiled_dictionary, list):
        for bucket in compiled_dictionary:
            drop_keys = [key for key, value in bucket.items() if should_drop(value)]
            for key in drop_keys:
                del bucket[key]
            removed += len(drop_keys)
    else:
        drop_keys = [
            key for key, value in compiled_dictionary.items() if should_drop(value)
        ]
        for key in drop_keys:
            del compiled_dictionary[key]
        removed += len(drop_keys)

    return removed


def read_input_text(input_path: Path, encoding: str) -> str:
    if encoding != "auto":
        return input_path.read_text(encoding=encoding)

    last_error: UnicodeDecodeError | None = None
    for candidate in ("utf-8-sig", "mac_roman"):
        try:
            return input_path.read_text(encoding=candidate)
        except UnicodeDecodeError as error:
            last_error = error

    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to decode input file.")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    file_text = read_input_text(input_path, args.encoding)
    compiled_dictionary = build_dictionary(
        file_text=file_text,
        progress_step=args.progress_step,
        sort_into_alpha_arrays=args.sort_into_alpha_arrays,
    )

    removed_count = clean_dictionary(
        compiled_dictionary,
        min_definition_length=args.min_definition_length,
        keep_short_definitions=args.keep_short_definitions,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_handle:
        json.dump(compiled_dictionary, output_handle, indent=2, ensure_ascii=False)
        output_handle.write("\n")

    if removed_count > 0:
        print(f"Removed {removed_count} entries during cleanup")
    print(f"Finished. Output saved to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

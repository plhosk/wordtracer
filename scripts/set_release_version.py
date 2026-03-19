from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update app and F-Droid release version fields in one step."
    )
    parser.add_argument("version", help="Version string, e.g. 1.0.2")
    parser.add_argument(
        "--version-code",
        type=int,
        default=0,
        help="Explicit Android/F-Droid versionCode (default: increment current).",
    )
    parser.add_argument(
        "--no-update-commit-tag",
        action="store_true",
        help="Do not update metadata commit tag.",
    )
    parser.add_argument(
        "--tag-format",
        default="v{version}",
        help="Tag format used for metadata commit when enabled.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing files.",
    )
    return parser.parse_args()


def replace_first(pattern: str, replacement: str, content: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update {label}")
    return updated


def parse_first_int(pattern: str, content: str, label: str) -> int:
    match = re.search(pattern, content, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"Could not read {label}")
    return int(match.group(1))


def main() -> None:
    args = parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit("Version must look like X.Y.Z")

    gradle_path = project_path("android", "app", "build.gradle")
    metadata_path = project_path("metadata", "com.wordtracer.app.yml")
    package_json_path = project_path("package.json")

    gradle_content = gradle_path.read_text(encoding="utf-8")
    metadata_content = metadata_path.read_text(encoding="utf-8")
    package_json_content = package_json_path.read_text(encoding="utf-8")

    gradle_code = parse_first_int(
        r"^\s*versionCode\s+(\d+)\s*$", gradle_content, "Gradle versionCode"
    )
    metadata_code = parse_first_int(
        r"^\s*CurrentVersionCode:\s*(\d+)\s*$",
        metadata_content,
        "metadata CurrentVersionCode",
    )

    if args.version_code > 0:
        new_code = args.version_code
    else:
        new_code = max(gradle_code, metadata_code) + 1

    updated_gradle = gradle_content
    updated_gradle = replace_first(
        r"^(\s*versionCode\s+)\d+(\s*)$",
        rf"\g<1>{new_code}\g<2>",
        updated_gradle,
        "Gradle versionCode",
    )
    updated_gradle = replace_first(
        r'^(\s*versionName\s+")([^"]+)("\s*)$',
        rf"\g<1>{args.version}\g<3>",
        updated_gradle,
        "Gradle versionName",
    )

    updated_metadata = metadata_content
    updated_metadata = replace_first(
        r"^(\s*-\s*versionName:\s*).*(\s*)$",
        rf"\g<1>{args.version}\g<2>",
        updated_metadata,
        "metadata build versionName",
    )
    updated_metadata = replace_first(
        r"^(\s*versionCode:\s*)\d+(\s*)$",
        rf"\g<1>{new_code}\g<2>",
        updated_metadata,
        "metadata build versionCode",
    )
    updated_metadata = replace_first(
        r"^(\s*CurrentVersion:\s*).*(\s*)$",
        rf"\g<1>{args.version}\g<2>",
        updated_metadata,
        "metadata CurrentVersion",
    )
    updated_metadata = replace_first(
        r"^(\s*CurrentVersionCode:\s*)\d+(\s*)$",
        rf"\g<1>{new_code}\g<2>",
        updated_metadata,
        "metadata CurrentVersionCode",
    )

    if not args.no_update_commit_tag:
        tag = args.tag_format.format(version=args.version)
        updated_metadata = replace_first(
            r"^(\s*commit:\s*).*(\s*)$",
            rf"\g<1>{tag}\g<2>",
            updated_metadata,
            "metadata commit",
        )

    updated_package_json = replace_first(
        r'^(\s*"version"\s*:\s*")[^"]+("\s*,\s*)$',
        rf"\g<1>{args.version}\g<2>",
        package_json_content,
        "package.json version",
    )

    print(f"Version: {args.version}")
    print(f"Version code: {new_code}")
    print(f"Gradle: {gradle_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Package JSON: {package_json_path}")

    if args.dry_run:
        print("Dry run: no files written")
        return

    gradle_path.write_text(updated_gradle, encoding="utf-8")
    metadata_path.write_text(updated_metadata, encoding="utf-8")
    package_json_path.write_text(updated_package_json, encoding="utf-8")
    print("Updated release version fields")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import re
import subprocess

from common import project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize local F-Droid metadata commit to a git hash."
    )
    parser.add_argument("version", help="Release version (X.Y.Z)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing files.",
    )
    return parser.parse_args()


def must_match(pattern: str, content: str, label: str) -> str:
    match = re.search(pattern, content, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"Could not read {label}")
    return match.group(1)


def has_match(pattern: str, content: str) -> bool:
    return re.search(pattern, content, flags=re.MULTILINE) is not None


def read_versions() -> tuple[str, str, int, str, int, str, int]:
    package_path = project_path("package.json")
    gradle_path = project_path("android", "app", "build.gradle")
    metadata_path = project_path("metadata", "com.wordtracer.app.yml")

    package_payload = json.loads(package_path.read_text(encoding="utf-8"))
    package_version = str(package_payload.get("version", "")).strip()
    if not package_version:
        raise SystemExit("package.json missing version")

    gradle_content = gradle_path.read_text(encoding="utf-8")
    gradle_version = must_match(
        r'^\s*versionName\s+"([^"]+)"\s*$', gradle_content, "Gradle versionName"
    )
    gradle_code = int(
        must_match(r"^\s*versionCode\s+(\d+)\s*$", gradle_content, "Gradle versionCode")
    )

    metadata_content = metadata_path.read_text(encoding="utf-8")
    metadata_build_version = must_match(
        r"^\s*-\s*versionName:\s*(\S+)\s*$",
        metadata_content,
        "metadata Builds versionName",
    )
    build_code_match = re.search(
        r"^\s*versionCode:\s*(\d+)\s*$", metadata_content, flags=re.MULTILINE
    )
    if not build_code_match:
        raise SystemExit("Could not read metadata Builds versionCode")
    metadata_build_code = int(build_code_match.group(1))
    metadata_current_version = must_match(
        r"^\s*CurrentVersion:\s*(\S+)\s*$",
        metadata_content,
        "metadata CurrentVersion",
    )
    metadata_current_code = int(
        must_match(
            r"^\s*CurrentVersionCode:\s*(\d+)\s*$",
            metadata_content,
            "metadata CurrentVersionCode",
        )
    )

    return (
        package_version,
        gradle_version,
        gradle_code,
        metadata_build_version,
        metadata_build_code,
        metadata_current_version,
        metadata_current_code,
    )


def resolve_tag_commit(version: str) -> tuple[str, str]:
    tag = f"v{version}"
    result = subprocess.run(
        ["git", "rev-parse", f"{tag}^{{commit}}"],
        cwd=project_path(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Could not resolve tag {tag} to a commit hash")
    commit_hash = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_hash):
        raise SystemExit(f"Resolved commit for {tag} is not a 40-char git hash")
    return tag, commit_hash


def main() -> None:
    args = parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit("Version must look like X.Y.Z")

    (
        package_version,
        gradle_version,
        gradle_code,
        metadata_build_version,
        metadata_build_code,
        metadata_current_version,
        metadata_current_code,
    ) = read_versions()

    version_fields = {
        "package.json": package_version,
        "android/app/build.gradle": gradle_version,
        "metadata Builds.versionName": metadata_build_version,
        "metadata CurrentVersion": metadata_current_version,
    }
    code_fields = {
        "android/app/build.gradle": gradle_code,
        "metadata Builds.versionCode": metadata_build_code,
        "metadata CurrentVersionCode": metadata_current_code,
    }

    mismatched_versions = {
        name: value for name, value in version_fields.items() if value != args.version
    }
    if mismatched_versions:
        details = ", ".join(
            f"{name}={value}" for name, value in mismatched_versions.items()
        )
        raise SystemExit(
            "Version fields are not aligned to requested version "
            f"{args.version}: {details}. Run `npm run release:set-version -- {args.version}` first."
        )

    unique_codes = sorted(set(code_fields.values()))
    if len(unique_codes) != 1:
        details = ", ".join(f"{name}={value}" for name, value in code_fields.items())
        raise SystemExit(
            "Version codes are not aligned across files: "
            f"{details}. Run `npm run release:set-version -- {args.version}` first."
        )

    version_code = unique_codes[0]
    metadata_path = project_path("metadata", "com.wordtracer.app.yml")
    metadata_text = metadata_path.read_text(encoding="utf-8")
    previous_commit = must_match(
        r"^\s*commit:\s*(\S+)\s*$", metadata_text, "metadata commit"
    )
    tag, commit_hash = resolve_tag_commit(args.version)
    updated_metadata_text = re.sub(
        r"^(\s*commit:\s*).*(\s*)$",
        rf"\g<1>{commit_hash}\g<2>",
        metadata_text,
        count=1,
        flags=re.MULTILINE,
    )
    changed = updated_metadata_text != metadata_text

    print(f"Release version: {args.version}")
    print(f"Release code: {version_code}")
    print(f"Metadata: {metadata_path}")
    print(f"Tag: {tag}")
    print(f"Previous metadata commit: {previous_commit}")
    print(f"Resolved commit hash: {commit_hash}")
    print(f"Metadata changed: {'yes' if changed else 'no'}")

    warnings: list[str] = []
    has_binaries = has_match(r"^\s*Binaries:\s*\S+\s*$", metadata_text)
    has_build_binary = has_match(r"^\s*binary:\s*\S+\s*$", metadata_text)
    if not has_binaries and not has_build_binary:
        warnings.append(
            "metadata missing Binaries/build binary URL for reproducible upstream verification"
        )
    if not has_match(r"^\s*AllowedAPKSigningKeys:\s*(?:\S.*)?$", metadata_text):
        warnings.append("metadata missing AllowedAPKSigningKeys")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if args.dry_run:
        print("Dry run: metadata not updated")
        return

    if changed:
        metadata_path.write_text(updated_metadata_text, encoding="utf-8")
        print("Updated metadata commit to git hash")
    else:
        print("Metadata already uses this git hash")


if __name__ == "__main__":
    main()

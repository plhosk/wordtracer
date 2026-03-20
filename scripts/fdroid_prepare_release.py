from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from common import project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare F-Droid metadata for a release without pushing any changes."
        )
    )
    parser.add_argument("version", help="Release version (X.Y.Z)")
    parser.add_argument(
        "--fdroiddata",
        required=True,
        help="Path to local fdroiddata checkout.",
    )
    parser.add_argument(
        "--application-id",
        default="com.wordtracer.app",
        help="F-Droid application id / metadata file stem.",
    )
    parser.add_argument(
        "--fdroidserver",
        required=True,
        help="Path to local fdroidserver checkout used to run fdroid via uv.",
    )
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


def check_local_tag_exists(version: str) -> bool:
    tag = f"v{version}"
    result = subprocess.run(
        ["git", "tag", "--list", tag],
        cwd=project_path(),
        check=False,
        capture_output=True,
        text=True,
    )
    return tag in result.stdout.split()


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
    source_metadata = project_path("metadata", "com.wordtracer.app.yml")
    fdroiddata_root = Path(args.fdroiddata).expanduser().resolve()
    fdroidserver_root = Path(args.fdroidserver).expanduser().resolve()
    if not fdroiddata_root.exists() or not fdroiddata_root.is_dir():
        raise SystemExit(f"fdroiddata path not found: {fdroiddata_root}")
    if not fdroidserver_root.exists() or not fdroidserver_root.is_dir():
        raise SystemExit(f"fdroidserver path not found: {fdroidserver_root}")
    target_metadata = fdroiddata_root / "metadata" / f"{args.application_id}.yml"
    if not target_metadata.parent.exists() or not target_metadata.parent.is_dir():
        raise SystemExit(
            f"fdroiddata metadata directory not found: {target_metadata.parent}"
        )

    source_text = source_metadata.read_text(encoding="utf-8")
    target_exists = target_metadata.exists()
    target_text = target_metadata.read_text(encoding="utf-8") if target_exists else ""
    changed = source_text != target_text

    print(f"Release version: {args.version}")
    print(f"Release code: {version_code}")
    print(f"Source metadata: {source_metadata}")
    print(f"Target metadata: {target_metadata}")
    print(f"fdroidserver: {fdroidserver_root}")
    print(f"Metadata changed: {'yes' if changed else 'no'}")

    if not args.dry_run and changed:
        target_metadata.write_text(source_text, encoding="utf-8")
        print("Copied metadata into fdroiddata checkout")
    elif args.dry_run:
        print("Dry run: metadata not copied")

    tag = f"v{args.version}"
    has_local_tag = check_local_tag_exists(args.version)
    if has_local_tag:
        print(f"Local tag exists: {tag}")
    else:
        print(f"Local tag missing: {tag}")

    branch_name = f"update-wordtracer-{args.version}"
    print("\nNext commands (not run):")
    print(f"  cd {project_path()}")
    print("  git status")
    if not has_local_tag:
        print(f'  git tag -a {tag} -m "Release {tag}"')
    print("  git push origin <your-branch>")
    print(f"  git push origin {tag}")
    print(f"  cd {fdroiddata_root}")
    print(f"  git checkout -b {branch_name}")
    print(
        "  "
        f"uv run --project {fdroidserver_root} --directory {fdroiddata_root} "
        f"fdroid lint {args.application_id}"
    )
    print(
        "  "
        f"uv run --project {fdroidserver_root} --directory {fdroiddata_root} "
        f"fdroid checkupdates --allow-dirty {args.application_id}"
    )
    print(
        "  "
        f"uv run --project {fdroidserver_root} --directory {fdroiddata_root} "
        f"fdroid build -v -l {args.application_id}"
    )
    print(f"  git add metadata/{args.application_id}.yml")
    print(f'  git commit -m "Update Word Tracer to {args.version} ({version_code})"')
    print(f"  git push -u origin {branch_name}")


if __name__ == "__main__":
    main()

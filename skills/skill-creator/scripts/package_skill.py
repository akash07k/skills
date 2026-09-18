#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""
Skill Packager - Creates a distributable .skill file (zip) of a skill folder.

Usage:
    python scripts/package_skill.py <path/to/skill-folder> [output-directory]

Example:
    python scripts/package_skill.py skills/my-skill
    python scripts/package_skill.py skills/my-skill ./dist

Without an output directory, <skill-name>.skill is written to the skill
folder's parent folder. The skill is validated first; invalid skills are not
packaged. Symlinks, junctions, dotfiles/dot-directories, caches and
development folders are skipped and listed on stderr with a reason.
Exit codes: 0 packaged, 1 error, 2 usage error.
"""

import argparse
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

if sys.version_info < (3, 13):
    sys.exit("skill-creator scripts require Python 3.13 or later.")

if not __package__:
    # Allow `python <skill>/scripts/<name>.py` from any working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.quick_validate import check_skill
from scripts.utils import ensure_utf8_stdio

# Directory names excluded anywhere in the tree (compared case-insensitively).
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".pytest_cache"}
# Directories excluded only at the skill root (compared case-insensitively).
ROOT_EXCLUDE_DIRS = {
    "evals", "logs", "playwright-report", "skill-creator-results", "test-results", "tests",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".skill"}


def _is_link_or_junction(path: str) -> bool:
    """True for symlinks, Windows junctions and other reparse points."""
    if os.path.islink(path) or os.path.isjunction(path):
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _dir_exclusion_reason(name: str, at_root: bool) -> str | None:
    lowered = name.lower()
    if lowered.startswith("."):
        return "hidden folder"
    if lowered in EXCLUDE_DIRS:
        return "cache or tool folder"
    if lowered.endswith("-workspace"):
        return "workspace folder"
    if at_root and lowered in ROOT_EXCLUDE_DIRS:
        return "development folder"
    return None


def _file_exclusion_reason(name: str) -> str | None:
    lowered = name.lower()
    if lowered.startswith("."):
        return "hidden file"
    suffix = os.path.splitext(lowered)[1]
    if suffix in EXCLUDE_SUFFIXES:
        return f"{suffix} file"
    return None


def _exclude_dir(name: str, at_root: bool) -> bool:
    return _dir_exclusion_reason(name, at_root) is not None


def _exclude_file(name: str) -> bool:
    return _file_exclusion_reason(name) is not None


def should_exclude(rel_path: Path) -> bool:
    """Check whether a path relative to the skill's parent folder is excluded."""
    parts = rel_path.parts
    if any(_exclude_dir(part, at_root=False) for part in parts[1:-1]):
        return True
    if len(parts) > 2 and _exclude_dir(parts[1], at_root=True):
        return True
    return _exclude_file(rel_path.name)


def collect_files(
    skill_root: Path, skip_paths=()
) -> tuple[list[tuple[Path, str]], list[tuple[str, str]]]:
    """Return ([(file, relative posix path)], [(skipped relative path, reason)]).

    Links are never followed. Skipped folders end with "/" and are not entered.
    """
    skip = {os.path.normcase(os.path.abspath(p)) for p in skip_paths}
    files: list[tuple[Path, str]] = []
    skipped: list[tuple[str, str]] = []

    def relative(full: str) -> str:
        return Path(full).relative_to(skill_root).as_posix()

    for dirpath, dirnames, filenames in os.walk(skill_root, followlinks=False):
        at_root = os.path.normcase(dirpath) == os.path.normcase(str(skill_root))
        kept = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(full)) in skip:
                reason = "package output"
            elif _is_link_or_junction(full):
                reason = "symlink or junction"
            else:
                reason = _dir_exclusion_reason(name, at_root)
            if reason:
                skipped.append((relative(full) + "/", reason))
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(full)) in skip:
                reason = "package output"
            elif _is_link_or_junction(full):
                reason = "symlink or junction"
            elif not os.path.isfile(full):
                reason = "not a regular file"
            else:
                reason = _file_exclusion_reason(name)
            if reason:
                skipped.append((relative(full), reason))
                continue
            files.append((Path(full), relative(full)))
    return files, skipped


def _error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def package_skill(skill_path, output_dir=None):
    """
    Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder (may itself be a symlink)
        output_dir: Optional output directory for the .skill file (defaults to
            the skill folder's parent folder)

    Returns:
        Path to the created .skill file, or None if error
    """
    given_path = Path(skill_path)
    skill_name = os.path.basename(os.path.normpath(os.path.abspath(given_path)))
    skill_root = given_path.resolve()

    if not skill_root.exists():
        _error(f"Skill folder not found: {given_path}")
        return None
    if not skill_root.is_dir():
        _error(f"Path is not a directory: {given_path}")
        return None
    if not (skill_root / "SKILL.md").is_file():
        _error(f"SKILL.md not found in {given_path}")
        return None

    print("Validating skill...")
    result = check_skill(given_path)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not result.valid:
        for message in result.errors:
            print(f"error: {message}", file=sys.stderr)
        _error("validation failed; fix the errors above before packaging.")
        return None
    print("Skill is valid!\n")

    temporary_path = None
    try:
        output_path = (
            Path(output_dir).resolve() if output_dir
            else Path(os.path.abspath(given_path)).parent
        )
        output_path.mkdir(parents=True, exist_ok=True)
        skill_filename = output_path / f"{skill_name}.skill"
        with tempfile.NamedTemporaryFile(
            dir=output_path, prefix=f".{skill_name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        skip_paths = [temporary_path]
        if output_path != skill_root and output_path.is_relative_to(skill_root):
            skip_paths.append(output_path)
        files, skipped = collect_files(skill_root, skip_paths)
        with zipfile.ZipFile(
            temporary_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False
        ) as archive:
            for file_path, relative in files:
                arcname = f"{skill_name}/{relative}"
                archive.write(file_path, arcname)
                print(f"  Added: {arcname}")
        temporary_relative = (
            temporary_path.relative_to(skill_root).as_posix()
            if temporary_path.is_relative_to(skill_root) else None
        )
        skipped = [item for item in skipped if item[0] != temporary_relative]
        if skipped:
            print(f"Skipped {len(skipped)} excluded path(s):", file=sys.stderr)
            for relative, reason in skipped:
                print(f"  {relative} ({reason})", file=sys.stderr)
        os.replace(temporary_path, skill_filename)
        temporary_path = None
        print(f"\nSuccessfully packaged skill to: {skill_filename}")
        return skill_filename
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        _error(f"could not create .skill file: {error}")
        return None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv=None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="python scripts/package_skill.py",
        description="Validate a skill folder and package it into a distributable .skill (zip) file.",
        epilog="Exit codes: 0 packaged, 1 error, 2 usage error.",
    )
    parser.add_argument("skill_path", help="path to the skill folder (containing SKILL.md)")
    parser.add_argument(
        "output_dir", nargs="?", default=None,
        help="directory for the .skill file (default: the skill folder's parent folder)",
    )
    args = parser.parse_args(argv)

    print(f"Packaging skill: {args.skill_path}")
    if args.output_dir:
        print(f"   Output directory: {args.output_dir}")
    print()
    return 0 if package_skill(args.skill_path, args.output_dir) else 1


if __name__ == "__main__":
    sys.exit(main())

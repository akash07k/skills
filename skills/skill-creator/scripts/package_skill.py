#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["ruamel.yaml==0.19.0"]
# ///
"""
Skill Packager - Creates a distributable .skill file (zip) of a skill folder.

Usage:
    uv run scripts/package_skill.py <skill-folder> [output-directory] [--target CLIENT]

Example:
    uv run scripts/package_skill.py skills/my-skill
    uv run scripts/package_skill.py skills/my-skill ./dist

Without an output directory, <skill-name>.skill is written to the skill
folder's parent folder. Both local and agnix validation must pass. Referenced
hidden files are checked for sensitive content; ambiguous files require
explicit review. Other dotfiles, caches and development folders are skipped.
Exit codes: 0 packaged, 1 error, 2 usage error.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

if sys.version_info < (3, 13):
    sys.exit("skill-creator scripts require Python 3.13 or later.")

if not __package__:
    # Allow `python <skill>/scripts/<name>.py` from any working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.quick_validate import CLIENT_PROPERTIES, body_reference_targets, check_skill
from scripts.utils import ensure_utf8_stdio, load_frontmatter

# Directory names excluded anywhere in the tree (compared case-insensitively).
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".pytest_cache"}
# Directories excluded only at the skill root (compared case-insensitively).
ROOT_EXCLUDE_DIRS = {
    "evals", "logs", "playwright-report", "skill-creator-results", "test-results", "tests",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".skill"}
SENSITIVE_NAMES = {".env", ".ssh", ".aws", ".git", ".npmrc", ".pypirc", ".netrc"}
SENSITIVE_CONTENT = re.compile(
    r"(?i)(?:-----BEGIN [^-]*PRIVATE KEY-----|"
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\b(?:password|secret|token|api[_-]?key)\b\s*[:=]\s*['\"]?[^\s'\"<>${}]+)"
)
RESOURCE_PATH = re.compile(r"(?<![A-Za-z0-9_/\\])(?:assets|references|scripts)[/\\][A-Za-z0-9_./\\-]+")


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

    Skipped folders end with "/" and are not entered.
    """
    skip = {os.path.normcase(os.path.abspath(p)) for p in skip_paths}
    files: list[tuple[Path, str]] = []
    skipped: list[tuple[str, str]] = []

    def relative(full: str) -> str:
        return Path(full).relative_to(skill_root).as_posix()

    for dirpath, dirnames, filenames in os.walk(skill_root, followlinks=True):
        at_root = os.path.normcase(dirpath) == os.path.normcase(str(skill_root))
        kept = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(full)) in skip:
                reason = "package output"
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


def _validate_agnix(skill_md: Path, target: str | None) -> bool:
    command = [
        "uvx", "--refresh-package", "agnix", "agnix@latest",
        "--strict", "--format", "json",
    ]
    if target in ("claude-code", "codex"):
        command.extend(["--target", target])
    command.append(str(skill_md))
    sidecar = skill_md.parent / "agents" / "openai.yaml"
    expected_files = 1
    if target == "codex" and sidecar.is_file():
        command.append(str(sidecar))
        expected_files += 1
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        _error(f"agnix validation could not run: {error}")
        return False
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        _error(f"agnix validation failed: {detail}")
        return False
    try:
        report = json.loads(result.stdout)
        summary = report["summary"]
        valid = (
            type(report.get("files_checked")) is int
            and report["files_checked"] >= expected_files
            and type(summary.get("errors")) is int and summary["errors"] == 0
            and type(summary.get("warnings")) is int and summary["warnings"] == 0
            and isinstance(report.get("version"), str) and report["version"]
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        _error(f"agnix returned an invalid report: {error}")
        return False
    if not valid:
        if type(report.get("files_checked")) is int and report["files_checked"] < expected_files:
            _error(
                f"agnix checked {report['files_checked']} of {expected_files} requested files; "
                "for Codex sidecars, use a native .agents/skills location."
            )
            return False
        _error(f"agnix validation failed: {result.stderr.strip() or result.stdout.strip()}")
        return False
    print(f"Agnix {report['version']} validated {skill_md}.")
    return True


def _referenced_hidden_files(
    skill_root: Path, reviewed_hidden: tuple[str, ...] = (),
) -> tuple[list[tuple[Path, str]], set[str]]:
    content = (skill_root / "SKILL.md").read_text(encoding="utf-8-sig")
    pending = [(skill_root / "SKILL.md", load_frontmatter(content).body)]
    seen_documents = set()
    selected = []
    required = set()
    reviewed = {Path(path).as_posix() for path in reviewed_hidden}
    found = set()
    while pending:
        document, body = pending.pop()
        if document in seen_documents:
            continue
        seen_documents.add(document)
        references = body_reference_targets(body)
        references.extend((match.group(0), "File reference") for match in RESOURCE_PATH.finditer(body))
        for target, _ in references:
            if re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|[/\\#])", target):
                continue
            path_text = unquote(target.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
            relative = Path(path_text)
            rooted = relative.parts and relative.parts[0] in ("assets", "references", "scripts")
            lexical = Path(os.path.abspath((skill_root if rooted else document.parent) / relative))
            full = lexical.resolve()
            hidden = any(part.startswith(".") and part not in (".", "..") for part in relative.parts)
            if not lexical.is_relative_to(skill_root) or not full.is_relative_to(skill_root):
                if hidden:
                    raise ValueError(f"referenced hidden file is outside the skill: {target}")
                continue
            normalized = lexical.relative_to(skill_root).as_posix()
            if full.is_file():
                required.add(normalized)
            hidden = hidden or any(part.startswith(".") for part in Path(normalized).parts)
            if not hidden:
                if full.suffix.lower() == ".md" and full.is_file():
                    pending.append((full, full.read_text(encoding="utf-8-sig")))
                continue
            if normalized in found:
                continue
            found.add(normalized)
            if any(
                part.lower() in SENSITIVE_NAMES
                or part.lower().startswith(".env.")
                or part.lower().endswith((".key", ".pem", ".p12"))
                for part in (*Path(normalized).parts, *full.relative_to(skill_root).parts)
            ):
                raise ValueError(f"referenced hidden file may contain secrets; review it before packaging: {target}")
            if not full.is_file():
                raise ValueError(f"referenced hidden file does not exist: {target}")
            try:
                text = full.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                if normalized not in reviewed:
                    raise ValueError(
                        f"referenced hidden file is not UTF-8 text; obtain user review and use "
                        f"--reviewed-hidden {normalized}: {target}"
                    ) from error
                selected.append((full, normalized))
                continue
            if SENSITIVE_CONTENT.search(text):
                raise ValueError(f"referenced hidden file may contain secrets; review it before packaging: {target}")
            if "\x00" in text and normalized not in reviewed:
                raise ValueError(
                    f"referenced hidden file contains binary data; obtain user review and use "
                    f"--reviewed-hidden {normalized}: {target}"
                )
            selected.append((full, normalized))
            if full.suffix.lower() == ".md":
                pending.append((full, text))
    missing = reviewed - found
    if missing:
        raise ValueError(f"reviewed hidden files are not explicitly referenced: {', '.join(sorted(missing))}")
    return selected, required


def package_skill(
    skill_path, output_dir=None, target: str | None = None,
    reviewed_hidden: tuple[str, ...] = (),
):
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
    selected_target = target or "portable"
    result = check_skill(given_path, target=selected_target)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not result.valid:
        for message in result.errors:
            print(f"error: {message}", file=sys.stderr)
        _error("validation failed; fix the errors above before packaging.")
        return None
    if not _validate_agnix(skill_root / "SKILL.md", selected_target):
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
        if output_path != skill_root:
            skip_paths.append(output_path)
        files, skipped = collect_files(skill_root, skip_paths)
        hidden, required = _referenced_hidden_files(skill_root, reviewed_hidden)
        existing = {relative for _, relative in files}
        for path, relative in hidden:
            if relative not in existing:
                files.append((path, relative))
                existing.add(relative)
        omitted = sorted(required - existing)
        if omitted:
            raise ValueError(f"referenced resources would be excluded: {', '.join(omitted)}")
        skipped = [
            (path, "unreferenced contents excluded")
            if path.endswith("/") and any(relative.startswith(path) for _, relative in hidden)
            else (path, reason)
            for path, reason in skipped if path.rstrip("/") not in existing
        ]
        if not any(relative == "SKILL.md" for _, relative in files):
            raise ValueError("Package has no SKILL.md entry point")
        with zipfile.ZipFile(
            temporary_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False
        ) as archive:
            for file_path, relative in files:
                arcname = f"{skill_name}/{relative}"
                archive.write(file_path, arcname)
                print(f"  Added: {arcname}")
        temporary_relative = temporary_path.name if output_path == skill_root else None
        skipped = [item for item in skipped if item[0] != temporary_relative]
        if skipped:
            print(f"Skipped {len(skipped)} excluded path(s):", file=sys.stderr)
            for relative, reason in skipped:
                print(f"  {relative} ({reason})", file=sys.stderr)
        os.replace(temporary_path, skill_filename)
        temporary_path = None
        print(f"\nSuccessfully packaged skill to: {skill_filename}")
        return skill_filename
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
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
    parser.add_argument(
        "--target", choices=sorted(CLIENT_PROPERTIES),
        help="validate fields for the selected client",
    )
    parser.add_argument(
        "--reviewed-hidden", action="append", default=[], metavar="PATH",
        help="include an explicitly referenced ambiguous hidden file after user review; repeatable",
    )
    args = parser.parse_args(argv)

    print(f"Packaging skill: {args.skill_path}")
    if args.output_dir:
        print(f"   Output directory: {args.output_dir}")
    print()
    return 0 if package_skill(
        args.skill_path, args.output_dir, target=args.target,
        reviewed_hidden=tuple(args.reviewed_hidden),
    ) else 1


if __name__ == "__main__":
    sys.exit(main())

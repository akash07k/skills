#!/usr/bin/env python3
"""
Skill Packager - Creates a distributable .skill file of a skill folder

Usage:
    python -m scripts.package_skill <path/to/skill-folder> [output-directory]

Example:
    python -m scripts.package_skill skills/public/my-skill
    python -m scripts.package_skill skills/public/my-skill ./dist
"""

import sys
import tempfile
import zipfile
from pathlib import Path
from scripts.quick_validate import validate_skill

# Patterns to exclude when packaging skills.
EXCLUDE_DIRS = {".git", ".pytest_cache", "__pycache__", "node_modules"}
# Directories excluded only at the skill root (not when nested deeper).
ROOT_EXCLUDE_DIRS = {
    "evals", "logs", "playwright-report", "skill-creator-results", "test-results", "tests",
}


def should_exclude(rel_path: Path) -> bool:
    """Check if a path should be excluded from packaging."""
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    # rel_path is relative to skill_path.parent, so parts[0] is the skill
    # folder name and parts[1] (if present) is the first subdir.
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True
    return rel_path.name == ".DS_Store" or rel_path.suffix in {".log", ".pyc", ".skill"}


def package_skill(skill_path, output_dir=None):
    """
    Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory for the .skill file (defaults to current directory)

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_path.exists():
        print(f"Error: Skill folder not found: {skill_path}")
        return None

    if not skill_path.is_dir():
        print(f"Error: Path is not a directory: {skill_path}")
        return None

    # Validate SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"Error: SKILL.md not found in {skill_path}")
        return None

    # Run validation before packaging
    print("Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"Validation failed: {message}")
        print("   Please fix the validation errors before packaging.")
        return None
    print(f"{message}\n")

    # Determine output location
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"
    temporary_path = None

    # Create the .skill file (zip format)
    try:
        skipped = 0
        output_is_nested = output_path != skill_path and output_path.is_relative_to(skill_path)
        with tempfile.NamedTemporaryFile(
            dir=output_path, prefix=f".{skill_name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(temporary_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Walk through the skill directory, excluding build artifacts
            for file_path in skill_path.rglob('*'):
                if not file_path.is_file():
                    continue
                arcname = file_path.relative_to(skill_path.parent)
                if file_path == temporary_path or should_exclude(arcname) or (
                    output_is_nested and file_path.is_relative_to(output_path)
                ):
                    skipped += 1
                    continue
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")

        if skipped:
            print(f"  Skipped {skipped} excluded file(s).")
        temporary_path.replace(skill_filename)
        temporary_path = None
        print(f"\nSuccessfully packaged skill to: {skill_filename}")
        return skill_filename

    except Exception as e:
        print(f"Error creating .skill file: {e}")
        return None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.package_skill <path/to/skill-folder> [output-directory]")
        print("\nExample:")
        print("  python -m scripts.package_skill skills/public/my-skill")
        print("  python -m scripts.package_skill skills/public/my-skill ./dist")
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Packaging skill: {skill_path}")
    if output_dir:
        print(f"   Output directory: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

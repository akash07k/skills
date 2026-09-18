#!/usr/bin/env python3
"""Minimal, dependency-free validation for skill frontmatter."""

import re
import sys
from pathlib import Path

from scripts.utils import is_safe_yaml_plain_scalar, parse_frontmatter

ALLOWED_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}


def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    content = skill_md.read_text(encoding="utf-8-sig")
    if not content.startswith("---"):
        return False, "No YAML frontmatter found"
    try:
        name, description, raw_description, keys = parse_frontmatter(content)
    except ValueError as error:
        return False, str(error)
    unexpected_keys = keys - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )
    if "name" not in keys:
        return False, "Missing 'name' in frontmatter"
    if "description" not in keys:
        return False, "Missing 'description' in frontmatter"

    name = name.strip()
    if not name:
        return False, "Name must be a nonempty string"
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return False, f"Name '{name}' should be kebab-case"
    if len(name) > 64:
        return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    description = description.strip()
    if not description:
        return False, "Description must be a nonempty string"
    is_block = raw_description == "|"
    is_quoted = (
        len(raw_description) >= 2
        and raw_description[0] in {'"', "'"}
        and raw_description[-1] == raw_description[0]
    )
    if not is_block and not is_quoted and not is_safe_yaml_plain_scalar(raw_description):
        return False, (
            "Plain description is not YAML-safe; quote it or use a description: | block"
        )
    if "<" in description or ">" in description:
        return False, "Description cannot contain angle brackets (< or >)"
    if len(description) > 1024:
        return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    return True, "Skill is valid!"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.quick_validate <skill-directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
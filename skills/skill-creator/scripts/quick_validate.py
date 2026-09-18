#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Dependency-free validation of a skill folder against the Agent Skills spec.

Usage:
    python scripts/quick_validate.py <skill-directory> [--strict] [--json]

Errors and warnings go to stderr; a success line goes to stdout. With --json a
single JSON object {"path", "valid", "errors", "warnings"} is the only output.
Exit codes: 0 valid, 1 invalid or unreadable, 2 usage error.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote

if sys.version_info < (3, 13):
    sys.exit("skill-creator scripts require Python 3.13 or later.")

if not __package__:
    # Allow `python <skill>/scripts/<name>.py` from any working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import FrontmatterError, ensure_utf8_stdio, load_frontmatter, resolve_plain_scalar

ALLOWED_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
CLIENT_SPECIFIC_PROPERTIES = {"argument-hint", "user-invocable", "disable-model-invocation"}
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000
VALID_MESSAGE = "Skill is valid!"
_WHEN_TO_USE_RE = re.compile(r"\b(use|used|using|when|whenever|trigger|triggers|if)\b", re.IGNORECASE)
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_LINK_RE = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)")
_LINK_DEFINITION_RE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)", re.MULTILINE)
_SKILL_DIR_PATH_RE = re.compile(r"(?:\.[\\/])?(?:scripts|references|assets|agents)[\\/][^\s*?<>|\"'{}$]+")
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+:")
_ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|[\\/]|~[\\/]")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def _yaml_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, date):
        return "timestamp"
    if isinstance(value, dict):
        return "mapping"
    return type(value).__name__


def _not_a_string(frontmatter, path: str, label: str, value) -> str:
    info = frontmatter.info.get(path, {})
    raw = info.get("raw", "")
    line = f"line {info['line']}: " if "line" in info else ""
    if info.get("style") == "plain" and raw:
        escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
        return (
            f"{line}{label} must be a string, but the unquoted value {raw!r} is a YAML "
            f"{_yaml_type(value)}; quote it, e.g. \"{escaped}\""
        )
    return f"{line}{label} must be a string (got {_yaml_type(value)})"


def _without_block_newlines(frontmatter, path: str, value: str) -> str:
    # Block scalars (| and >) end with a newline added by chomping; it is not part of the text.
    if frontmatter.info.get(path, {}).get("style") in ("literal", "folded"):
        return value.rstrip("\n")
    return value


def _check_name(name: str, folder: str, errors: list[str], warnings: list[str]) -> None:
    if not name.strip():
        errors.append("'name' must be a non-empty string")
        return
    if name != name.strip():
        errors.append(f"Name {name!r} must not have leading or trailing whitespace")
        name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        errors.append(f"Name is too long ({len(name)} characters). Maximum is {MAX_NAME_LENGTH} characters.")
    if name != name.lower():
        errors.append(f"Name '{name}' must be lowercase")
    if name.startswith("-") or name.endswith("-"):
        errors.append(f"Name '{name}' must not start or end with a hyphen")
    if "--" in name:
        errors.append(f"Name '{name}' must not contain consecutive hyphens (--)")
    invalid = sorted({ch for ch in name if not (ch.isalnum() or ch == "-")})
    if invalid:
        errors.append(
            f"Name '{name}' contains invalid characters {''.join(invalid)!r}; "
            "use only lowercase letters, digits and hyphens"
        )
    if folder and unicodedata.normalize("NFKC", name) != unicodedata.normalize("NFKC", folder):
        errors.append(f"Name '{name}' must match the skill directory name '{folder}'")
    if not name.isascii():
        warnings.append(
            f"Name '{name}' contains non-ASCII characters; the spec allows them, but some "
            "clients, file systems and tools handle only ASCII names"
        )


def _body_without_code(body: str) -> tuple[str, list[str]]:
    """Return the body with fenced and inline code blanked out, plus the inline code spans."""
    kept: list[str] = []
    fence = ""
    for line in body.split("\n"):
        match = _FENCE_RE.match(line)
        if fence:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) \
                    and not line.strip().lstrip(fence[0]):
                fence = ""
            kept.append("")
            continue
        if match:
            fence = match.group(1)
            kept.append("")
            continue
        kept.append(line)
    text = "\n".join(kept)
    blanked = _CODE_SPAN_RE.sub(lambda match: " " * len(match.group(0)), text)
    spans = []
    for match in _CODE_SPAN_RE.finditer(text):
        # Inline code inside a "quoted passage" is example prose, not a real reference.
        paragraph = blanked[blanked.rfind("\n\n", 0, match.start()) + 1:match.start()]
        if sum(paragraph.count(quote) for quote in '"\u201c\u201d') % 2 == 0:
            spans.append(match.group(2).strip())
    return blanked, spans


def _check_reference(target: str, skill_path: Path, label: str, warnings: list[str]) -> None:
    if _ABSOLUTE_PATH_RE.match(target):
        warnings.append(
            f"{label} {target!r} is an absolute path; use a path relative to the skill folder"
        )
        return
    if _SCHEME_RE.match(target) or target.startswith("#"):
        return
    path = unquote(target.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path:
        return
    root = skill_path.resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        warnings.append(f"{label} {target!r} points outside the skill folder")
        return
    if not resolved.exists():
        warnings.append(f"{label} {target!r} does not exist in the skill folder")


def _check_body_references(body: str, skill_path: Path, warnings: list[str]) -> None:
    text, spans = _body_without_code(body)
    seen: set[str] = set()
    targets = [(m.group(1), "Link") for m in _LINK_RE.finditer(text)]
    targets += [(m.group(1), "Link") for m in _LINK_DEFINITION_RE.finditer(text)]
    targets += [(span, "File reference") for span in spans if _SKILL_DIR_PATH_RE.fullmatch(span)]
    for target, label in targets:
        target = target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if target and target not in seen:
            seen.add(target)
            _check_reference(target, skill_path, label, warnings)


def _find_skill_md(skill_path: Path, errors: list[str]) -> Path | None:
    try:
        entries = os.listdir(skill_path)
    except OSError as error:
        errors.append(f"Cannot list {skill_path}: {error.strerror or error}")
        return None
    if "SKILL.md" in entries and (skill_path / "SKILL.md").is_file():
        return skill_path / "SKILL.md"
    near = sorted(entry for entry in entries if entry.lower() == "skill.md")
    if near:
        errors.append(f"SKILL.md not found (found {near[0]!r}; the file must be named exactly 'SKILL.md')")
    else:
        errors.append("SKILL.md not found")
    return None


def check_skill(skill_path, strict: bool = False) -> ValidationResult:
    """Validate a skill directory and collect every error and warning.

    With ``strict``, client-specific frontmatter fields are errors instead of warnings.
    """
    result = ValidationResult()
    errors, warnings = result.errors, result.warnings
    skill_path = Path(skill_path)
    if skill_path.name.lower() == "skill.md" and skill_path.is_file():
        skill_path = skill_path.parent
    if not skill_path.exists():
        errors.append(f"Skill directory not found: {skill_path}")
        return result
    if not skill_path.is_dir():
        errors.append(f"Not a directory: {skill_path}")
        return result
    skill_md = _find_skill_md(skill_path, errors)
    if skill_md is None:
        return result

    try:
        content = skill_md.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        errors.append(f"SKILL.md is not valid UTF-8 (invalid byte at offset {error.start})")
        return result
    except OSError as error:
        errors.append(f"Cannot read SKILL.md: {error.strerror or error}")
        return result

    try:
        frontmatter = load_frontmatter(content)
    except FrontmatterError as error:
        errors.append(str(error))
        return result
    data = frontmatter.data

    unexpected = set(data) - ALLOWED_PROPERTIES - CLIENT_SPECIFIC_PROPERTIES
    if unexpected:
        errors.append(
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )
    client_specific = sorted(set(data) & CLIENT_SPECIFIC_PROPERTIES)
    if client_specific:
        (errors if strict else warnings).append(
            f"Client-specific key(s) in SKILL.md frontmatter: {', '.join(client_specific)}. "
            "These are extensions of some clients (e.g. VS Code), not part of the Agent Skills "
            "spec; other clients may ignore or reject them"
        )

    folder = os.path.basename(os.path.normpath(os.path.abspath(skill_path)))
    if "name" not in data:
        errors.append("Missing 'name' in frontmatter")
    elif not isinstance(data["name"], str):
        errors.append(_not_a_string(frontmatter, "name", "'name'", data["name"]))
    else:
        _check_name(data["name"], folder, errors, warnings)

    if "description" not in data:
        errors.append("Missing 'description' in frontmatter")
    elif not isinstance(data["description"], str):
        errors.append(_not_a_string(frontmatter, "description", "'description'", data["description"]))
    else:
        description = _without_block_newlines(frontmatter, "description", data["description"])
        if not description.strip():
            errors.append("'description' must be a non-empty string")
        else:
            if len(description) > MAX_DESCRIPTION_LENGTH:
                errors.append(
                    f"Description is too long ({len(description)} characters). "
                    f"Maximum is {MAX_DESCRIPTION_LENGTH} characters."
                )
            if "<" in description or ">" in description:
                warnings.append(
                    "Description contains angle brackets (< or >); some hosts render or strip them"
                )
            if not _WHEN_TO_USE_RE.search(description):
                warnings.append(
                    "Description does not say when to use the skill; consider adding 'Use when ...'"
                )

    if "compatibility" in data:
        value = data["compatibility"]
        if not isinstance(value, str):
            errors.append(_not_a_string(frontmatter, "compatibility", "'compatibility'", value))
        elif not value.strip():
            errors.append("'compatibility' must not be empty")
        elif len(value := _without_block_newlines(frontmatter, "compatibility", value)) > MAX_COMPATIBILITY_LENGTH:
            errors.append(
                f"Compatibility is too long ({len(value)} characters). "
                f"Maximum is {MAX_COMPATIBILITY_LENGTH} characters."
            )

    for key in ("license", "allowed-tools"):
        if key in data and not isinstance(data[key], str):
            errors.append(_not_a_string(frontmatter, key, f"'{key}'", data[key]))
    if isinstance(data.get("license"), str) and not data["license"].strip():
        warnings.append("license is empty; remove it or name a license")

    if "metadata" in data:
        metadata = data["metadata"]
        if not isinstance(metadata, dict):
            line = frontmatter.info.get("metadata", {}).get("line")
            prefix = f"line {line}: " if line else ""
            errors.append(f"{prefix}'metadata' must be a mapping of string keys to string values")
        else:
            for key, value in metadata.items():
                info = frontmatter.info.get(f"metadata.{key}", {})
                resolved = resolve_plain_scalar(key) if info.get("key_style", "plain") == "plain" else key
                if not isinstance(resolved, str):
                    line = f"line {info['line']}: " if "line" in info else ""
                    errors.append(
                        f"{line}metadata keys must be strings; quote the key: the unquoted key "
                        f"{key!r} is a YAML {_yaml_type(resolved)}, write \"{key}\": ... instead"
                    )
                if not isinstance(value, str):
                    errors.append(
                        _not_a_string(frontmatter, f"metadata.{key}", f"'metadata.{key}'", value)
                    )

    body_lines = frontmatter.body.strip("\n").split("\n") if frontmatter.body.strip() else []
    if not body_lines:
        warnings.append("SKILL.md body is empty; add instructions after the frontmatter")
    elif len(body_lines) > MAX_BODY_LINES:
        warnings.append(
            f"SKILL.md body has {len(body_lines)} lines; keep it under {MAX_BODY_LINES} "
            "and move detail into references/"
        )
    body_tokens = round(len(frontmatter.body) / 4)
    if len(frontmatter.body) > MAX_BODY_TOKENS * 4:
        warnings.append(
            f"SKILL.md body is about {body_tokens} tokens (characters / 4); keep it under "
            f"{MAX_BODY_TOKENS} and move detail into references/"
        )
    _check_body_references(frontmatter.body, skill_path, warnings)
    return result


def validate_skill(skill_path) -> tuple[bool, str]:
    """Backward-compatible API: (valid, message). All errors are newline-joined."""
    result = check_skill(skill_path)
    if result.valid:
        return True, VALID_MESSAGE
    return False, "\n".join(result.errors)


def main(argv=None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="python scripts/quick_validate.py",
        description="Validate a skill folder's SKILL.md against the Agent Skills specification.",
        epilog="Exit codes: 0 valid, 1 invalid or unreadable, 2 usage error.",
    )
    parser.add_argument("skill_directory", help="path to the skill folder (containing SKILL.md)")
    parser.add_argument(
        "--strict", action="store_true",
        help="treat client-specific frontmatter fields (argument-hint, user-invocable, "
             "disable-model-invocation) as errors instead of warnings",
    )
    parser.add_argument(
        "--json", action="store_true",
        help='print one JSON object {"path", "valid", "errors", "warnings"} to stdout and nothing else',
    )
    args = parser.parse_args(argv)

    result = check_skill(args.skill_directory, strict=args.strict)
    if args.json:
        skill_dir = Path(args.skill_directory)
        if skill_dir.name.lower() == "skill.md" and skill_dir.is_file():
            skill_dir = skill_dir.parent
        print(json.dumps({
            "path": str(skill_dir),
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
        }, ensure_ascii=False))
        return 0 if result.valid else 1
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not result.valid:
        for error in result.errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"Skill is invalid: {len(result.errors)} error(s)", file=sys.stderr)
        return 1
    suffix = f" ({len(result.warnings)} warning(s))" if result.warnings else ""
    print(f"{VALID_MESSAGE}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

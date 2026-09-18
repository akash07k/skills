"""Shared utilities for skill-creator scripts."""

import os
import re
import tempfile
from pathlib import Path

def eval_sort_key(eval_id: object) -> tuple[int, int | str]:
    """Sort numeric IDs numerically and all other IDs predictably."""
    if isinstance(eval_id, int) and not isinstance(eval_id, bool):
        return 0, eval_id
    if isinstance(eval_id, str):
        try:
            return 0, int(eval_id)
        except ValueError:
            return 1, eval_id
    return 2, str(eval_id)


def aggregate_runs(results: list[dict] | None) -> tuple[int, int]:
    """Count correct and total trigger decisions."""
    correct = 0
    total = 0
    for result in results or []:
        runs = result.get("runs", 0)
        triggers = result.get("triggers", 0)
        total += runs
        correct += triggers if result.get("should_trigger", True) else runs - triggers
    return correct, total


def best_iteration(history: list[dict], has_holdout: bool) -> dict | None:
    """Choose by passing queries, then correct runs; max keeps the earliest tie."""
    if not history:
        return None
    prefix = "test" if has_holdout else "train"
    return max(
        history,
        key=lambda item: (
            item.get(f"{prefix}_passed") or 0,
            aggregate_runs(item.get(f"{prefix}_results"))[0],
        ),
    )


def is_safe_yaml_plain_scalar(value: str) -> bool:
    """Return whether a string remains a YAML string when written unquoted."""
    if not value or value != value.strip():
        return False
    if value[0] in "!&*#{}[],|>@`\"'%":
        return False
    if value in {"-", "?", ":"} or value.startswith(("- ", "? ", ": ")):
        return False
    if ": " in value or " #" in value or value.endswith(":"):
        return False
    if value.startswith(("---", "...")):
        return False
    if value.lower() in {"null", "~", "true", "false", ".nan", ".inf", "-.inf", "+.inf"}:
        return False
    return re.fullmatch(
        r"[-+]?(?:0|[1-9][0-9_]*)(?:\.[0-9_]*)?(?:[eE][-+]?[0-9]+)?",
        value,
    ) is None


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a text file atomically and clean up failed temporary writes."""
    temporary_path = None
    destination_mode = path.stat().st_mode if path.exists() else 0o644
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
        temporary_path = None
        os.chmod(path, destination_mode)
    finally:
        if temporary_path is not None:
            try:
                os.chmod(temporary_path, 0o600)
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def decode_yaml_scalar(value: str) -> str:
    """Decode the single-line quoted YAML forms accepted by the validator."""
    if len(value) < 2 or value[0] != value[-1] or value[0] not in "\"'":
        return value
    inner = value[1:-1]
    if value[0] == "'":
        decoded = []
        index = 0
        while index < len(inner):
            if inner[index] != "'":
                decoded.append(inner[index])
                index += 1
            elif index + 1 < len(inner) and inner[index + 1] == "'":
                decoded.append("'")
                index += 2
            else:
                raise ValueError("Invalid single-quoted YAML scalar")
        return "".join(decoded)

    escapes = {
        "0": "\0", "a": "\a", "b": "\b", "t": "\t", "n": "\n",
        "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ",
        '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0",
        "L": "\u2028", "P": "\u2029",
    }
    decoded = []
    index = 0
    while index < len(inner):
        if inner[index] != "\\":
            if inner[index] == '"':
                raise ValueError("Invalid double-quoted YAML scalar")
            decoded.append(inner[index])
            index += 1
            continue
        index += 1
        if index == len(inner):
            raise ValueError("Invalid escape in double-quoted YAML scalar")
        escape = inner[index]
        if escape in "xuU":
            digits = {"x": 2, "u": 4, "U": 8}[escape]
            code = inner[index + 1:index + 1 + digits]
            if len(code) != digits or not re.fullmatch(r"[0-9a-fA-F]+", code):
                raise ValueError("Invalid Unicode escape in double-quoted YAML scalar")
            decoded.append(chr(int(code, 16)))
            index += digits + 1
        elif escape in escapes:
            decoded.append(escapes[escape])
            index += 1
        else:
            raise ValueError(f"Unsupported escape in double-quoted YAML scalar: \\{escape}")
    return "".join(decoded)


def parse_frontmatter(content: str) -> tuple[str, str, str, set[str]]:
    """Parse constrained skill frontmatter once."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")

    if lines[0].rstrip() != "---":
        raise ValueError("SKILL.md missing frontmatter (no opening ---)")

    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("SKILL.md missing frontmatter (no closing ---)")

    name = ""
    description = ""
    raw_description = ""
    frontmatter_lines = lines[1:end_idx]

    keys = set()
    for line in frontmatter_lines:
        if not line.strip() or line[0].isspace():
            continue
        if re.match(r"^(?:name|description):\S", line):
            raise ValueError("Frontmatter values must be separated from keys by a space")
        key, separator, value = line.partition(":")
        if (
            not separator
            or (value and not value.startswith(" "))
            or not re.fullmatch(r"[a-z][a-z0-9-]*", key)
        ):
            raise ValueError(f"Invalid frontmatter property: {line}")
        if key in keys:
            raise ValueError(f"Duplicate frontmatter property: {key}")
        keys.add(key)

    def has_indented_continuation(index: int) -> bool:
        index += 1
        while index < len(frontmatter_lines) and not frontmatter_lines[index].strip():
            index += 1
        return (
            index < len(frontmatter_lines)
            and frontmatter_lines[index][0].isspace()
        )

    i = 0
    while i < len(frontmatter_lines):
        line = frontmatter_lines[i]
        if line.startswith("name:"):
            if has_indented_continuation(i):
                raise ValueError("Names must use a single-line YAML scalar")
            name = decode_yaml_scalar(line[len("name:"):].strip())
        elif line.startswith("description:"):
            value = line[len("description:"):].strip()
            raw_description = value
            if value == "|":
                block_lines = []
                i += 1
                while i < len(frontmatter_lines):
                    block_line = frontmatter_lines[i]
                    if not block_line:
                        block_lines.append("")
                    elif not block_line.strip():
                        raise ValueError(
                            "Blank description block lines must be empty"
                        )
                    elif block_line.startswith("  "):
                        block_lines.append(block_line[2:])
                    elif block_line[0].isspace():
                        raise ValueError(
                            "Description block lines must use two-space indentation"
                        )
                    else:
                        break
                    i += 1
                description = "\n".join(block_lines).rstrip("\n")
                if description:
                    description += "\n"
                continue
            if value.startswith(("|", ">")):
                raise ValueError(
                    "Description blocks must use exactly 'description: |'"
                )
            if has_indented_continuation(i):
                raise ValueError(
                    "Wrapped descriptions must use exactly 'description: |'"
                )
            description = decode_yaml_scalar(value)
        i += 1

    return name, description, raw_description, keys


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning (name, description, full_content)."""
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8-sig")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    name, description, _, _ = parse_frontmatter(normalized)
    return name, description, normalized

"""Shared utilities for skill-creator scripts."""

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    import ruamel.yaml as yaml
except ImportError as error:
    raise SystemExit(
        "ruamel.yaml is required. Install skill-creator/requirements.txt "
        "or run the script with uv run."
    ) from error


def ensure_utf8_stdio() -> None:
    """Keep non-ASCII output from crashing on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


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


class FrontmatterError(ValueError):
    """A frontmatter syntax error, optionally tied to a 1-based file line."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class Frontmatter:
    """Parsed frontmatter, source metadata, and the remaining Markdown body."""

    data: dict
    info: dict
    body: str
    body_line: int


def _safe_yaml():
    """Create a safe YAML 1.2 core-schema parser."""
    parser = yaml.YAML(typ="safe", pure=True)
    for initial, resolvers in parser.resolver.versioned_resolver.items():
        parser.resolver.versioned_resolver[initial] = [
            item for item in resolvers if item[0] != "tag:yaml.org,2002:timestamp"
        ]
    return parser


def split_frontmatter(content: str) -> tuple[list[str], str, int]:
    """Split SKILL.md text into (frontmatter lines, body, body start line)."""
    content = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")
    if lines[0].rstrip() != "---":
        raise FrontmatterError("SKILL.md missing frontmatter (no opening ---)")
    for end, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            return lines[1:end], "\n".join(lines[end + 1:]), end + 2
    raise FrontmatterError("SKILL.md missing frontmatter (no closing ---)")


def _style(node) -> str:
    if isinstance(node, yaml.nodes.MappingNode):
        return "flow" if node.flow_style else "mapping"
    if isinstance(node, yaml.nodes.SequenceNode):
        return "sequence"
    return {
        None: "plain",
        "'": "single",
        '"': "double",
        "|": "literal",
        ">": "folded",
    }.get(node.style, "plain")


def _record(info: dict, path: str, key_node, value_node, lines: list[str]) -> None:
    index = key_node.start_mark.line
    rest = lines[index][key_node.end_mark.column:].lstrip()
    raw = rest[1:].strip() if rest.startswith(":") else ""
    info[path] = {
        "line": index + 2,
        "style": _style(value_node),
        "raw": raw,
        "key_style": {"'": "single", '"': "double"}.get(key_node.style, "plain"),
    }


def _check_unicode(node, lines, seen=None):
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, yaml.nodes.ScalarNode):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in node.value):
            first = node.start_mark.line
            last = min(node.end_mark.line, len(lines) - 1)
            for index in range(first, last + 1):
                if re.search(r"\\(?:u|U)[0-9a-fA-F]+", lines[index]):
                    raise FrontmatterError("invalid Unicode code point", index + 2)
            raise FrontmatterError("invalid Unicode code point", first + 2)
    elif isinstance(node, yaml.nodes.MappingNode):
        for key, value in node.value:
            _check_unicode(key, lines, seen)
            _check_unicode(value, lines, seen)
    elif isinstance(node, yaml.nodes.SequenceNode):
        for item in node.value:
            _check_unicode(item, lines, seen)


def load_frontmatter(content: str) -> Frontmatter:
    """Parse SKILL.md text with safe YAML; reject duplicate mapping keys."""
    lines, body, body_line = split_frontmatter(content)
    for index, line in enumerate(lines):
        if re.match(r"^(?:name|description|license|compatibility|metadata|allowed-tools):\S", line):
            raise FrontmatterError("frontmatter values must be separated from keys by a space", index + 2)
    parser = _safe_yaml()
    text = "\n".join(lines) + "\n"
    try:
        node = parser.compose(text)
        if not isinstance(node, yaml.nodes.MappingNode):
            raise FrontmatterError("SKILL.md frontmatter must be a YAML mapping", 2)
        _check_unicode(node, lines)
        data = parser.load(text)
        parser.constructor.flatten_mapping(node)
        info = {}
        for key_node, value_node in node.value:
            if key_node.tag != "tag:yaml.org,2002:str":
                raise FrontmatterError("frontmatter keys must be strings", key_node.start_mark.line + 2)
            key = key_node.value
            _record(info, key, key_node, value_node, lines)
            if key == "metadata" and isinstance(value_node, yaml.nodes.MappingNode):
                parser.constructor.flatten_mapping(value_node)
                for child_key, child_value in value_node.value:
                    if not isinstance(child_key, yaml.nodes.ScalarNode):
                        continue
                    child = (
                        child_key.value if child_key.tag == "tag:yaml.org,2002:str"
                        else parser.constructor.construct_object(child_key, deep=True)
                    )
                    path = f"metadata.{child}"
                    _record(info, path, child_key, child_value, lines)
                    info[path]["key_raw"] = child_key.value
        return Frontmatter(data=data, info=info, body=body, body_line=body_line)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        message = getattr(error, "problem", None) or str(error)
        if isinstance(error, yaml.constructor.DuplicateKeyError):
            match = re.search(r'found duplicate key "([^"]+)"', message)
            if match:
                message = f"Duplicate frontmatter property: {match.group(1)}"
        if "mapping values are not allowed" in message:
            message += "; quote the value or use a block scalar"
        raise FrontmatterError(message, mark.line + 2 if mark else None) from error
    except FrontmatterError:
        raise
    except ValueError as error:
        message = "invalid Unicode code point" if "chr() arg" in str(error) else "invalid YAML value"
        candidates = [
            index + 2
            for index, line in enumerate(lines)
            for match in re.finditer(r"(?<!\\)(?:\\\\)*\\U([0-9a-fA-F]{8})", line)
            if int(match.group(1), 16) > 0x10FFFF
        ]
        line = candidates[0] if len(candidates) == 1 else None
        raise FrontmatterError(f"{message}: {error}", line) from error


def resolve_plain_scalar(text: str):
    """Resolve an unquoted scalar using the YAML loader."""
    try:
        return _safe_yaml().load(text)
    except yaml.YAMLError:
        return text


def frontmatter_text(frontmatter: Frontmatter, key: str) -> str:
    """Return a field as text: strings as-is, other scalars as written."""
    value = frontmatter.data.get(key)
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (dict, list)):
        return ""
    return frontmatter.info.get(key, {}).get("raw", str(value))


def parse_frontmatter(content: str) -> tuple[str, str, str, set[str]]:
    """Backward-compatible wrapper: (name, description, raw_description, keys)."""
    frontmatter = load_frontmatter(content)
    return (
        frontmatter_text(frontmatter, "name"),
        frontmatter_text(frontmatter, "description"),
        frontmatter.info.get("description", {}).get("raw", ""),
        set(frontmatter.data),
    )


def decode_yaml_scalar(value: str) -> str:
    """Decode a single-line quoted YAML scalar; other text is unchanged."""
    if not value or value[0] not in "\"'":
        return value
    try:
        return _safe_yaml().load(value)
    except yaml.YAMLError as error:
        raise FrontmatterError(str(error)) from error


def is_safe_yaml_plain_scalar(value: str) -> bool:
    """Return whether a string remains the same YAML string when unquoted."""
    if not value or value != value.strip() or "\n" in value:
        return False
    try:
        parsed = _safe_yaml().load(f"k: {value}")
        return isinstance(parsed, dict) and parsed.get("k") == value
    except yaml.YAMLError:
        return False


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning (name, description, full_content)."""
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8-sig")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    name, description, _, _ = parse_frontmatter(normalized)
    return name, description, normalized

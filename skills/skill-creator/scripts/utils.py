"""Shared utilities for skill-creator scripts."""

import os
import re
import tempfile
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


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


# ---------------------------------------------------------------------------
# SKILL.md frontmatter: a small, strict, dependency-free YAML subset parser.
#
# Supported: top-level ``key: value`` pairs whose values are plain, single- or
# double-quoted (optionally multi-line) scalars, literal ``|`` / folded ``>``
# block scalars (chomping ``-``/``+`` and indentation indicators), comments,
# and one level of nested string mapping under ``metadata``. Everything else
# (flow collections, anchors, aliases, tags, sequences, other nested maps,
# duplicate keys, tab indentation) is rejected with a line-numbered error.
# Plain scalars resolve like a YAML loader would (booleans incl. YAML 1.1
# yes/no/on/off, nulls, numbers, timestamps) so validation can flag values
# that are not strings in real YAML.

_KEY_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_.-]*)[ \t]*:(?:[ \t]+(.*))?$")
_MISSING_SPACE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*:\S")
_INT_RE = re.compile(r"[-+]?(?:0b[01_]+|0x[0-9a-fA-F_]+|0o[0-7_]+|[0-9][0-9_]*)")
_SEXAGESIMAL_RE = re.compile(r"[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?")
_FLOAT_RE = re.compile(
    r"[-+]?(?:(?:[0-9][0-9_]*)?\.[0-9_]*(?:[eE][-+]?[0-9]+)?|[0-9][0-9_]*[eE][-+]?[0-9]+)"
)
_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d\d?-\d\d?(?:(?:[Tt]|[ \t]+)\d\d?:\d\d:\d\d(?:\.\d*)?"
    r"(?:[ \t]*(?:Z|[-+]\d\d?(?::\d\d)?))?)?"
)
_DOUBLE_QUOTE_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n",
    "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"',
    "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029",
}


class FrontmatterError(ValueError):
    """A frontmatter syntax error, optionally tied to a 1-based file line."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class Frontmatter:
    """Parsed SKILL.md frontmatter.

    ``data`` maps top-level keys to values (str, None, bool, int, float,
    date/datetime, or a dict of str -> value for ``metadata``). ``info`` maps
    ``key`` / ``metadata.<key>`` to ``{"line", "style", "raw"}``; metadata
    entries also carry ``key_style`` ("plain", "single" or "double").
    """

    data: dict
    info: dict
    body: str
    body_line: int


def _yaml_cases(word: str) -> set[str]:
    return {word, word.capitalize(), word.upper()}


_NULL_WORDS = {"", "~"} | _yaml_cases("null")
_TRUE_WORDS = set().union(*(_yaml_cases(w) for w in ("true", "yes", "on", "y")))
_FALSE_WORDS = set().union(*(_yaml_cases(w) for w in ("false", "no", "off", "n")))
_INF_NAN = {
    **{w: float("inf") for w in _yaml_cases(".inf") | {"+" + w for w in _yaml_cases(".inf")}},
    **{"-" + w: float("-inf") for w in _yaml_cases(".inf")},
    **{w: float("nan") for w in {".nan", ".NaN", ".NAN"}},
}


def resolve_plain_scalar(text: str):
    """Resolve an unquoted scalar the way a YAML loader would."""
    if text in _NULL_WORDS:
        return None
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    if text in _INF_NAN:
        return _INF_NAN[text]
    try:
        if _INT_RE.fullmatch(text):
            digits = text.replace("_", "")
            sign = -1 if digits.startswith("-") else 1
            digits = digits.lstrip("+-")
            if digits[:2] in ("0b", "0x", "0o"):
                return sign * int(digits, 0)
            if len(digits) > 1 and digits[0] == "0" and set(digits) <= set("01234567"):
                return sign * int(digits, 8)
            return sign * int(digits, 10)
        if _SEXAGESIMAL_RE.fullmatch(text):
            sign = -1 if text.startswith("-") else 1
            total = 0.0 if "." in text else 0
            for part in text.lstrip("+-").replace("_", "").split(":"):
                total = total * 60 + (float(part) if "." in part else int(part))
            return sign * total
        if _FLOAT_RE.fullmatch(text):
            return float(text.replace("_", ""))
        if _TIMESTAMP_RE.fullmatch(text):
            if len(text) <= 10:
                year, month, day = (int(part) for part in text.split("-"))
                return date(year, month, day)
            return datetime.fromisoformat(re.sub(r"[Tt]|[ \t]+", "T", text, count=1).replace(" ", ""))
    except ValueError:
        pass
    return text


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


_BLOCK_FORM_HINT = (
    "this validator's YAML subset only supports a flat flow map under 'metadata'; "
    "use the block form instead: 'metadata:' on its own line followed by indented "
    "'key: value' lines"
)


class _FrontmatterParser:
    def __init__(self, lines: list[str], first_line: int):
        self.lines = lines
        self.first_line = first_line
        self.pos = 0
        self.info: dict = {}

    def lineno(self, index: int) -> int:
        return self.first_line + index

    def error(self, message: str, index: int) -> FrontmatterError:
        return FrontmatterError(message, self.lineno(index))

    def check_tabs(self, index: int) -> None:
        line = self.lines[index]
        if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
            raise self.error("tabs are not allowed in indentation; use spaces", index)

    @staticmethod
    def is_ignorable(line: str) -> bool:
        stripped = line.strip()
        return not stripped or stripped.startswith("#")

    def parse(self) -> dict:
        data: dict = {}
        while self.pos < len(self.lines):
            index = self.pos
            line = self.lines[index]
            if self.is_ignorable(line):
                self.pos += 1
                continue
            self.check_tabs(index)
            if line[0] == " ":
                raise self.error("unexpected indentation", index)
            key, rest = self.split_key(line, index)
            if key in data:
                raise self.error(f"Duplicate frontmatter property: {key}", index)
            data[key] = self.parse_value(key, rest, index, 0, allow_mapping=(key == "metadata"))
        return data

    def split_key(self, text: str, index: int) -> tuple[str, str]:
        match = _KEY_RE.match(text)
        if match:
            return match.group(1), (match.group(2) or "").strip()
        stripped = text.strip()
        if _MISSING_SPACE_RE.match(stripped):
            raise self.error("Frontmatter values must be separated from keys by a space", index)
        if stripped[0] == "-" and stripped[1:2] in ("", " "):
            raise self.error("YAML sequences ('- item') are not supported in frontmatter", index)
        if stripped[0] == "?" and stripped[1:2] in ("", " "):
            raise self.error("complex mapping keys ('? key') are not supported", index)
        if stripped[0] in "\"'":
            raise self.error("quoted keys are not supported; use a plain key such as 'name:'", index)
        if stripped[0] in "[{":
            raise self.error(f"flow collections ([...] or {{...}}) are not supported here; {_BLOCK_FORM_HINT}", index)
        if stripped[0] in "&*!":
            raise self.error("anchors, aliases and tags are not supported", index)
        if stripped[0] == "%":
            raise self.error("YAML directives are not supported", index)
        raise self.error(f"Invalid frontmatter property: {stripped}", index)

    def next_content(self, index: int) -> int | None:
        while index < len(self.lines):
            if not self.is_ignorable(self.lines[index]):
                return index
            index += 1
        return None

    def record(self, path: str, index: int, style: str, raw: str) -> None:
        self.info[path] = {"line": self.lineno(index), "style": style, "raw": raw}

    def parse_value(self, path: str, rest: str, index: int, parent_indent: int, allow_mapping: bool):
        if allow_mapping and rest.startswith("{"):
            self.record(path, index, "flow", rest)
            return self.parse_flow_map(path, rest, index)
        if rest and not rest.startswith("#"):
            value, style = self.parse_scalar(rest, index, parent_indent)
            self.record(path, index, style, rest)
            return value

        following = self.next_content(index + 1)
        if following is None or _indent_of(self.lines[following]) <= parent_indent:
            self.pos = index + 1
            self.record(path, index, "empty", "")
            return None
        self.check_tabs(following)
        content = self.lines[following].strip()
        if content[0] == "-" and content[1:2] in ("", " "):
            raise self.error("YAML sequences ('- item') are not supported in frontmatter", following)
        if allow_mapping and content.startswith("{"):
            self.record(path, index, "flow", content)
            return self.parse_flow_map(path, content, following)
        if self.looks_like_mapping_entry(content):
            if not allow_mapping:
                raise self.error(
                    f"nested mappings are only supported under 'metadata' (found under '{path}')",
                    following,
                )
            self.record(path, index, "mapping", "")
            return self.parse_mapping(path, following, parent_indent)
        if content[0] in "|>":
            raise self.error("block scalar indicators must follow the key on the same line", following)
        value, style = self.parse_scalar(self.lines[following].lstrip(" "), following, parent_indent)
        self.record(path, index, style, content)
        return value

    @staticmethod
    def looks_like_mapping_entry(content: str) -> bool:
        if content[0] in "\"'":
            end = content.find(content[0], 1)
            return end > 0 and re.match(r"[ \t]*:(?:[ \t]|$)", content[end + 1:]) is not None
        before_comment = re.split(r"[ \t]#", content, maxsplit=1)[0]
        return re.search(r":(?:[ \t]|$)", before_comment) is not None

    def parse_mapping(self, path: str, index: int, parent_indent: int) -> dict:
        indent = _indent_of(self.lines[index])
        result: dict = {}
        while index < len(self.lines):
            line = self.lines[index]
            if self.is_ignorable(line):
                index += 1
                continue
            line_indent = _indent_of(line)
            if line_indent <= parent_indent:
                break
            self.check_tabs(index)
            if line_indent != indent:
                raise self.error(f"inconsistent indentation inside '{path}'", index)
            text = line[line_indent:]
            if text[0] in "\"'":
                key, end = self.scan_quoted(text, 0, index)
                key_style = "single" if text[0] == "'" else "double"
                match = re.match(r"[ \t]*:(?:[ \t]+(.*))?$", text[end:])
                if not match:
                    raise self.error(f"expected ':' after the quoted key {text[:end]}", index)
                rest = (match.group(1) or "").strip()
            else:
                key, rest = self.split_key(text, index)
                key_style = "plain"
            if key in result:
                raise self.error(f"Duplicate key in '{path}': {key}", index)
            result[key] = self.parse_value(f"{path}.{key}", rest, index, indent, allow_mapping=False)
            self.info[f"{path}.{key}"]["key_style"] = key_style
            index = self.pos
        self.pos = index
        return result

    def scan_quoted(self, text: str, start: int, index: int) -> tuple[str, int]:
        """Read a single-line quoted scalar at text[start]; return (value, end)."""
        quote = text[start]
        out: list[str] = []
        position = start + 1
        while position < len(text):
            char = text[position]
            if char == quote:
                if quote == "'" and text[position + 1:position + 2] == "'":
                    out.append("'")
                    position += 2
                    continue
                return "".join(out), position + 1
            if quote == '"' and char == "\\":
                escape = text[position + 1:position + 2]
                if escape in ("x", "u", "U"):
                    digits = {"x": 2, "u": 4, "U": 8}[escape]
                    code = text[position + 2:position + 2 + digits]
                    if len(code) != digits or not re.fullmatch(r"[0-9a-fA-F]+", code):
                        raise self.error(f"invalid \\{escape} escape in double-quoted value", index)
                    out.append(chr(int(code, 16)))
                    position += 2 + digits
                    continue
                if escape and escape in _DOUBLE_QUOTE_ESCAPES:
                    out.append(_DOUBLE_QUOTE_ESCAPES[escape])
                    position += 2
                    continue
                raise self.error(f"unsupported escape \\{escape} in double-quoted value", index)
            out.append(char)
            position += 1
        style = "single" if quote == "'" else "double"
        raise self.error(f"unterminated {style}-quoted text on this line", index)

    def parse_flow_map(self, path: str, text: str, index: int) -> dict:
        """Parse a flat one-line flow map such as {author: x, version: "1.0"}."""
        result: dict = {}
        position = 1

        def skip_spaces(at: int) -> int:
            while at < len(text) and text[at] in " \t":
                at += 1
            return at

        def flow_scalar(at: int, is_key: bool):
            char = text[at]
            if char in "{[":
                raise self.error(f"nested flow collections are not supported; {_BLOCK_FORM_HINT}", index)
            if char in "\"'":
                value, end = self.scan_quoted(text, at, index)
                return value, ("single" if char == "'" else "double"), text[at:end], end
            if char in "]},#&*!|>@`%" or (char in "-?:" and text[at + 1:at + 2] in ("", " ", "\t", ",", "}")):
                raise self.error(
                    f"a flow map {'key' if is_key else 'value'} cannot start with '{char}'; quote it",
                    index,
                )
            end = at
            while end < len(text):
                current = text[end]
                if current in ",}":
                    break
                if current in "{[]":
                    raise self.error(
                        f"nested flow collections are not supported; {_BLOCK_FORM_HINT}", index
                    )
                if current == ":" and text[end + 1:end + 2] in ("", " ", "\t", ",", "}"):
                    break
                if current == "#" and text[end - 1] in " \t":
                    raise self.error(f"comments are not allowed inside a flow map; {_BLOCK_FORM_HINT}", index)
                end += 1
            raw = text[at:end].rstrip(" \t")
            return (raw if is_key else resolve_plain_scalar(raw)), "plain", raw, end

        while True:
            position = skip_spaces(position)
            if position >= len(text):
                raise self.error(f"flow map is not closed with '}}' on the same line; {_BLOCK_FORM_HINT}", index)
            if text[position] == "}":
                position += 1
                break
            key, key_style, _, position = flow_scalar(position, is_key=True)
            position = skip_spaces(position)
            value, style, raw = None, "empty", ""
            if position < len(text) and text[position] == ":":
                position = skip_spaces(position + 1)
                if position < len(text) and text[position] not in ",}":
                    value, style, raw, position = flow_scalar(position, is_key=False)
                    position = skip_spaces(position)
            if key in result:
                raise self.error(f"Duplicate key in '{path}': {key}", index)
            result[key] = value
            self.record(f"{path}.{key}", index, style, raw)
            self.info[f"{path}.{key}"]["key_style"] = key_style
            if position < len(text) and text[position] == ",":
                position += 1
                continue
            if position < len(text) and text[position] == "}":
                position += 1
                break
            if position >= len(text):
                raise self.error(f"flow map is not closed with '}}' on the same line; {_BLOCK_FORM_HINT}", index)
            raise self.error(f"expected ',' or '}}' in flow map; {_BLOCK_FORM_HINT}", index)
        rest = text[position:]
        if rest.strip() and not re.match(r"[ \t]+#", rest):
            raise self.error(f"unexpected text after flow map: {rest.strip()!r}", index)
        self.pos = index + 1
        return result

    def parse_scalar(self, text: str, index: int, parent_indent: int):
        first = text[0]
        if first in "|>":
            return self.parse_block(text, index, parent_indent)
        if first in "\"'":
            return self.parse_quoted(text, index, parent_indent)
        if first in "[{":
            raise self.error(
                "flow collections ([...] or {...}) are not supported here by this validator's YAML "
                "subset (only a flat {key: value} map directly under 'metadata' is); "
                "quote the value if it is text, or use block form under 'metadata'",
                index,
            )
        if first in "]},":
            raise self.error(f"a value cannot start with '{first}'; quote the value", index)
        if first == "&":
            raise self.error("YAML anchors (&name) are not supported", index)
        if first == "*":
            raise self.error("YAML aliases (*name) are not supported; quote the value if it is text", index)
        if first == "!":
            raise self.error("YAML tags (!tag) are not supported; quote the value if it is text", index)
        if first in "@`%":
            raise self.error(f"a value cannot start with '{first}'; quote the value", index)
        if first in "-?:" and text[1:2] in ("", " ", "\t"):
            raise self.error(f"unexpected '{first}' indicator; quote the value if it is text", index)
        return self.parse_plain(text, index, parent_indent)

    def parse_plain(self, text: str, index: int, parent_indent: int):
        def take(segment: str, at: int) -> tuple[str, bool]:
            parts = re.split(r"[ \t]#", segment, maxsplit=1)
            content = parts[0].rstrip(" \t")
            if re.search(r":(?:[ \t]|$)", content):
                raise self.error(
                    "':' followed by a space is not allowed in an unquoted value; "
                    "quote the value or use a block scalar (|)",
                    at,
                )
            return content, len(parts) > 1

        value, commented = take(text, index)
        blank_lines = 0
        cursor = index + 1
        while cursor < len(self.lines):
            line = self.lines[cursor]
            if not line.strip():
                blank_lines += 1
                cursor += 1
                continue
            if _indent_of(line) <= parent_indent:
                break
            self.check_tabs(cursor)
            stripped = line.strip()
            if stripped.startswith("#"):
                commented = True
                cursor += 1
                continue
            if commented:
                raise self.error("a comment cannot be followed by more text of the same value", cursor)
            content, commented = take(stripped, cursor)
            value += ("\n" * blank_lines if blank_lines else " ") + content
            blank_lines = 0
            cursor += 1
        self.pos = cursor
        return resolve_plain_scalar(value), "plain"

    def parse_quoted(self, text: str, index: int, parent_indent: int):
        quote = text[0]
        style = "single" if quote == "'" else "double"
        out: list[str] = []
        protected = 0
        escaped_break = False
        cursor = index
        segment = text[1:]
        position = 0
        while True:
            if position >= len(segment):
                if not escaped_break:
                    while len(out) > protected and out[-1] in " \t":
                        out.pop()
                breaks = 0
                cursor += 1
                while True:
                    if cursor >= len(self.lines):
                        raise self.error(f"unterminated {style}-quoted value", index)
                    line = self.lines[cursor]
                    if not line.strip():
                        breaks += 1
                        cursor += 1
                        continue
                    if _indent_of(line) <= parent_indent:
                        raise self.error(
                            f"unterminated {style}-quoted value "
                            "(continuation lines must be indented)",
                            index,
                        )
                    break
                if breaks:
                    out.append("\n" * breaks)
                elif not escaped_break:
                    out.append(" ")
                protected = len(out) if escaped_break else protected
                escaped_break = False
                segment = self.lines[cursor].lstrip(" \t")
                position = 0
                continue
            char = segment[position]
            if quote == "'":
                if char == "'":
                    if segment[position + 1:position + 2] == "'":
                        out.append("'")
                        protected = len(out)
                        position += 2
                        continue
                    position += 1
                    break
                out.append(char)
                position += 1
                continue
            if char == '"':
                position += 1
                break
            if char != "\\":
                out.append(char)
                position += 1
                continue
            if position + 1 >= len(segment):
                escaped_break = True
                position += 1
                continue
            escape = segment[position + 1]
            if escape in "xuU":
                digits = {"x": 2, "u": 4, "U": 8}[escape]
                code = segment[position + 2:position + 2 + digits]
                if len(code) != digits or not re.fullmatch(r"[0-9a-fA-F]+", code):
                    raise self.error(f"invalid \\{escape} escape in double-quoted value", cursor)
                out.append(chr(int(code, 16)))
                position += 2 + digits
            elif escape in _DOUBLE_QUOTE_ESCAPES:
                out.append(_DOUBLE_QUOTE_ESCAPES[escape])
                position += 2
            else:
                raise self.error(f"unsupported escape \\{escape} in double-quoted value", cursor)
            protected = len(out)
        rest = segment[position:]
        if rest.strip() and (rest[0] not in " \t" or not rest.strip().startswith("#")):
            raise self.error(
                f"unexpected text after closing quote: {rest.strip()!r}; "
                "quote the whole value",
                cursor,
            )
        self.pos = cursor + 1
        return "".join(out), style

    def parse_block(self, text: str, index: int, parent_indent: int):
        match = re.fullmatch(r"([|>])([1-9+-]{0,2})(?:[ \t]+#.*)?[ \t]*", text)
        indicators = match.group(2) if match else ""
        digits = [c for c in indicators if c.isdigit()]
        chomps = [c for c in indicators if c in "+-"]
        if not match or len(digits) > 1 or len(chomps) > 1:
            raise self.error(f"invalid block scalar header: {text.strip()!r}", index)
        style = "literal" if match.group(1) == "|" else "folded"
        chomp = chomps[0] if chomps else ""

        cursor = index + 1
        if digits:
            indent = parent_indent + int(digits[0])
        else:
            indent = None
            longest_blank = 0
            probe = cursor
            while probe < len(self.lines) and not self.lines[probe].strip():
                longest_blank = max(longest_blank, _indent_of(self.lines[probe]))
                probe += 1
            if probe < len(self.lines) and _indent_of(self.lines[probe]) > parent_indent:
                indent = _indent_of(self.lines[probe])
                if longest_blank > indent:
                    raise self.error(
                        "a leading blank line in a block scalar is more indented than its first line",
                        probe,
                    )

        content: list[str] = []
        while cursor < len(self.lines):
            line = self.lines[cursor]
            if not line.strip():
                if indent is not None and len(line) > indent and line[:indent] == " " * indent:
                    content.append(line[indent:])
                else:
                    content.append("")
                cursor += 1
                continue
            if indent is None or _indent_of(line) < indent:
                break
            content.append(line[indent:])
            cursor += 1
        self.pos = cursor

        last = max((i for i, line in enumerate(content) if line), default=-1)
        lines = content[:last + 1]
        trailing = len(content) - len(lines)
        if style == "literal":
            value = "\n".join(lines)
        else:
            value = ""
            blank_lines = 0
            previous_more = False
            started = False
            for line in lines:
                if not line:
                    blank_lines += 1
                    continue
                more = line[0] in " \t"
                if not started:
                    value = "\n" * blank_lines + line
                    started = True
                elif more or previous_more:
                    value += "\n" * (blank_lines + 1) + line
                elif blank_lines:
                    value += "\n" * blank_lines + line
                else:
                    value += " " + line
                blank_lines = 0
                previous_more = more
        if last < 0:
            value = "\n" * trailing if chomp == "+" else ""
        elif chomp == "":
            value += "\n"
        elif chomp == "+":
            value += "\n" * (trailing + 1)
        return value, style


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


def load_frontmatter(content: str) -> Frontmatter:
    """Parse SKILL.md text; raises FrontmatterError (a ValueError) on bad syntax."""
    lines, body, body_line = split_frontmatter(content)
    parser = _FrontmatterParser(lines, first_line=2)
    data = parser.parse()
    return Frontmatter(data=data, info=parser.info, body=body, body_line=body_line)


def frontmatter_text(frontmatter: Frontmatter, key: str) -> str:
    """Return a field as text: strings as-is, other scalars as written, missing as ''."""
    value = frontmatter.data.get(key)
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, dict):
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
    """Decode a single-line quoted YAML scalar; other text is returned unchanged."""
    if not value or value[0] not in "\"'":
        return value
    decoded, _ = _FrontmatterParser([value], first_line=1).parse_quoted(value, 0, 0)
    return decoded


def is_safe_yaml_plain_scalar(value: str) -> bool:
    """Return whether a string remains the same YAML string when written unquoted."""
    if not value or value != value.strip() or "\n" in value:
        return False
    try:
        parser = _FrontmatterParser([f"k: {value}"], first_line=1)
        return parser.parse().get("k") == value and parser.info["k"]["style"] == "plain"
    except FrontmatterError:
        return False


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning (name, description, full_content)."""
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8-sig")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    name, description, _, _ = parse_frontmatter(normalized)
    return name, description, normalized

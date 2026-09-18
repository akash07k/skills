#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Build the trigger eval-set editor page from assets/eval_review.html.

Usage:
    python scripts/prepare_eval_review.py --eval-set <eval_set.json>
        --skill-path <skill-dir> --output <eval_review.html> [--open]

The page is written atomically. The browser opens only with --open.
"""

import argparse
import html
import json
import re
import sys
import webbrowser
from pathlib import Path

if sys.version_info < (3, 13):
    sys.exit("skill-creator scripts require Python 3.13 or later.")

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from scripts.utils import atomic_write_text, ensure_utf8_stdio, parse_skill_md

TEMPLATE_PATH = SKILL_ROOT / "assets" / "eval_review.html"
PLACEHOLDERS = re.compile(
    r"__(EVAL_DATA|SKILL_NAME|SKILL_DESCRIPTION)_PLACEHOLDER__"
)
SCRIPT_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def script_json(value: object) -> str:
    """Encode JSON that cannot close or break out of an inline script."""
    encoded = json.dumps(value, ensure_ascii=False)
    return re.sub("[<>&\u2028\u2029]", lambda match: SCRIPT_ESCAPES[match.group()], encoded)


def validate_eval_set(data: object) -> list[dict]:
    """Return a clean eval set or raise ValueError describing the problem."""
    if not isinstance(data, list) or not data:
        raise ValueError("eval set must be a nonempty JSON list")
    cleaned = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"entry {index} must be an object")
        query = item.get("query")
        should_trigger = item.get("should_trigger")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"entry {index} needs a nonempty string query")
        if not isinstance(should_trigger, bool):
            raise ValueError(f"entry {index} should_trigger must be true or false")
        cleaned.append({"query": query, "should_trigger": should_trigger})
    return cleaned


def render_page(eval_set: list[dict], skill_name: str, description: str, template: str | None = None) -> str:
    """Fill every template placeholder in one pass so data cannot inject placeholders."""
    template = template if template is not None else TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "EVAL_DATA": script_json(eval_set),
        "SKILL_NAME": html.escape(skill_name),
        "SKILL_DESCRIPTION": html.escape(description),
    }
    return PLACEHOLDERS.sub(lambda match: values[match.group(1)], template)


def main() -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="python scripts/prepare_eval_review.py",
        description="Create the trigger eval-set editor page",
    )
    parser.add_argument("--eval-set", type=Path, required=True, help="Trigger eval set JSON list")
    parser.add_argument("--skill-path", type=Path, required=True, help="Skill directory containing SKILL.md")
    parser.add_argument("--output", type=Path, required=True, help="HTML file to write")
    parser.add_argument("--open", action="store_true", help="Open the page in the default browser")
    args = parser.parse_args()

    try:
        eval_set = validate_eval_set(json.loads(args.eval_set.read_text(encoding="utf-8-sig")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Error: invalid eval set {args.eval_set}: {error}", file=sys.stderr)
        sys.exit(1)
    try:
        skill_name, description, _ = parse_skill_md(args.skill_path)
    except (OSError, ValueError) as error:
        print(f"Error: could not read SKILL.md in {args.skill_path}: {error}", file=sys.stderr)
        sys.exit(1)

    output = args.output.resolve()
    atomic_write_text(output, render_page(eval_set, skill_name, description))
    print(output)
    if args.open:
        webbrowser.open(output.as_uri())


if __name__ == "__main__":
    main()

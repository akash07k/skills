"""Tests for the frontmatter parser, quick_validate and package_skill."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path

from skill_path import SKILL
from scripts import package_skill as packager
from scripts import quick_validate
from scripts.utils import (
    FrontmatterError,
    decode_yaml_scalar,
    is_safe_yaml_plain_scalar,
    load_frontmatter,
    parse_frontmatter,
    parse_skill_md,
)


def fm(text: str) -> dict:
    return load_frontmatter(f"---\n{text}\n---\nBody.\n").data


def make_skill(root: Path, name: str, frontmatter: str, body: str = "Use this skill.\n") -> Path:
    skill = root / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return skill


def can_symlink(root: Path) -> bool:
    try:
        target = root / "symlink-probe-target"
        target.write_text("x", encoding="utf-8")
        os.symlink(target, root / "symlink-probe")
        os.symlink(root, root / "symlink-probe-dir", target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    finally:
        for name in ("symlink-probe", "symlink-probe-dir", "symlink-probe-target"):
            path = root / name
            if os.path.lexists(path):
                try:
                    os.unlink(path)
                except OSError:
                    os.rmdir(path)
    return True


def run_cli(module: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", f"scripts.{module}", *args],
        cwd=SKILL, capture_output=True, text=True, encoding="utf-8",
    )


class ScalarStyleTests(unittest.TestCase):
    def test_plain_scalars_fold_continuation_lines_and_strip_comments(self):
        self.assertEqual(fm("a: hello world # note")["a"], "hello world")
        self.assertEqual(fm("a: one\n  two\n\n  three")["a"], "one two\nthree")
        self.assertEqual(fm("a: http://example.com/x#frag")["a"], "http://example.com/x#frag")
        self.assertEqual(fm("a:\n  on next line")["a"], "on next line")

    def test_single_quoted(self):
        self.assertEqual(fm("a: 'it''s # not a comment'")["a"], "it's # not a comment")
        self.assertEqual(fm("a: 'line one\n  line two\n\n  para'")["a"], "line one line two\npara")

    def test_double_quoted_escapes(self):
        self.assertEqual(
            fm(r'a: "tab\there \"q\" back\\slash \u00e9 \x41 \U0001F600 nl\n"')["a"],
            'tab\there "q" back\\slash \u00e9 A \U0001F600 nl\n',
        )
        self.assertEqual(fm('a: "joined\\\n    here"')["a"], "joinedhere")
        self.assertEqual(fm('a: "folded\n  text"  # trailing comment')["a"], "folded text")

    def test_literal_block_chomping(self):
        source = "a: |{}\n  one\n    two\n\n  three\n\n\nb: x"
        self.assertEqual(fm(source.format(""))["a"], "one\n  two\n\nthree\n")
        self.assertEqual(fm(source.format("-"))["a"], "one\n  two\n\nthree")
        self.assertEqual(fm(source.format("+"))["a"], "one\n  two\n\nthree\n\n\n")
        self.assertEqual(fm("a: |1\n   indented\nb: x")["a"], "  indented\n")
        self.assertEqual(fm("a: |2-\n    x\nb: y")["a"], "  x")

    def test_folded_block_chomping(self):
        source = "a: >{}\n  one\n  two\n\n  three\n    more\n  four\n\n"
        self.assertEqual(fm(source.format(""))["a"], "one two\nthree\n  more\nfour\n")
        self.assertEqual(fm(source.format("-"))["a"], "one two\nthree\n  more\nfour")
        self.assertEqual(fm(source.format("+"))["a"], "one two\nthree\n  more\nfour\n\n\n")
        self.assertEqual(fm("a: >-  # comment\n  x\n  y")["a"], "x y")

    def test_empty_values_and_comments(self):
        data = fm("# leading comment\na:\nb: # only comment\nc: ''\nd: |\ne: x")
        self.assertIsNone(data["a"])
        self.assertIsNone(data["b"])
        self.assertEqual(data["c"], "")
        self.assertEqual(data["d"], "")
        self.assertEqual(data["e"], "x")

    def test_metadata_mapping(self):
        data = fm(
            "metadata:\n  author: Jane Doe\n  version: \"1.0\"\n  note: |\n    multi\n"
            "  # comment\n  quoted: 'a: b'\nname: x"
        )
        self.assertEqual(
            data["metadata"],
            {"author": "Jane Doe", "version": "1.0", "note": "multi\n", "quoted": "a: b"},
        )
        self.assertEqual(data["name"], "x")

    def test_plain_resolution_matches_yaml_types(self):
        data = fm(
            "a: yes\nb: No\nc: on\nd: OFF\ne: y\nf: true\ng: null\nh: ~\n"
            "i: 42\nj: 1.5\nk: 0x1F\nl: 2024-01-02\nm: .inf\nn: yesterday\no: 1.2.3"
        )
        self.assertIs(data["a"], True)
        self.assertIs(data["b"], False)
        self.assertIs(data["c"], True)
        self.assertIs(data["d"], False)
        self.assertIs(data["e"], True)
        self.assertIs(data["f"], True)
        self.assertIsNone(data["g"])
        self.assertIsNone(data["h"])
        self.assertEqual(data["i"], 42)
        self.assertEqual(data["j"], 1.5)
        self.assertEqual(data["k"], 31)
        self.assertEqual(data["l"], date(2024, 1, 2))
        self.assertEqual(data["m"], float("inf"))
        self.assertEqual(data["n"], "yesterday")
        self.assertEqual(data["o"], "1.2.3")

    def test_crlf_and_bom(self):
        content = "\ufeff---\r\nname: demo\r\ndescription: |\r\n  Line.\r\n---\r\nBody\r\n"
        data = load_frontmatter(content).data
        self.assertEqual(data, {"name": "demo", "description": "Line.\n"})


class RejectedConstructTests(unittest.TestCase):
    def assert_rejected(self, text: str, fragment: str, line: int | None = None):
        with self.assertRaises(FrontmatterError) as caught:
            fm(text)
        self.assertIn(fragment, str(caught.exception))
        if line is not None:
            self.assertEqual(caught.exception.line, line)

    def test_rejections_have_clear_line_numbered_messages(self):
        cases = (
            ("name: x\ntools: [a, b]", "flow collections", 3),
            ("a: {k: v}", "flow collections", 2),
            ("a: &anchor x", "anchors", 2),
            ("a: *alias", "aliases", 2),
            ("a: !tag x", "tags", 2),
            ("a: x\nb:\n  nested: map", "nested mappings", 4),
            ("metadata:\n  a:\n    b: c", "nested mappings", 4),
            ("a: x\na: y", "Duplicate frontmatter property: a", 3),
            ("metadata:\n  k: 1\n  k: 2", "Duplicate key in 'metadata': k", 4),
            ("\ta: x", "tabs", 2),
            ("metadata:\n\tk: v", "tabs", 3),
            ("b:\n  - item", "sequences", 3),
            ("- item", "sequences", 2),
            ("a: b: c", "quote the value", 2),
            ('a: "x" y', "unexpected text after closing quote", 2),
            ("a: 'open", "unterminated", 2),
            ("a: x\n  extra: y", "quote the value", 3),
            ("name:value", "separated from keys by a space", 2),
            ('"quoted": key', "quoted keys", 2),
            ("a: |x\n  y", "invalid block scalar header", 2),
            ('a: "\\q"', "unsupported escape", 2),
            ("a: @x", "cannot start with '@'", 2),
            ("  a: x", "unexpected indentation", 2),
        )
        for text, fragment, line in cases:
            with self.subTest(text=text):
                self.assert_rejected(text, fragment, line)

    def test_missing_fences(self):
        with self.assertRaisesRegex(FrontmatterError, "no opening ---"):
            load_frontmatter("name: x\n")
        with self.assertRaisesRegex(FrontmatterError, "no closing ---"):
            load_frontmatter("---\nname: x\n")


class CompatibilityHelperTests(unittest.TestCase):
    def test_parse_frontmatter_tuple(self):
        name, description, raw, keys = parse_frontmatter(
            "---\nname: demo\ndescription: |\n  Hi.\nlicense: MIT\n---\n"
        )
        self.assertEqual((name, description, raw, keys), ("demo", "Hi.\n", "|", {"name", "description", "license"}))

    def test_decode_and_plain_safety_helpers(self):
        self.assertEqual(decode_yaml_scalar("'it''s'"), "it's")
        self.assertEqual(decode_yaml_scalar('"a\\tb"'), "a\tb")
        self.assertEqual(decode_yaml_scalar("plain"), "plain")
        self.assertTrue(is_safe_yaml_plain_scalar("Use when asked."))
        for unsafe in ("yes", "123", "a: b", "a #b", "[x]", " x", "", "*x"):
            with self.subTest(unsafe=unsafe):
                self.assertFalse(is_safe_yaml_plain_scalar(unsafe))

    def test_parse_skill_md(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(Path(temporary), "demo", "name: demo\ndescription: >-\n  Folded\n  text.")
            self.assertEqual(parse_skill_md(skill)[:2], ("demo", "Folded text."))


class ValidationRuleTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()

    def check(self, folder: str, frontmatter: str, body: str = "Use this skill.\n"):
        return quick_validate.check_skill(make_skill(self.root, folder, frontmatter, body))

    def assert_error(self, folder, frontmatter, fragment):
        result = self.check(folder, frontmatter)
        self.assertFalse(result.valid, frontmatter)
        self.assertTrue(any(fragment in error for error in result.errors), result.errors)

    def test_valid_minimal_and_full(self):
        result = self.check(
            "full-skill",
            "name: full-skill\ndescription: Does things. Use when asked.\nlicense: MIT\n"
            "compatibility: Requires Python 3.10+\nallowed-tools: Bash(git:*) Read\n"
            "metadata:\n  author: me\n  version: '1.0'",
        )
        self.assertEqual((result.errors, result.warnings), ([], []))

    def test_name_rules(self):
        self.assert_error("Demo", "name: Demo\ndescription: Use when x.", "must be lowercase")
        self.assert_error("a--b", "name: a--b\ndescription: Use when x.", "consecutive hyphens")
        self.assert_error("-ab", "name: -ab\ndescription: Use when x.", "start or end with a hyphen")
        self.assert_error("ab-", "name: ab-\ndescription: Use when x.", "start or end with a hyphen")
        self.assert_error("a_b", "name: a_b\ndescription: Use when x.", "invalid characters")
        long_name = "a" * 65
        self.assert_error(long_name, f"name: {long_name}\ndescription: Use when x.", "too long")
        self.assert_error("other", "name: demo\ndescription: Use when x.", "must match the skill directory")
        self.assert_error("x", "description: Use when x.", "Missing 'name'")
        self.assert_error("x", "name: ''\ndescription: Use when x.", "non-empty")
        self.assertTrue(self.check("a" * 64, f"name: {'a' * 64}\ndescription: Use when x.").valid)

    def test_unicode_lowercase_name_and_nfkc_folder_match(self):
        self.assertTrue(self.check("café-skill", "name: café-skill\ndescription: Use when x.").valid)
        self.assertTrue(self.check("東京", "name: 東京\ndescription: Use when x.").valid)
        self.assert_error("ÉCOLE", "name: ÉCOLE\ndescription: Use when x.", "lowercase")
        # Folder uses a decomposed é (NFD); the name uses the composed form.
        result = self.check("cafe\u0301", "name: caf\u00e9\ndescription: Use when x.")
        self.assertTrue(result.valid, result.errors)

    def test_description_and_compatibility_limits(self):
        ok = "x" * 1015 + " use when"
        self.assertTrue(self.check("d", f"name: d\ndescription: {ok}").valid)
        self.assert_error("d", f"name: d\ndescription: {'x' * 1025}", "Description is too long")
        self.assert_error("d", "name: d\ndescription: '   '", "non-empty")
        self.assert_error("d", "name: d", "Missing 'description'")
        base = "name: d\ndescription: Use when x.\ncompatibility: "
        self.assertTrue(self.check("d", base + "y" * 500).valid)
        self.assert_error("d", base + "y" * 501, "Compatibility is too long")
        self.assert_error("d", base + "''", "must not be empty")

    def test_boolean_like_and_numeric_plain_values_are_rejected(self):
        for value, kind in (("yes", "boolean"), ("off", "boolean"), ("null", "null"), ("42", "integer"), ("1.0", "number")):
            with self.subTest(value=value):
                self.assert_error("d", f"name: d\ndescription: {value}", f"YAML {kind}; quote it")
        self.assert_error("d", "name: d\ndescription: Use when x.\nmetadata:\n  version: 1.0", "'metadata.version'")
        self.assert_error("d", "name: d\ndescription: Use when x.\nlicense: true", "'license'")
        self.assert_error("d", "name: d\ndescription: Use when x.\nmetadata: plain", "'metadata' must be a mapping")
        self.assertTrue(self.check("d", "name: d\ndescription: \"yes, use when x\"").valid)

    def test_unknown_keys_and_all_errors_reported(self):
        result = self.check("good-name", "name: Bad--Name\ndescription: ''\nfoo: bar\ncompatibility: ''")
        joined = "\n".join(result.errors)
        for fragment in ("Unexpected key(s) in SKILL.md frontmatter: foo", "lowercase",
                         "consecutive hyphens", "must match", "description' must be a non-empty",
                         "'compatibility' must not be empty"):
            self.assertIn(fragment, joined)
        valid, message = quick_validate.validate_skill(self.root / "good-name")
        self.assertFalse(valid)
        self.assertEqual(message, joined)

    def test_warnings(self):
        result = self.check("d", "name: d\ndescription: Formats <tags> nicely.", body="line\n" * 501)
        self.assertTrue(result.valid)
        warnings = "\n".join(result.warnings)
        self.assertIn("angle brackets", warnings)
        self.assertIn("when to use", warnings)
        self.assertIn("501 lines", warnings)

    def assert_warning(self, result, fragment):
        self.assertTrue(result.valid, result.errors)
        self.assertTrue(any(fragment in warning for warning in result.warnings), result.warnings)

    def test_name_with_surrounding_whitespace_is_an_error(self):
        self.assert_error("d", 'name: " d "\ndescription: Use when x.', "leading or trailing whitespace")
        self.assert_error("d", "name: 'd '\ndescription: Use when x.", "leading or trailing whitespace")
        self.assertTrue(self.check("d", "name: d   \ndescription: Use when x.").valid)

    def test_description_length_counts_raw_text_but_not_block_newline(self):
        text = "use when " + "x" * 1015
        self.assertEqual(len(text), 1024)
        result = self.check("d", f"name: d\ndescription: |\n  {text}\n")
        self.assertEqual(result.errors, [])
        self.assertTrue(self.check("d", f"name: d\ndescription: >\n  {text}").valid)
        self.assert_error("d", f'name: d\ndescription: "  {text}"', "Description is too long (1026")
        self.assertTrue(self.check("d", f"name: d\ndescription: {text}").valid)

    def test_body_token_warning(self):
        frontmatter = "name: d\ndescription: Use when x."
        self.assertEqual(self.check("d", frontmatter, body="x" * 20000).warnings, [])
        self.assert_warning(self.check("d", frontmatter, body="x" * 20004), "about 5001 tokens")

    def test_metadata_keys_must_resolve_to_strings(self):
        for key, kind in (("1", "integer"), ("1.5", "number"), ("yes", "boolean"), ("Off", "boolean"),
                          ("null", "null"), ("2024-01-02", "timestamp")):
            with self.subTest(key=key):
                result = self.check("d", f"name: d\ndescription: Use when x.\nmetadata:\n  {key}: v")
                self.assertFalse(result.valid)
                self.assertIn(f"line 5: metadata keys must be strings; quote the key", result.errors[0])
                self.assertIn(f"YAML {kind}", result.errors[0])
        result = self.check(
            "d", "name: d\ndescription: Use when x.\nmetadata:\n  \"1\": v\n  'yes': w\n  \"a\\tb\": x\n  ok-key: yv"
        )
        self.assertEqual(result.errors, [])
        self.assert_error("d", "name: d\ndescription: Use when x.\nmetadata: {1: v}", "metadata keys must be strings")

    def test_metadata_flow_map(self):
        base = "name: d\ndescription: Use when x.\nmetadata: "
        result = self.check("d", base + '{author: Jane Doe, version: "1.0", \'q\': \'it\'\'s\'}  # note')
        self.assertEqual((result.errors, result.warnings), ([], []))
        self.assertEqual(
            fm(base + '{author: Jane Doe, version: "1.0", \'q\': \'it\'\'s\'}')["metadata"],
            {"author": "Jane Doe", "version": "1.0", "q": "it's"},
        )
        self.assertEqual(fm(base + "{}")["metadata"], {})
        self.assertEqual(fm(base + "{a: b,}")["metadata"], {"a": "b"})
        self.assertEqual(fm(base + "{url: http://x.example/a}")["metadata"], {"url": "http://x.example/a"})
        self.assertEqual(fm("metadata:\n  {a: b}\nname: x")["metadata"], {"a": "b"})
        self.assertTrue(self.check("d", base + "{}").valid)
        self.assert_error("d", base + "{version: 1.0}", "'metadata.version'")
        self.assert_error("d", base + "{a}", "'metadata.a'")

    def test_flow_map_limitations_are_explained(self):
        cases = (
            ("metadata: {a: {b: c}}", "nested flow collections"),
            ("metadata: {a: [b, c]}", "nested flow collections"),
            ("metadata: {a: b", "not closed"),
            ("metadata: {a: b, a: c}", "Duplicate key in 'metadata': a"),
            ("metadata: {a: b} extra", "unexpected text after flow map"),
            ("metadata: {a b: c d e: f}", "expected ','"),
            ("metadata: {a: b # c}", "comments are not allowed"),
        )
        for text, fragment in cases:
            with self.subTest(text=text):
                with self.assertRaises(FrontmatterError) as caught:
                    fm(text)
                self.assertIn(fragment, str(caught.exception))
        for text in ("metadata: {a: {b: c}}", "license: {a: b}", "metadata:\n  a: {b: c}"):
            with self.subTest(text=text):
                with self.assertRaises(FrontmatterError) as caught:
                    fm(text)
                self.assertIn("validator's YAML subset", str(caught.exception))
                self.assertIn("metadata", str(caught.exception))

    def test_client_specific_fields_warn_or_fail_in_strict_mode(self):
        frontmatter = (
            "name: d\ndescription: Use when x.\nargument-hint: '[file]'\n"
            "user-invocable: true\ndisable-model-invocation: false"
        )
        result = self.check("d", frontmatter)
        self.assert_warning(result, "argument-hint, disable-model-invocation, user-invocable")
        self.assertIn("not part of the Agent Skills spec", result.warnings[0])
        strict = quick_validate.check_skill(self.root / "d", strict=True)
        self.assertFalse(strict.valid)
        self.assertIn("Client-specific key(s)", strict.errors[0])
        self.assertEqual(strict.warnings, [])
        result = self.check("d", "name: d\ndescription: Use when x.\nuser-invocable: true\nfoo: bar")
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Unexpected key(s) in SKILL.md frontmatter: foo", result.errors[0])

    def test_body_link_and_file_reference_warnings(self):
        skill = self.root / "d"
        (skill / "references" / "deep").mkdir(parents=True)
        (skill / "references" / "ok.md").write_text("x", encoding="utf-8")
        (skill / "references" / "deep" / "b.md").write_text("x", encoding="utf-8")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text("x", encoding="utf-8")
        body = (
            "Use this skill.\n"
            "[ok](references/ok.md) [frag](references/ok.md#part) [dot](./references/ok.md \"t\")\n"
            "[web](https://example.com/x) [mail](mailto:a@b.c) [anchor](#top) ![img](<references/ok.md>)\n"
            "Run `scripts\\run.py` or `scripts/run.py --flag`, see `other/thing.md`.\n"
            "Example: \"Read `references/example.md` when deploying\".\n"
            "```md\n[fenced](references/fenced.md) `references/fenced2.md`\n```\n"
            "Inline `[code](references/inline.md)` is ignored.\n"
            "[missing](references/missing.md) and `references/gone.md`\n"
            "[win](C:\\Users\\x\\a.md) [posix](/etc/passwd)\n"
            "[nested](references/deep/b.md) [out](../outside.md)\n"
            "[ref]: references/undefined-ref.md\n"
        )
        result = self.check("d", "name: d\ndescription: Use when x.", body=body)
        self.assertTrue(result.valid, result.errors)
        warnings = "\n".join(result.warnings)
        for fragment in (
            "Link 'references/missing.md' does not exist",
            "File reference 'references/gone.md' does not exist",
            "Link 'references/undefined-ref.md' does not exist",
            "Link 'C:\\\\Users\\\\x\\\\a.md' is an absolute path",
            "Link '/etc/passwd' is an absolute path",
            "Link '../outside.md' points outside the skill folder",
        ):
            self.assertIn(fragment, warnings)
        self.assertNotIn("references/deep/b.md", warnings)
        self.assertEqual(len(result.warnings), 6, result.warnings)

    def test_skill_md_must_be_named_exactly(self):
        skill = self.root / "d"
        skill.mkdir()
        (skill / "skill.md").write_text("---\nname: d\ndescription: Use when x.\n---\nBody\n", encoding="utf-8")
        result = quick_validate.check_skill(skill)
        self.assertFalse(result.valid)
        self.assertIn("found 'skill.md'", result.errors[0])
        self.assertIn("exactly 'SKILL.md'", result.errors[0])
        self.assertFalse(quick_validate.check_skill(skill / "skill.md").valid)

    def test_non_ascii_name_warns(self):
        self.assert_warning(self.check("café-skill", "name: café-skill\ndescription: Use when x."), "non-ASCII")
        self.assertEqual(self.check("cafe-skill", "name: cafe-skill\ndescription: Use when x.").warnings, [])

    def test_empty_license_warns(self):
        for value in ('""', "'   '"):
            with self.subTest(value=value):
                result = self.check("d", f"name: d\ndescription: Use when x.\nlicense: {value}")
                self.assert_warning(result, "license is empty; remove it or name a license")

    def test_unreadable_inputs(self):
        skill = self.root / "bad-utf8"
        skill.mkdir()
        (skill / "SKILL.md").write_bytes(b"---\nname: bad-utf8\ndescription: \xff\n---\n")
        self.assertIn("not valid UTF-8", quick_validate.check_skill(skill).errors[0])
        self.assertIn("SKILL.md not found", quick_validate.check_skill(self.root).errors[0])
        self.assertIn("not found", quick_validate.check_skill(self.root / "missing").errors[0])


class CliTests(unittest.TestCase):
    def test_quick_validate_cli_exit_codes_and_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = make_skill(root, "good", "name: good\ndescription: Use when testing.")
            bad = make_skill(root, "bad", "name: Bad\ndescription: yes\nextra: 1")
            ok = run_cli("quick_validate", str(good))
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("Skill is valid!", ok.stdout)
            failed = run_cli("quick_validate", str(bad))
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(failed.stdout, "")
            self.assertEqual(failed.stderr.count("error: "), 4, failed.stderr)
            self.assertEqual(run_cli("quick_validate", str(root / "missing")).returncode, 1)
        usage = run_cli("quick_validate")
        self.assertEqual(usage.returncode, 2)
        self.assertIn("usage:", usage.stderr)
        help_result = run_cli("quick_validate", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("skill_directory", help_result.stdout)
        self.assertIn("python scripts/quick_validate.py", help_result.stdout)
        self.assertIn("--strict", help_result.stdout)
        self.assertIn("--json", help_result.stdout)

    def test_quick_validate_json_and_strict_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = make_skill(root, "good", "name: good\ndescription: Use when testing.\nuser-invocable: true")
            bad = make_skill(root, "bad", "name: Bad\ndescription: Use when testing.")
            ok = run_cli("quick_validate", "--json", str(good))
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(ok.stderr, "")
            payload = json.loads(ok.stdout)
            self.assertEqual(set(payload), {"path", "valid", "errors", "warnings"})
            self.assertEqual((payload["path"], payload["valid"], payload["errors"]), (str(good), True, []))
            self.assertEqual(len(payload["warnings"]), 1)
            failed = run_cli("quick_validate", str(bad), "--json")
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(failed.stderr, "")
            self.assertFalse(json.loads(failed.stdout)["valid"])
            missing = run_cli("quick_validate", "--json", str(root / "missing"))
            self.assertEqual(missing.returncode, 1)
            self.assertIn("not found", json.loads(missing.stdout)["errors"][0])
            self.assertEqual(run_cli("quick_validate", "--json").returncode, 2)

            strict = run_cli("quick_validate", "--strict", str(good))
            self.assertEqual(strict.returncode, 1)
            self.assertIn("error: Client-specific key(s)", strict.stderr)
            loose = run_cli("quick_validate", str(good))
            self.assertEqual(loose.returncode, 0)
            self.assertIn("warning: Client-specific key(s)", loose.stderr)

    def test_quick_validate_runs_as_script_from_any_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            good = make_skill(Path(temporary), "good", "name: good\ndescription: Use when testing.")
            result = subprocess.run(
                [sys.executable, str(SKILL / "scripts" / "quick_validate.py"), str(good)],
                cwd=temporary, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Skill is valid!", result.stdout)

    def test_package_cli_help_and_usage(self):
        help_result = run_cli("package_skill", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("output_dir", help_result.stdout)
        self.assertEqual(run_cli("package_skill").returncode, 2)

    def test_package_cli_refuses_invalid_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad = make_skill(root, "bad", "name: Bad\ndescription: Use when x.")
            result = run_cli("package_skill", str(bad), str(root / "out"))
            self.assertEqual(result.returncode, 1)
            self.assertIn("lowercase", result.stderr)
            self.assertFalse((root / "out" / "bad.skill").exists())


class PackagingTests(unittest.TestCase):
    def package(self, skill: Path, output: Path) -> list[str]:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            archive_path = packager.package_skill(skill, output)
        self.assertIsNotNone(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            return archive.namelist()

    def test_excludes_dotfiles_caches_and_dirs_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(root, "demo", "name: demo\ndescription: Use when x.")
            for relative in (
                ".env", ".DS_Store", "scripts/.hidden", ".Pytest_Cache/x", "scripts/__PYCACHE__/m.pyc",
                "Node_Modules/p/index.js", ".git/config", "VENV/lib.py", ".venv/lib.py",
                "scripts/mod.PYC", "Tests/test_x.py", "EVALS/evals.json", "demo-Workspace/out.txt",
                "scripts/tool.py", "references/guide.md", "assets/.keep",
            ):
                path = skill / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")
            names = self.package(skill, root / "out")
        self.assertEqual(
            sorted(names),
            ["demo/SKILL.md", "demo/references/guide.md", "demo/scripts/tool.py"],
        )

    def test_packages_files_with_pre_1980_timestamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(root, "demo", "name: demo\ndescription: Use when x.")
            old_file = skill / "assets" / "old.txt"
            old_file.parent.mkdir()
            old_file.write_text("old", encoding="utf-8")
            old_time = datetime(1975, 1, 1).timestamp()
            os.utime(old_file, (old_time, old_time))

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive_path = packager.package_skill(skill, root / "out")

            self.assertIsNotNone(archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.getinfo("demo/assets/old.txt").date_time[:3], (1980, 1, 1))

    def test_skips_symlinks_inside_skill_but_follows_symlinked_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            if not can_symlink(root):
                self.skipTest("symlinks are not available")
            skill = make_skill(root, "demo", "name: demo\ndescription: Use when x.")
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            os.symlink(outside / "secret.txt", skill / "linked.txt")
            os.symlink(outside, skill / "linked-dir", target_is_directory=True)
            (skill / "real.txt").write_text("real", encoding="utf-8")
            names = self.package(skill, root / "out")
            self.assertEqual(sorted(names), ["demo/SKILL.md", "demo/real.txt"])

            alias_parent = root / "alias"
            alias_parent.mkdir()
            os.symlink(skill, alias_parent / "demo", target_is_directory=True)
            names = self.package(alias_parent / "demo", root / "out2")
            self.assertEqual(sorted(names), ["demo/SKILL.md", "demo/real.txt"])

    def test_refuses_invalid_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(root, "demo", "name: demo\ndescription: yes")
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertIsNone(packager.package_skill(skill, root / "out"))
            self.assertIn("quote it", stderr.getvalue())
            self.assertFalse((root / "out").exists())

    def test_should_exclude_helper(self):
        self.assertTrue(packager.should_exclude(Path("demo/.env")))
        self.assertTrue(packager.should_exclude(Path("demo/TESTS/x.py")))
        self.assertTrue(packager.should_exclude(Path("demo/a/__pycache__/x.py")))
        self.assertFalse(packager.should_exclude(Path("demo/scripts/tests/x.py")))
        self.assertFalse(packager.should_exclude(Path("demo/scripts/x.py")))


class RealSkillTests(unittest.TestCase):
    def test_skill_creator_is_valid(self):
        result = quick_validate.check_skill(SKILL)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()

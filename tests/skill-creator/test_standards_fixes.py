"""Regression cases for portable YAML, targeted clients, and packaging."""

import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from skill_path import SKILL
from scripts import package_skill, quick_validate


def make_skill(root, name, frontmatter, body="# Instructions\n\nPerform the task.\n"):
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return skill


class StandardsValidationTests(unittest.TestCase):
    def test_quoted_keys_and_yaml_aliases_are_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(
                Path(temporary), "quoted-doc",
                '"name": quoted-doc\n'
                '"description": &description "Use this skill when checking a document."\n'
                "license: *description",
            )
            result = quick_validate.check_skill(skill)
            self.assertTrue(result.valid, result.errors)

    def test_yaml_12_string_scalars_and_number_types(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("yes", "on", "off"):
                skill = make_skill(
                    root, name,
                    f"name: {name}\ndescription: 2024-01-02\nmetadata:\n  on: yes",
                )
                result = quick_validate.check_skill(skill, target="portable")
                self.assertTrue(result.valid, result.errors)
            skill = make_skill(
                root, "number",
                "name: number\ndescription: 08",
            )
            self.assertFalse(quick_validate.check_skill(skill, target="portable").valid)

    def test_yaml_merge_keys_are_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(
                Path(temporary), "merge-skill",
                '<<: {name: merge-skill, description: "Use when testing YAML merges."}\n'
                'metadata: {<<: {author: Example, version: "1.0"}, version: "2.0"}',
            )
            result = quick_validate.check_skill(skill, target="portable")
            self.assertTrue(result.valid, result.errors)

    def test_claude_extension_requires_explicit_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(
                Path(temporary), "task-brief",
                "name: task-brief\n"
                "description: Use this skill when summarizing a task.\n"
                "context: fork",
            )
            self.assertFalse(quick_validate.check_skill(skill, strict=True).valid)
            result = quick_validate.check_skill(skill, target="claude-code")
            self.assertTrue(result.valid, result.errors)
            self.assertFalse(quick_validate.check_skill(skill, target="codex").valid)

    def test_client_target_rejects_unknown_extensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(
                Path(temporary), "task-brief",
                "name: task-brief\n"
                "description: Use this skill when summarizing a task.\n"
                "context: fork\nunknown-field: value",
            )
            result = quick_validate.check_skill(skill, target="claude-code")
            self.assertFalse(result.valid)
            self.assertTrue(any("unknown-field" in error for error in result.errors))

    def test_targeted_client_fields_validate_their_types(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "task-brief",
                "name: task-brief\n"
                "description: Use this skill when summarizing a task.\n"
                "context: fork\nbackground: false\nallowed-tools: [Read, Grep]",
            )
            result = quick_validate.check_skill(skill, strict=True, target="claude-code")
            self.assertTrue(result.valid, result.errors)
            self.assertFalse(quick_validate.check_skill(skill, target="copilot").valid)
            (skill / "SKILL.md").write_text(
                "---\nname: task-brief\ndescription: Use when summarizing a task.\n"
                "context: invalid\nbackground: perhaps\n---\nBody\n",
                encoding="utf-8",
            )
            result = quick_validate.check_skill(skill, target="claude-code")
            self.assertFalse(result.valid)
            self.assertTrue(any("context" in error for error in result.errors))
            self.assertTrue(any("background" in error for error in result.errors))

    def test_copilot_extension_requires_explicit_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = make_skill(
                Path(temporary), "task-brief",
                "name: task-brief\ndescription: Use when summarizing a task.\n"
                "user-invocable: false\ndisable-model-invocation: true",
            )
            result = quick_validate.check_skill(skill, strict=True, target="copilot")
            self.assertTrue(result.valid, result.errors)
            self.assertFalse(quick_validate.check_skill(skill, strict=True, target="portable").valid)

    def test_unsafe_yaml_object_tags_cannot_execute(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "executed"
            skill = make_skill(
                root, "unsafe-tag",
                "name: unsafe-tag\n"
                "description: Use this skill when testing.\n"
                f"license: !!python/object/apply:os.system ['touch {marker.as_posix()}']",
            )
            self.assertFalse(quick_validate.check_skill(skill).valid)
            self.assertFalse(marker.exists())


class StandardsPackagingTests(unittest.TestCase):
    @staticmethod
    def agnix_result(code=0, errors=0, warnings=0, checked=1):
        return subprocess.CompletedProcess(
            args=[], returncode=code,
            stdout=json.dumps({
                "version": "test-version",
                "files_checked": checked,
                "summary": {"errors": errors, "warnings": warnings, "info": 0},
            }),
            stderr="",
        )

    def test_package_includes_referenced_hidden_template_not_unrelated_env(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use this skill when preparing a document.",
                "# Instructions\n\nRead [the template](assets/.template).\n",
            )
            (skill / "assets").mkdir()
            (skill / "assets" / ".template").write_bytes(b"Document template.\n")
            (skill / ".env").write_text("EXAMPLE_ONLY=NOT_A_SECRET\n", encoding="utf-8")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()) as run, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out")
            self.assertIsNotNone(archive)
            self.assertTrue(run.called)
            with zipfile.ZipFile(archive) as result:
                self.assertIn("hidden-template/assets/.template", result.namelist())
                self.assertNotIn("hidden-template/.env", result.namelist())
                self.assertEqual(result.read("hidden-template/assets/.template"), b"Document template.\n")

    def test_package_rejects_referenced_secret_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "sensitive-template",
                "name: sensitive-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the config](assets/.env).\n",
            )
            (skill / "assets").mkdir()
            (skill / "assets" / ".env").write_text("EXAMPLE_ONLY=NOT_A_SECRET\n", encoding="utf-8")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out")
            self.assertIsNone(archive)
            self.assertFalse((root / "out" / "sensitive-template.skill").exists())

    def test_package_rejects_secret_like_content_even_after_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the template](assets/.template).\n",
            )
            (skill / "assets").mkdir()
            (skill / "assets" / ".template").write_text(
                "password = example-not-a-real-secret\n", encoding="utf-8",
            )
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(
                    skill, root / "out", reviewed_hidden=("assets/.template",),
                )
            self.assertIsNone(archive)

    def test_package_includes_hidden_template_referenced_in_a_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\n```sh\ncat assets/.template\n```\n",
            )
            (skill / "assets").mkdir()
            (skill / "assets" / ".template").write_bytes(b"Document template.\n")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out")
            self.assertIsNotNone(archive)
            with zipfile.ZipFile(archive) as result:
                self.assertIn("hidden-template/assets/.template", result.namelist())

    def test_package_includes_hidden_template_referenced_from_a_guide(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the guide](references/guide.md).\n",
            )
            (skill / "references").mkdir()
            (skill / "assets").mkdir()
            (skill / "references" / "guide.md").write_text(
                "[Template](../assets/.template)\n[Guide](guide.md)\n", encoding="utf-8",
            )
            (skill / "assets" / ".template").write_bytes(b"Document template.\n")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out")
            self.assertIsNotNone(archive)
            with zipfile.ZipFile(archive) as result:
                self.assertIn("hidden-template/assets/.template", result.namelist())

    def test_hidden_symlink_keeps_its_referenced_archive_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the template](assets/.template).\n",
            )
            assets = skill / "assets"
            assets.mkdir()
            (assets / "template.txt").write_bytes(b"Document template.\n")
            try:
                (assets / ".template").symlink_to("template.txt")
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out")
            self.assertIsNotNone(archive)
            with zipfile.ZipFile(archive) as result:
                self.assertEqual(result.read("hidden-template/assets/.template"), b"Document template.\n")

    def test_hidden_symlink_cannot_disguise_a_sensitive_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the template](assets/.template).\n",
            )
            assets = skill / "assets"
            assets.mkdir()
            (assets / ".env").write_text("EXAMPLE_ONLY=NOT_A_SECRET\n", encoding="utf-8")
            try:
                (assets / ".template").symlink_to(".env")
            except OSError as error:
                self.skipTest(f"symbolic links unavailable: {error}")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(package_skill.package_skill(skill, root / "out"))

    def test_referenced_excluded_resource_blocks_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the template](evals/template.txt).\n",
            )
            (skill / "evals").mkdir()
            (skill / "evals" / "template.txt").write_text("Template.\n", encoding="utf-8")
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out")
            self.assertIsNone(archive)

    def test_package_refuses_when_agnix_fails_or_checks_no_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(root, "safe", "name: safe\ndescription: Use when preparing a document.")
            for result in (
                self.agnix_result(code=1, errors=1),
                self.agnix_result(checked=0),
            ):
                with self.subTest(result=result), \
                        mock.patch.object(package_skill.subprocess, "run", return_value=result), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertIsNone(package_skill.package_skill(skill, root / "out"))
                self.assertFalse((root / "out" / "safe.skill").exists())

    def test_package_requires_review_for_ambiguous_hidden_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "hidden-template",
                "name: hidden-template\ndescription: Use when preparing a document.",
                "# Instructions\n\nRead [the template](assets/.template).\n",
            )
            (skill / "assets").mkdir()
            payload = b"\xff\x00binary"
            (skill / "assets" / ".template").write_bytes(payload)
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(package_skill.package_skill(skill, root / "out"))
                archive = package_skill.package_skill(
                    skill, root / "out", reviewed_hidden=("assets/.template",),
                )
            self.assertIsNotNone(archive)
            with zipfile.ZipFile(archive) as result:
                self.assertEqual(result.read("hidden-template/assets/.template"), payload)

    def test_packaging_refuses_malformed_agnix_output_and_preserves_old_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(root, "safe", "name: safe\ndescription: Use when preparing a document.")
            out = root / "out"
            out.mkdir()
            archive = out / "safe.skill"
            archive.write_bytes(b"existing archive")
            result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr="")
            with mock.patch.object(package_skill.subprocess, "run", return_value=result), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(package_skill.package_skill(skill, out))
            self.assertEqual(archive.read_bytes(), b"existing archive")

    def test_packaging_reports_missing_uvx_without_replacing_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(root, "safe", "name: safe\ndescription: Use when preparing a document.")
            out = root / "out"
            out.mkdir()
            archive = out / "safe.skill"
            archive.write_bytes(b"existing archive")
            errors = io.StringIO()
            with mock.patch.object(package_skill.subprocess, "run", side_effect=FileNotFoundError("uvx")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertIsNone(package_skill.package_skill(skill, out))
            self.assertIn("agnix validation could not run", errors.getvalue())
            self.assertEqual(archive.read_bytes(), b"existing archive")

    def test_packager_passes_claude_target_to_agnix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "task-brief",
                "name: task-brief\ndescription: Use when summarizing a task.\ncontext: fork",
            )
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()) as run, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out", target="claude-code")
            self.assertIsNotNone(archive)
            self.assertIn("--target", run.call_args.args[0])
            self.assertIn("claude-code", run.call_args.args[0])

    def test_packager_requires_explicit_target_for_client_extensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "task-brief",
                "name: task-brief\ndescription: Use when summarizing a task.\n"
                "user-invocable: false",
            )
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result()) as run, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(package_skill.package_skill(skill, root / "out"))
                self.assertFalse(run.called)
                archive = package_skill.package_skill(skill, root / "out", target="copilot")
            self.assertIsNotNone(archive)

    def test_codex_sidecar_must_be_checked_and_packaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root, "task-brief",
                "name: task-brief\ndescription: Use when summarizing a task.",
            )
            (skill / "agents").mkdir()
            (skill / "agents" / "openai.yaml").write_text(
                "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8",
            )
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result(checked=1)), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertIsNone(package_skill.package_skill(skill, root / "out", target="codex"))
            with mock.patch.object(package_skill.subprocess, "run", return_value=self.agnix_result(checked=2)) as run, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out", target="codex")
            self.assertIsNotNone(archive)
            self.assertIn(str(skill / "agents" / "openai.yaml"), run.call_args.args[0])
            with zipfile.ZipFile(archive) as result:
                self.assertIn("task-brief/agents/openai.yaml", result.namelist())

    @unittest.skipUnless(shutil.which("uvx"), "uvx is unavailable")
    def test_real_agnix_rejects_invalid_codex_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = make_skill(
                root / ".agents" / "skills", "task-brief",
                "name: task-brief\ndescription: Use when summarizing a task.",
            )
            (skill / "agents").mkdir()
            sidecar = skill / "agents" / "openai.yaml"
            sidecar.write_text(
                "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                archive = package_skill.package_skill(skill, root / "out", target="codex")
            self.assertIsNotNone(archive)
            original = archive.read_bytes()
            sidecar.write_text(
                "policy:\n  allow_implicit_invocation: maybe\n", encoding="utf-8",
            )
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertIsNone(package_skill.package_skill(skill, root / "out", target="codex"))
            self.assertIn("allow_implicit_invocation", errors.getvalue())
            self.assertEqual(archive.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

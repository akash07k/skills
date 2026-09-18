"""Entry-point checks shared by every skill-creator script."""

import subprocess
import sys
import tempfile
import unittest

from skill_path import SKILL

SCRIPTS = [
    "aggregate_benchmark", "generate_report", "generate_review", "improve_description",
    "package_skill", "prepare_eval_review", "quick_validate", "run_eval", "run_loop",
]


class ScriptEntryTests(unittest.TestCase):
    def test_scripts_run_by_path_from_any_directory(self):
        with tempfile.TemporaryDirectory() as cwd:
            for name in SCRIPTS:
                with self.subTest(script=name):
                    result = subprocess.run(
                        [sys.executable, str(SKILL / "scripts" / f"{name}.py"), "--help"],
                        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("usage:", result.stdout)

    def test_scripts_declare_and_enforce_python_313(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                text = (SKILL / "scripts" / f"{name}.py").read_text(encoding="utf-8")
                self.assertIn('# /// script\n# requires-python = ">=3.13"\n', text)
                guard = text.index("if sys.version_info < (3, 13):")
                self.assertLess(guard, text.index("from scripts."))


if __name__ == "__main__":
    unittest.main()

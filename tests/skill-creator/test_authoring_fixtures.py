"""Check teaching inputs and executable examples, not model compliance."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skill_path import SKILL


FIXTURES = SKILL / "evals" / "files" / "service-report"
EXPECTED_REPORT = {
    "incident_id": "svc-17",
    "affected_users": 12,
    "evidence": ["monitor export"],
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class AuthoringFixtureTests(unittest.TestCase):
    def test_task_ids_and_input_paths_are_valid(self):
        suite = read_json(SKILL / "evals" / "evals.json")
        self.assertEqual(suite["skill_name"], "skill-creator")
        ids = [case["id"] for case in suite["evals"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(range(1, 11)).issubset(ids))
        for case in suite["evals"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["prompt"].strip())
                self.assertTrue(case["expected_output"].strip())
                self.assertTrue(case["assertions"])
                for assertion in case["assertions"]:
                    self.assertIsInstance(assertion, str)
                    self.assertTrue(assertion.strip())
                for name in case.get("files", []):
                    self.assertTrue((SKILL / name).is_file(), name)

    def test_known_facts_and_valid_report_agree_with_independent_values(self):
        facts = read_json(FIXTURES / "facts.json")
        self.assertEqual(facts["fixture_kind"], "illustrative")
        self.assertEqual(facts["incident_id"], "svc-17")
        self.assertEqual(facts["affected_users"], 12)
        self.assertEqual(facts["source"], "monitor export")
        self.assertEqual(read_json(FIXTURES / "report-b.json"), EXPECTED_REPORT)

    def test_reference_checker_rejects_seeded_defects(self):
        reference = (SKILL / "references" / "worked-example.md").read_text(encoding="utf-8")
        match = re.search(r"```python\n(def report_errors\(report\):.*?)\n```", reference, re.S)
        self.assertIsNotNone(match, "The executable checker example is missing.")
        namespace = {}
        exec(compile(match.group(1), "worked-example.md", "exec"), namespace)
        checker = namespace["report_errors"]
        self.assertEqual(checker(dict(EXPECTED_REPORT)), [])
        self.assertEqual(checker(read_json(FIXTURES / "report-extra-evidence.json")), [])
        self.assertTrue(any("affected_users" in error for error in checker(
            read_json(FIXTURES / "report-a.json")
        )))
        self.assertTrue(any("evidence" in error for error in checker(
            read_json(FIXTURES / "report-no-evidence.json")
        )))
        for value in (True, "12", 13):
            with self.subTest(value=value):
                self.assertTrue(checker({**EXPECTED_REPORT, "affected_users": value}))
        self.assertTrue(checker([]))
        self.assertTrue(checker({**EXPECTED_REPORT, "evidence": ["invented source"]}))
        self.assertTrue(any("evidence" in error for error in checker(
            read_json(FIXTURES / "report-unsupported-evidence.json")
        )))
        for value in ("monitor export", [], None, [None]):
            with self.subTest(evidence=value):
                self.assertTrue(checker({**EXPECTED_REPORT, "evidence": value}))

    def test_future_cases_and_benchmark_examples_are_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(SKILL / "evals", root / "evals")
            shutil.copytree(SKILL / "references", root / "references")
            shutil.copyfile(SKILL / "SKILL.md", root / "SKILL.md")
            path = root / "evals" / "evals.json"
            suite = read_json(path)
            suite["evals"].append({
                "id": 13, "prompt": "A later task", "expected_output": "A result",
                "files": [], "assertions": ["The result is correct."],
            })
            path.write_text(json.dumps(suite), encoding="utf-8")
            schema = (root / "references" / "schemas.md").read_text(encoding="utf-8")
            blocks = re.findall(r"```json\n(.*?)\n```", schema, re.S)
            benchmark = next(block for block in blocks if '"run_summary"' in block)
            (root / "references" / "future.md").write_text(
                f"```json\n{benchmark}\n```\n", encoding="utf-8",
            )
            with mock.patch(f"{__name__}.SKILL", root):
                for name in (
                    "test_task_ids_and_input_paths_are_valid",
                    "test_document_json_examples_parse_and_run_counts_agree",
                ):
                    with self.subTest(test=name):
                        result = unittest.TestResult()
                        self.__class__(name).run(result)
                        self.assertEqual(result.errors, [])
                        self.assertEqual(result.failures, [])

    def test_complete_skill_example_passes_the_real_validator(self):
        reference = (SKILL / "references" / "worked-example.md").read_text(encoding="utf-8")
        match = re.search(r"```markdown\n(---\n.*?)\n```", reference, re.S)
        self.assertIsNotNone(match, "The complete skill example is missing.")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "service-report"
            path.mkdir()
            (path / "SKILL.md").write_text(match.group(1) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SKILL / "scripts" / "quick_validate.py"), str(path), "--json"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["valid"])
            self.assertEqual(report["warnings"], [])

    def test_empty_artifact_fails_parsing_not_file_access(self):
        path = FIXTURES / "empty.txt"
        self.assertTrue(path.is_file())
        content = path.read_text(encoding="utf-8")
        self.assertEqual(content.strip(), "")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(content)

    def test_matched_success_records_have_five_complete_runs_per_side(self):
        data = read_json(FIXTURES / "matched-successes.json")
        self.assertEqual(data["fixture_kind"], "illustrative")
        self.assertEqual(len(data["runs"]), 10)
        for configuration in ("baseline", "candidate"):
            runs = [row for row in data["runs"] if row["configuration"] == configuration]
            self.assertEqual(sorted(row["run_number"] for row in runs), [1, 2, 3, 4, 5])
            for row in runs:
                self.assertEqual(row["passed"], 3)
                self.assertEqual(row["failed"], 0)
                self.assertEqual(row["total"], len(data["assertions"]))
                self.assertEqual(row["passed"] + row["failed"], row["total"])
                self.assertNotIn("time_seconds", row)

    def test_clean_control_contains_fifteen_factually_correct_samples(self):
        data = read_json(FIXTURES / "clean-control.json")
        self.assertEqual(data["fixture_kind"], "illustrative")
        facts = read_json(FIXTURES / "facts.json")
        self.assertEqual(data["input"], {key: facts[key] for key in (
            "incident_id", "service", "affected_users", "source",
        )})
        reference = (SKILL / "references" / "worked-example.md").read_text(encoding="utf-8")
        shared_task = re.search(r"Task: (.*?)\nVariant instruction:", reference, re.S)
        self.assertIsNotNone(shared_task)
        self.assertEqual(re.sub(r"\s+", " ", shared_task.group(1)), data["task"])
        self.assertEqual([variant["name"] for variant in data["variants"]],
                         ["control", "prohibition", "recipe"])
        self.assertEqual(data["variants"][0]["instruction"], "")
        for variant in data["variants"][1:]:
            for field in ("incident_id", "affected_users", "evidence"):
                self.assertIn(field, variant["instruction"])
        for variant in data["variants"]:
            self.assertEqual(len(variant["samples"]), 5)
            for sample in variant["samples"]:
                self.assertEqual(sample, EXPECTED_REPORT)

    def test_comparison_case_has_a_complete_absent_output_inventory(self):
        manifest = read_json(FIXTURES / "verified-absent-run.json")
        self.assertEqual(manifest["fixture_kind"], "illustrative")
        self.assertIs(manifest["run_completed"], True)
        self.assertIs(manifest["output_inventory_complete"], True)
        self.assertEqual(manifest["expected_output"], "report.json")
        self.assertNotIn(manifest["expected_output"], manifest["output_files"])
        cases = read_json(SKILL / "evals" / "evals.json")["evals"]
        case = next(case for case in cases if case["id"] == 4)
        self.assertIn("evals/files/service-report/verified-absent-run.json", case["files"])

    def test_confirmation_cases_and_inputs_are_separate_and_consistent(self):
        regression = read_json(SKILL / "evals" / "evals.json")
        confirmation = read_json(SKILL / "evals" / "confirmation.json")
        self.assertEqual(confirmation["skill_name"], regression["skill_name"])
        ids = [case["id"] for case in confirmation["evals"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({11, 12}.issubset(ids))
        self.assertTrue(set(ids).isdisjoint(case["id"] for case in regression["evals"]))
        for case in confirmation["evals"]:
            self.assertTrue(case["prompt"].strip())
            self.assertTrue(case["expected_output"].strip())
            self.assertTrue(case["assertions"])
            for name in case["files"]:
                self.assertTrue((SKILL / name).is_file(), name)
        teaching = (SKILL / "references" / "worked-example.md").read_text(encoding="utf-8")
        self.assertNotIn("inventory-reconciliation", teaching)

        results = read_json(SKILL / "evals" / "files" / "inventory-confirmation" / "matched-results.json")
        self.assertEqual(results["fixture_kind"], "illustrative")
        self.assertEqual(len(results["runs"]), 6)
        for configuration in ("baseline", "candidate"):
            runs = [row for row in results["runs"] if row["configuration"] == configuration]
            self.assertEqual(sorted(row["run_number"] for row in runs), [1, 2, 3])
            for row in runs:
                self.assertEqual(row["passed"], len(results["checks"]))
                self.assertEqual(row["failed"], 0)
                self.assertEqual(row["total"], len(results["checks"]))
                self.assertNotIn("time_seconds", row)

    def test_document_json_examples_parse_and_run_counts_agree(self):
        paths = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
        benchmark_examples = 0
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for index, block in enumerate(re.findall(r"```json\n(.*?)\n```", text, re.S)):
                with self.subTest(path=path.name, block=index):
                    data = json.loads(block)
                    if not isinstance(data, dict) or "runs" not in data or "run_summary" not in data:
                        continue
                    benchmark_examples += 1
                    for run in data["runs"]:
                        result = run["result"]
                        assertions = run["assertion_results"]
                        passed = sum(row["passed"] for row in assertions)
                        self.assertEqual(passed, result["passed"])
                        self.assertEqual(len(assertions), result["total"])
                        self.assertEqual(len(assertions) - passed, result["failed"])
                        self.assertAlmostEqual(passed / len(assertions), result["pass_rate"], places=7)
        self.assertGreaterEqual(benchmark_examples, 1)


if __name__ == "__main__":
    unittest.main()

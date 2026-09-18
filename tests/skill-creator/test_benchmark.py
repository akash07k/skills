import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skill_path import SKILL  # noqa: F401
from scripts import aggregate_benchmark as aggregate


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def grading(pass_rate=1.0, field="assertion_results", timing=None):
    """Consistent grading: the first assertion always passes, ten assertions in total."""
    passed = max(1, round(pass_rate * 10))
    results = [{"text": "Has | pipe", "passed": True, "evidence": "Seen"}] + [
        {"text": f"Check {index}", "passed": index < passed, "evidence": "Seen"}
        for index in range(1, 10)
    ]
    data = {
        "summary": {"passed": passed, "failed": 10 - passed, "total": 10, "pass_rate": passed / 10},
        field: results,
    }
    if timing is not None:
        data["timing"] = timing
    return data


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def run_main(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["aggregate_benchmark", str(self.root), *extra]), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                aggregate.main()
                code = 0
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_timing_json_takes_precedence_over_grading_total(self):
        cases = [
            ({"total_duration_seconds": 3.0, "duration_ms": 9000}, 3.0),
            ({"duration_ms": 23332}, 23.332),
            ({"executor_duration_seconds": 7.0}, 7.0),
            (None, 5.0),
        ]
        for index, (timing_file, expected) in enumerate(cases):
            run = self.root / f"eval-{index}" / "with_skill" / "run-1"
            write_json(run / "grading.json", grading(timing={
                "executor_duration_seconds": 5.0, "total_duration_seconds": 99.0,
            }))
            if timing_file is not None:
                write_json(run / "timing.json", timing_file)
        results = aggregate.load_run_results(self.root)["with_skill"]
        times = {result["eval_id"]: result["time_seconds"] for result in results}
        self.assertEqual(times, {index: expected for index, (_, expected) in enumerate(cases)})

    def test_json_files_with_utf8_bom_are_read(self):
        run = self.root / "eval-1" / "with_skill" / "run-1"
        run.mkdir(parents=True)
        (run / "grading.json").write_text(json.dumps(grading(0.5)), encoding="utf-8-sig")
        (run / "timing.json").write_text(json.dumps({"duration_ms": 4000}), encoding="utf-8-sig")
        result = aggregate.load_run_results(self.root)["with_skill"][0]
        self.assertEqual((result["pass_rate"], result["time_seconds"]), (0.5, 4.0))

    def test_grading_total_is_last_fallback(self):
        run = self.root / "eval-1" / "with_skill" / "run-1"
        write_json(run / "grading.json", grading(timing={"total_duration_seconds": 12.0}))
        self.assertEqual(aggregate.load_run_results(self.root)["with_skill"][0]["time_seconds"], 12.0)

    def test_delta_values_are_numbers_and_markdown_formats_them(self):
        for config, rate, seconds, tokens in (("with_skill", 0.9, 10.0, 300), ("without_skill", 0.4, 4.0, 100)):
            run = self.root / "eval-1" / config / "run-1"
            write_json(run / "grading.json", grading(rate))
            write_json(run / "timing.json", {"total_duration_seconds": seconds, "total_tokens": tokens})
        benchmark = aggregate.generate_benchmark(self.root, "demo")
        delta = benchmark["run_summary"]["delta"]
        for key in ("pass_rate", "time_seconds", "tokens"):
            self.assertIsInstance(delta[key], float)
        self.assertAlmostEqual(delta["pass_rate"], 0.5)
        self.assertAlmostEqual(delta["time_seconds"], 6.0)
        self.assertAlmostEqual(delta["tokens"], 200)
        markdown = aggregate.generate_markdown(benchmark)
        self.assertIn("| +50% |", markdown)
        self.assertIn("| +6.0s |", markdown)
        self.assertIn("| +200 |", markdown)

    def test_legacy_string_deltas_still_render(self):
        self.assertEqual(aggregate.format_delta("+50%", "%", 0, percent=True), "+50%")
        self.assertEqual(aggregate.format_delta("+13.0", "s", 1), "+13.0s")
        self.assertEqual(aggregate.format_delta(-0.0001, "%", 0, percent=True), "+0%")
        self.assertEqual(aggregate.format_delta(None), "Not available")

    def test_writes_assertion_results_and_reads_legacy_expectations(self):
        write_json(self.root / "eval-1" / "with_skill" / "run-1" / "grading.json", grading())
        write_json(
            self.root / "eval-1" / "without_skill" / "run-1" / "grading.json",
            grading(0.0, field="expectations"),
        )
        benchmark = aggregate.generate_benchmark(self.root, "demo")
        for run in benchmark["runs"]:
            self.assertNotIn("expectations", run)
            self.assertEqual(len(run["assertion_results"]), 10)
            self.assertEqual(
                run["assertion_results"][0],
                {"text": "Has | pipe", "passed": True, "evidence": "Seen"},
            )

    def test_spec_layout_uses_implicit_run_and_any_eval_name_with_metadata(self):
        for config in ("with_skill", "without_skill"):
            base = self.root / "top-months-chart" / config
            (base / "outputs").mkdir(parents=True)
            write_json(base / "grading.json", grading())
            write_json(base / "timing.json", {"total_tokens": 10, "duration_ms": 1500})
        write_json(self.root / "top-months-chart" / "eval_metadata.json", {
            "eval_name": "top-months-chart", "prompt": "p", "assertions": ["Has | pipe"],
        })
        write_json(self.root / "eval-clean-emails" / "with_skill" / "grading.json", grading())
        (self.root / "not-an-eval" / "with_skill" / "outputs").mkdir(parents=True)
        results = aggregate.load_run_results(self.root)
        self.assertEqual(len(results["with_skill"]), 2)
        self.assertEqual(len(results["without_skill"]), 1)
        rows = {row["eval_id"]: row for row in results["with_skill"]}
        self.assertEqual(set(rows), {"top-months-chart", "eval-clean-emails"})
        self.assertEqual(rows["top-months-chart"]["run_number"], 1)
        self.assertEqual(rows["top-months-chart"]["time_seconds"], 1.5)
        self.assertEqual(rows["top-months-chart"]["tokens"], 10)

    def test_numbered_runs_take_precedence_over_implicit_run(self):
        base = self.root / "eval-1" / "with_skill"
        write_json(base / "grading.json", grading(0.0))
        write_json(base / "run-1" / "grading.json", grading(1.0))
        write_json(base / "run-2" / "grading.json", grading(1.0))
        rows = aggregate.load_run_results(self.root)["with_skill"]
        self.assertEqual([row["run_number"] for row in rows], [1, 2])
        self.assertEqual({row["pass_rate"] for row in rows}, {1.0})

    def test_no_evals_or_runs_exit_nonzero_with_stderr(self):
        code, stdout, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("No eval directories", stderr)
        self.assertIn("no graded runs", stderr)
        self.assertNotIn("Generated", stdout)
        self.assertFalse((self.root / "benchmark.json").exists())

        (self.root / "eval-1" / "with_skill" / "run-1").mkdir(parents=True)
        code, _, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("grading.json not found", stderr)

        missing = self.root / "missing"
        with patch.object(sys, "argv", ["aggregate_benchmark", str(missing)]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr, \
             self.assertRaises(SystemExit) as raised:
            aggregate.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("directory not found", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_successful_cli_writes_outputs(self):
        write_json(self.root / "eval-1" / "with_skill" / "grading.json", grading())
        code, stdout, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Generated", stdout)
        self.assertTrue((self.root / "benchmark.json").exists())

    def test_markdown_table_cells_are_escaped(self):
        write_json(self.root / "eval-1" / "with_skill" / "run-1" / "grading.json", grading())
        write_json(self.root / "eval-1" / "without_skill" / "run-1" / "grading.json", grading(0.5))
        benchmark = aggregate.generate_benchmark(self.root, "demo")
        summary = benchmark["run_summary"]
        benchmark["run_summary"] = {
            "with|skill": summary["with_skill"],
            "without_skill": summary["without_skill"],
            "delta": {**summary["delta"], "pass_rate": "+1|\nx"},
        }
        benchmark["metadata"]["runs_per_configuration"] = 1
        markdown = aggregate.generate_markdown(benchmark)
        self.assertIn("With\\|Skill", markdown)
        self.assertIn("+1\\| x", markdown)
        table = [line for line in markdown.splitlines() if line.startswith("|")]
        self.assertTrue(all(line.endswith("|") for line in table))
        self.assertEqual(aggregate.md_cell("a|b\r\nc"), "a\\|b c")

    def test_delta_config_name_is_reserved(self):
        write_json(self.root / "eval-1" / "delta" / "run-1" / "grading.json", grading())
        with self.assertRaisesRegex(ValueError, "reserved"):
            aggregate.load_run_results(self.root)
        code, _, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("reserved", stderr)

    def test_missing_summary_is_computed_from_assertions(self):
        for field in ("assertion_results", "expectations"):
            data = grading(0.3, field=field)
            del data["summary"]
            write_json(self.root / f"eval-{field}" / "with_skill" / "grading.json", data)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            benchmark = aggregate.generate_benchmark(self.root, "demo")
        self.assertEqual(len(benchmark["runs"]), 2)
        for run in benchmark["runs"]:
            self.assertEqual(
                run["result"],
                {"pass_rate": 0.3, "passed": 3, "failed": 7, "total": 10},
            )
        self.assertIn("has no usable summary; computed it from the assertion results", stderr.getvalue())
        self.assertEqual(benchmark["skipped_runs"], [])
        self.assertNotIn("Skipped runs", aggregate.generate_markdown(benchmark))

    def test_disagreeing_summary_is_replaced_with_a_warning(self):
        data = grading(0.3)
        data["summary"] = {"passed": 9, "failed": 1, "total": 10, "pass_rate": 0.9}
        write_json(self.root / "eval-1" / "with_skill" / "run-2" / "grading.json", data)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            benchmark = aggregate.generate_benchmark(self.root, "demo")
        self.assertEqual(benchmark["runs"][0]["result"]["pass_rate"], 0.3)
        self.assertEqual(benchmark["runs"][0]["result"]["passed"], 3)
        message = stderr.getvalue()
        self.assertIn("eval 1 with_skill run 2", message)
        self.assertIn("disagrees with its assertion results", message)
        self.assertIn("using the values computed from the assertion results", message)

    def test_rounded_summary_pass_rate_is_not_a_disagreement(self):
        data = {
            "summary": {"passed": 2, "failed": 1, "total": 3, "pass_rate": 0.67},
            "assertion_results": [
                {"text": f"Check {index}", "passed": index < 2, "evidence": "Seen"}
                for index in range(3)
            ],
        }
        write_json(self.root / "eval-1" / "with_skill" / "grading.json", data)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            benchmark = aggregate.generate_benchmark(self.root, "demo")
        self.assertEqual(benchmark["runs"][0]["result"]["pass_rate"], 0.6667)
        self.assertNotIn("disagrees", stderr.getvalue())

    def test_summary_is_kept_when_assertions_are_malformed(self):
        data = grading(0.5)
        data["assertion_results"][1] = {"text": "No verdict"}
        write_json(self.root / "eval-1" / "with_skill" / "grading.json", data)
        with contextlib.redirect_stderr(io.StringIO()):
            benchmark = aggregate.generate_benchmark(self.root, "demo")
        self.assertEqual(benchmark["runs"][0]["result"]["pass_rate"], 0.5)

    def test_unusable_runs_are_listed_in_json_and_markdown(self):
        write_json(self.root / "eval-1" / "with_skill" / "grading.json", grading())
        write_json(self.root / "eval-1" / "without_skill" / "grading.json", {"assertion_results": []})
        write_json(self.root / "eval-2" / "with_skill" / "run-1" / "grading.json", {"summary": {"passed": 1}})
        (self.root / "eval-2" / "with_skill" / "run-2").mkdir(parents=True)
        (self.root / "eval-2" / "with_skill" / "run-3").mkdir(parents=True)
        (self.root / "eval-2" / "with_skill" / "run-3" / "grading.json").write_text("{", encoding="utf-8")
        code, stdout, stderr = self.run_main()
        self.assertEqual(code, 0)
        benchmark = json.loads((self.root / "benchmark.json").read_text(encoding="utf-8"))
        skipped = benchmark["skipped_runs"]
        self.assertEqual(
            [(run["eval_id"], run["configuration"], run["run_number"], run["path"]) for run in skipped],
            [
                (1, "without_skill", 1, "eval-1/without_skill"),
                (2, "with_skill", 1, "eval-2/with_skill/run-1"),
                (2, "with_skill", 2, "eval-2/with_skill/run-2"),
                (2, "with_skill", 3, "eval-2/with_skill/run-3"),
            ],
        )
        self.assertEqual(skipped[0]["reason"], "no usable summary and no valid assertion results")
        self.assertEqual(skipped[2]["reason"], "grading.json not found")
        self.assertTrue(skipped[3]["reason"].startswith("invalid grading.json"))
        self.assertIn("Skipping eval 1 without_skill run 1", stderr)
        self.assertIn("Skipped runs:  4", stdout)
        markdown = (self.root / "benchmark.md").read_text(encoding="utf-8")
        self.assertIn("## Skipped runs", markdown)
        self.assertIn(
            "- Eval 1, without_skill, run 1 (`eval-1/without_skill`): "
            "no usable summary and no valid assertion results",
            markdown,
        )

    def test_skill_path_is_omitted_unless_given(self):
        write_json(self.root / "eval-1" / "with_skill" / "grading.json", grading())
        self.assertNotIn("skill_path", aggregate.generate_benchmark(self.root, "demo")["metadata"])
        benchmark = aggregate.generate_benchmark(self.root, "demo", skill_path=r"C:\skills\demo")
        self.assertEqual(benchmark["metadata"]["skill_path"], r"C:\skills\demo")


if __name__ == "__main__":
    unittest.main()

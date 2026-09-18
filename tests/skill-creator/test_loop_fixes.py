"""Regressions for process cleanup, strict thresholds, and run_loop/report CLI output."""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest import mock
from unittest.mock import Mock, patch

from skill_path import SKILL  # noqa: F401  (adds the skill to sys.path)
from scripts import copilot_cli, generate_report, improve_description, run_eval, run_loop


def _alive_windows(pid: int) -> bool:
    output = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        capture_output=True, text=True,
    ).stdout
    return f'"{pid}"' in output


class KillProcessTreeTests(unittest.TestCase):
    def test_windows_uses_taskkill_for_the_whole_tree(self):
        process = Mock(pid=4321)
        process.poll.side_effect = [None, 0]
        killer = Mock()
        with patch.object(copilot_cli.os, "name", "nt"), \
             patch.object(copilot_cli, "_POPEN", return_value=killer) as popen:
            copilot_cli.kill_process_tree(process)
        self.assertEqual(popen.call_args.args[0], ["taskkill", "/T", "/F", "/PID", "4321"])
        killer.wait.assert_called_once()
        process.kill.assert_not_called()

    def test_windows_falls_back_to_direct_kill_when_taskkill_fails(self):
        process = Mock(pid=4321)
        process.poll.return_value = None
        with patch.object(copilot_cli.os, "name", "nt"), \
             patch.object(copilot_cli, "_POPEN", side_effect=OSError("no taskkill")):
            copilot_cli.kill_process_tree(process)
        process.kill.assert_called_once()

    def test_windows_skips_finished_processes(self):
        process = Mock(pid=4321)
        process.poll.return_value = 0
        with patch.object(copilot_cli.os, "name", "nt"), \
             patch.object(copilot_cli, "_POPEN") as popen:
            copilot_cli.kill_process_tree(process)
        popen.assert_not_called()
        process.kill.assert_not_called()

    @patch.object(copilot_cli.signal, "SIGKILL", 9, create=True)
    def test_posix_kills_the_process_group_only_when_it_owns_it(self):
        process = Mock(pid=77)
        process.poll.return_value = 0
        with patch.object(copilot_cli.os, "name", "posix"), \
             patch.object(copilot_cli.os, "getpgid", create=True, return_value=77), \
             patch.object(copilot_cli.os, "getpgrp", create=True, return_value=1), \
             patch.object(copilot_cli.os, "killpg", create=True) as killpg:
            copilot_cli.kill_process_tree(process)
        killpg.assert_called_once_with(77, 9)
        with patch.object(copilot_cli.os, "name", "posix"), \
             patch.object(copilot_cli.os, "getpgid", create=True, return_value=1), \
             patch.object(copilot_cli.os, "getpgrp", create=True, return_value=1), \
             patch.object(copilot_cli.os, "killpg", create=True) as killpg:
            copilot_cli.kill_process_tree(process)
        killpg.assert_not_called()

    def test_popen_options_start_a_new_session_on_posix(self):
        with patch.object(copilot_cli.os, "name", "posix"):
            self.assertEqual(copilot_cli.process_group_kwargs(), {"start_new_session": True})
        with patch.object(copilot_cli.os, "name", "nt"):
            self.assertEqual(copilot_cli.process_group_kwargs(), {})

    @unittest.skipUnless(sys.platform == "win32", "taskkill tree behavior")
    def test_real_grandchild_is_killed_on_windows(self):
        grandchild = "import time; time.sleep(60)"
        parent = (
            "import subprocess, sys, time\n"
            f"child = subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", parent], stdout=subprocess.PIPE, text=True,
            **copilot_cli.process_group_kwargs(),
        )
        try:
            grandchild_pid = int(process.stdout.readline())
            self.assertTrue(_alive_windows(grandchild_pid))
            copilot_cli.kill_process_tree(process)
            process.wait(timeout=10)
            deadline = time.monotonic() + 5
            while _alive_windows(grandchild_pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(_alive_windows(grandchild_pid))
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()


class InterruptCleanupTests(unittest.TestCase):
    def setUp(self):
        resolver = patch("scripts.copilot_cli.shutil.which", return_value="copilot")
        resolver.start()
        self.addCleanup(resolver.stop)

    def test_keyboard_interrupt_kills_tree_and_removes_candidate(self):
        roots = []

        def launch(cmd, **kwargs):
            roots.append(Path(cmd[cmd.index("--add-dir") + 1]))
            return Mock()

        with patch.object(run_eval.subprocess, "Popen", side_effect=launch), \
             patch.object(run_eval, "_await_decision", side_effect=KeyboardInterrupt), \
             patch.object(run_eval, "kill_process_tree") as kill:
            with self.assertRaises(KeyboardInterrupt):
                run_eval.run_single_query("query", "demo", "description", 5)
        kill.assert_called_once()
        self.assertFalse(roots[0].exists())

    def test_eval_interrupt_cancels_workers_and_waits_for_cleanup(self):
        executor = Mock()
        executor.submit.return_value = Future()
        with patch.object(run_eval, "ThreadPoolExecutor", return_value=executor), \
             patch.object(run_eval, "copilot_version", return_value="v"), \
             patch.object(run_eval, "as_completed", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run_eval.run_eval([{"query": "q", "should_trigger": True}], "demo", "d", 1, 1)
        cancelled = executor.submit.call_args.args[6]
        self.assertTrue(cancelled.is_set())
        executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    def test_improver_kills_tree_on_interrupt_and_timeout(self):
        for error in (KeyboardInterrupt(), subprocess.TimeoutExpired("copilot", 1)):
            with self.subTest(error=type(error).__name__):
                process = Mock()
                process.communicate.side_effect = [error, ("", "")]
                with patch.object(improve_description.subprocess, "Popen", return_value=process), \
                     patch.object(improve_description, "kill_process_tree") as kill:
                    with self.assertRaises(type(error)):
                        improve_description._call_copilot("prompt", None, timeout=1)
                kill.assert_called_once_with(process)
                self.assertEqual(process.communicate.call_count, 2)


class StrictThresholdTests(unittest.TestCase):
    def evaluate(self, eval_set, outcomes, **options):
        futures = []
        for outcome in outcomes:
            future = Future()
            future.set_result(outcome)
            futures.append(future)
        with patch.object(run_eval, "ThreadPoolExecutor") as executor, \
             patch.object(run_eval, "copilot_version", return_value="v"), \
             patch.object(run_eval, "as_completed", side_effect=lambda _: list(futures)):
            executor.return_value.submit.side_effect = futures
            return run_eval.run_eval(eval_set, "demo", "d", 1, 1, **options)

    def test_rate_equal_to_threshold_fails_in_both_directions(self):
        entries = [
            {"query": "positive", "should_trigger": True},
            {"query": "negative", "should_trigger": False},
        ]
        result = self.evaluate(entries, [True, False, True, False], runs_per_query=2)
        self.assertEqual([row["trigger_rate"] for row in result["results"]], [0.5, 0.5])
        self.assertEqual([row["pass"] for row in result["results"]], [False, False])

    def test_rates_strictly_above_or_below_pass(self):
        entries = [
            {"query": "positive", "should_trigger": True},
            {"query": "negative", "should_trigger": False},
        ]
        result = self.evaluate(entries, [True, True, False, True], runs_per_query=2, trigger_threshold=0.4)
        self.assertEqual([row["pass"] for row in result["results"]], [True, False])
        result = self.evaluate(entries, [True, True, False, False], runs_per_query=2)
        self.assertEqual([row["pass"] for row in result["results"]], [True, True])

    def test_thresholds_that_make_a_label_impossible_are_rejected(self):
        for threshold in (0, 1):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                run_eval.run_eval([{"query": "q", "should_trigger": True}], "demo", "d", 1, 1,
                                  trigger_threshold=threshold)


class DescriptionLengthTests(unittest.TestCase):
    scores = {"results": [], "summary": {"passed": 0, "total": 0}}

    def test_prompt_targets_150_words_and_rejects_rather_than_truncates(self):
        with patch.object(improve_description, "_call_copilot",
                          return_value="<new_description>Fine.</new_description>") as call:
            improve_description.improve_description("demo", "content", "old", self.scores, [], None)
        prompt = call.call_args.args[0]
        self.assertIn("about 150 words", prompt)
        self.assertIn("MUST be under 1024 characters", prompt)
        self.assertNotIn("will be truncated", prompt)
        self.assertNotIn("100-200 words", prompt)

    def test_over_length_description_is_retried_then_rejected_not_truncated(self):
        too_long = "<new_description>" + "word " * 300 + "</new_description>"
        with patch.object(improve_description, "_call_copilot", side_effect=[too_long, too_long]) as call:
            with self.assertRaisesRegex(RuntimeError, "exceeds 1024.*refusing to truncate"):
                improve_description.improve_description("demo", "content", "old", self.scores, [], None)
        self.assertEqual(call.call_count, 2)
        self.assertIn("under 1024 characters", call.call_args_list[1].args[0])


class LoopCliFixture:
    OUTPUT = {
        "exit_reason": "all_passed (iteration 1)",
        "best_description": "Best.",
        "best_score": "1/1",
        "iterations_run": 1,
        "history": [{"iteration": 1, "description": "Best."}],
    }

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
        )
        self.eval_set = self.root / "evals.json"
        self.eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")

    def main(self, *options, output=None, side_effect=None):
        argv = [
            "run_loop", "--eval-set", str(self.eval_set), "--skill-path", str(self.skill),
            "--holdout", "0", "--results-dir", str(self.root / "results"), *options,
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch.object(sys, "argv", argv), \
             patch.object(run_loop, "run_loop", return_value=output or self.OUTPUT, side_effect=side_effect), \
             patch.object(run_loop.webbrowser, "open") as opened, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                run_loop.main()
            except SystemExit as exit:
                code = exit.code
        return code, stdout.getvalue(), stderr.getvalue(), opened

    def run_dir(self):
        return next((self.root / "results").iterdir())


class LoopCliTests(LoopCliFixture, unittest.TestCase):

    def test_eval_set_with_utf8_bom_is_accepted(self):
        # Windows PowerShell 5 writes a BOM with -Encoding utf8.
        self.eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8-sig")
        code, _, stderr, _ = self.main()
        self.assertEqual(code, 0, stderr)

    def test_default_writes_report_in_results_dir_and_never_opens_browser(self):
        code, stdout, stderr, opened = self.main()
        self.assertEqual(code, 0)
        opened.assert_not_called()
        report = self.run_dir() / "report.html"
        self.assertTrue(report.exists())
        self.assertIn(f"Report: {report}", stderr)
        summary = json.loads(stdout)
        self.assertEqual(Path(summary["report_path"]), report)
        self.assertEqual(Path(summary["results_path"]), self.run_dir() / "results.json")

    def test_open_flag_opens_the_report_once(self):
        code, _, _, opened = self.main("--open")
        self.assertEqual(code, 0)
        opened.assert_called_once_with((self.run_dir() / "report.html").resolve().as_uri())

    def test_report_none_writes_no_report(self):
        code, stdout, _, opened = self.main("--report", "none")
        self.assertEqual(code, 0)
        opened.assert_not_called()
        self.assertFalse((self.run_dir() / "report.html").exists())
        self.assertIsNone(json.loads(stdout)["report_path"])

    def test_custom_report_path_is_used_and_copied_to_results_dir(self):
        report = self.root / "custom" / "my-report.html"
        code, stdout, _, _ = self.main("--report", str(report))
        self.assertEqual(code, 0)
        self.assertTrue(report.exists())
        self.assertTrue((self.run_dir() / "report.html").exists())
        self.assertEqual(Path(json.loads(stdout)["report_path"]), report)

    def test_stdout_is_short_summary_unless_full_json(self):
        _, stdout, _, _ = self.main("--report", "none")
        summary = json.loads(stdout)
        self.assertEqual(set(summary), {
            "best_description", "best_score", "exit_reason", "iterations_run",
            "results_path", "report_path", "error",
        })
        self.assertEqual(summary["best_description"], "Best.")
        self.assertIsNone(summary["error"])
        _, stdout, _, _ = self.main("--report", "none", "--full-json")
        self.assertEqual(json.loads(stdout), self.OUTPUT)

    def test_interrupt_saves_partial_results_and_exits_130(self):
        partial = dict(self.OUTPUT, exit_reason=run_loop.INTERRUPTED, error="interrupted by user (Ctrl+C)")
        code, stdout, stderr, _ = self.main(output=partial)
        self.assertEqual(code, 130)
        self.assertEqual(json.loads(stdout)["exit_reason"], "interrupted")
        saved = json.loads((self.run_dir() / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["history"], partial["history"])
        self.assertNotIn("Traceback", stderr)
        code, _, _, _ = self.main(side_effect=KeyboardInterrupt)
        self.assertEqual(code, 130)

    def test_open_without_report_is_a_usage_error(self):
        code, _, _, opened = self.main("--report", "none", "--open")
        self.assertEqual(code, 2)
        opened.assert_not_called()

    def test_run_loop_returns_completed_iterations_on_interrupt(self):
        entries = [{"query": "q", "should_trigger": True}, {"query": "n", "should_trigger": False}]
        rows = [
            {"eval_id": i, "query": item["query"], "should_trigger": item["should_trigger"],
             "trigger_rate": 0.0, "triggers": 0, "runs": 1, "pass": not item["should_trigger"]}
            for i, item in enumerate(entries)
        ]
        with patch.object(run_loop, "parse_skill_md", return_value=("demo", "old", "content")), \
             patch.object(run_loop, "copilot_version", return_value="v"), \
             patch.object(run_loop, "run_eval", side_effect=[{"results": rows}, KeyboardInterrupt]), \
             patch.object(run_loop, "improve_description", return_value="new"):
            result = run_loop.run_loop(entries, Path.cwd(), None, 1, 1, 3, 1, 0.5, 0, None, False)
        self.assertEqual(result["exit_reason"], "interrupted")
        self.assertEqual(result["iterations_run"], 1)
        self.assertIn("interrupted", result["error"])


class NumericArgumentTests(LoopCliFixture, unittest.TestCase):
    INVALID = (
        ("--num-workers", "0"),
        ("--num-workers", "two"),
        ("--timeout", "-5"),
        ("--timeout", "0"),
        ("--runs-per-query", "0"),
        ("--trigger-threshold", "0"),
        ("--trigger-threshold", "1"),
        ("--trigger-threshold", "1.5"),
        ("--trigger-threshold", "nan"),
    )

    def run_eval_main(self, *options):
        argv = [
            "run_eval", "--eval-set", str(self.eval_set), "--skill-path", str(self.skill), *options,
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", argv), \
             patch.object(run_eval, "run_eval") as evaluated, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
             self.assertRaises(SystemExit) as raised:
            run_eval.main()
        evaluated.assert_not_called()
        return raised.exception.code, stderr.getvalue()

    def assert_usage_error(self, code, stderr, flag):
        self.assertEqual(code, 2)
        self.assertIn(f"argument {flag}:", stderr)
        self.assertNotIn("Planned usage", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_run_eval_rejects_invalid_numbers_before_planning(self):
        for flag, value in self.INVALID:
            with self.subTest(flag=flag, value=value):
                code, stderr = self.run_eval_main(flag, value)
                self.assert_usage_error(code, stderr, flag)

    def test_run_loop_rejects_invalid_numbers_before_planning(self):
        cases = self.INVALID + (
            ("--max-iterations", "0"),
            ("--holdout", "1"),
            ("--holdout", "-0.1"),
            ("--holdout", "inf"),
        )
        for flag, value in cases:
            with self.subTest(flag=flag, value=value):
                code, _, stderr, _ = self.main(flag, value)
                self.assert_usage_error(code, stderr, flag)
        self.assertFalse((self.root / "results").exists())

    def test_boundary_values_are_accepted(self):
        code, _, stderr, _ = self.main(
            "--holdout", "0", "--num-workers", "1", "--timeout", "1",
            "--runs-per-query", "1", "--max-iterations", "1", "--trigger-threshold", "0.01",
        )
        self.assertEqual(code, 0)
        self.assertIn("Planned usage", stderr)

    def test_help_shows_defaults_once(self):
        for module in (run_eval, run_loop):
            stdout = io.StringIO()
            with self.subTest(module=module.__name__), \
                 patch.object(sys, "argv", [module.__name__, "--help"]), \
                 patch.dict("os.environ", {"COLUMNS": "200"}), \
                 contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
                module.main()
            self.assertEqual(raised.exception.code, 0)
            text = " ".join(stdout.getvalue().split())
            for default in ("(default: 4)", "(default: 60)", "(default: 3)", "(default: 0.5)"):
                self.assertEqual(text.count(default), 1, default)
            self.assertNotIn("(default: None)", text)
            self.assertNotIn("(default: False)", text)
            self.assertNotIn("(default 0.5)", text)
            self.assertIn(f"usage: python scripts/{module.__name__.split('.')[-1]}.py", text)
        self.assertIn("(default: 5)", text)
        self.assertIn("(default: 0.4)", text)
        self.assertIn("(default: auto)", text)
        self.assertNotIn("'auto' (default)", text)


class DefaultResultsDirTests(LoopCliFixture, unittest.TestCase):
    def test_default_results_dir_is_a_workspace_next_to_the_skill(self):
        argv = [
            "run_loop", "--eval-set", str(self.eval_set), "--skill-path", str(self.skill),
            "--holdout", "0", "--report", "none",
        ]
        with patch.object(sys, "argv", argv), \
             patch.object(run_loop, "run_loop", return_value=self.OUTPUT), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run_loop.main()
        root = self.root / "skill-workspace" / "description-optimization"
        self.assertTrue(next(root.glob("*/results.json")).exists())
        self.assertEqual([p.name for p in self.skill.iterdir()], ["SKILL.md"])

    def test_default_results_root_uses_resolved_skill_directory_name(self):
        relative = Path(self.skill, "..", "skill")
        self.assertEqual(
            run_loop.default_results_root(relative),
            self.root.resolve() / "skill-workspace" / "description-optimization",
        )


class GenerateReportCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.input = self.root / "results.json"
        self.input.write_text(json.dumps({"history": [], "best_score": "0/0"}), encoding="utf-8")

    def main(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch.object(sys, "argv", ["generate_report", *args]), \
             patch.object(generate_report.webbrowser, "open") as opened, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                generate_report.main()
            except SystemExit as exit:
                code = exit.code
        return code, stdout.getvalue(), stderr.getvalue(), opened

    def test_writes_utf8_report_without_opening_browser_by_default(self):
        output = self.root / "out" / "report.html"
        code, _, stderr, opened = self.main(str(self.input), "-o", str(output), "--skill-name", "caf\u00e9")
        self.assertEqual(code, 0)
        self.assertIn("caf\u00e9", output.read_text(encoding="utf-8"))
        self.assertEqual(sorted(path.name for path in output.parent.iterdir()), ["report.html"])
        opened.assert_not_called()
        code, _, _, opened = self.main(str(self.input), "-o", str(output), "--open")
        self.assertEqual(code, 0)
        opened.assert_called_once_with(output.resolve().as_uri())

    def test_expected_errors_are_clean_with_exit_codes(self):
        malformed = self.root / "bad.json"
        malformed.write_text("{", encoding="utf-8")
        not_object = self.root / "list.json"
        not_object.write_text("[]", encoding="utf-8")
        directory = self.root / "a-directory"
        directory.mkdir()
        cases = [
            ((str(self.root / "missing.json"),), 2),
            ((str(malformed),), 2),
            ((str(not_object),), 2),
            ((str(self.input), "-o", str(directory)), 1),
            ((str(self.input), "--open"), 2),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                code, _, stderr, opened = self.main(*args)
                self.assertEqual(code, expected)
                self.assertIn("rror", stderr)
                self.assertNotIn("Traceback", stderr)
                opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()

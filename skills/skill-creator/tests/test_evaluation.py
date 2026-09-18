"""Offline evaluator regressions: python -m unittest discover -s tests -v."""

import contextlib
import copy
import io
import json
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from concurrent.futures import Future
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from scripts import run_eval, run_loop
from scripts import aggregate_benchmark
from scripts.package_skill import package_skill
from scripts.quick_validate import validate_skill
from scripts.utils import atomic_write_text, parse_skill_md


FAKE_COPILOT = r'''
import json
import sys
import time

scenario, name, skill_path = sys.argv[1:]

def emit(event, newline=True):
    data = json.dumps(event, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(data + (b"\n" if newline else b""))
    sys.stdout.buffer.flush()

def delta(part, tool="skill", tool_id="first"):
    emit({"type": "assistant.tool_call_delta", "data": {"toolCallId": tool_id, "toolName": tool, "inputDelta": part}})

if scenario != "missing_discovery":
    skills = [{"name": name, "path": skill_path, "enabled": scenario != "disabled_skill"}]
    if scenario == "duplicate_original":
        skills.append({"name": name.split("-eval-", 1)[0], "path": "installed/SKILL.md", "enabled": True})
    emit({"type": "session.skills_loaded", "data": {
        "skills": skills
    }})

if scenario in ("partial_skill", "partial_view", "interleaved_tools"):
    tool = "view" if scenario == "partial_view" else "skill"
    argument = json.dumps({"skill": name} if tool == "skill" else {"path": skill_path})
    midpoint = len(argument) // 2
    for index, part in enumerate((argument[:midpoint], argument[midpoint:])):
        data = json.dumps({"type": "assistant.tool_call_delta", "note": "caf\u00e9", "data": {
            "toolCallId": "first", "toolName": tool if index == 0 else None, "inputDelta": part
        }}, ensure_ascii=False).encode("utf-8")
        cut = data.index("\u00e9".encode("utf-8")) + 1
        sys.stdout.buffer.write(data[:cut])
        sys.stdout.buffer.flush()
        time.sleep(0.02)
        sys.stdout.buffer.write(data[cut:] + b"\n")
        sys.stdout.buffer.flush()
        if index == 0 and scenario == "interleaved_tools":
            delta('{"pattern": "*"}', "glob", "second")
    time.sleep(10)
elif scenario == "initial_input":
    emit({"type": "tool.execution_start", "data": {"toolCallId": "first", "toolName": "skill", "arguments": {"skill": name}}})
    time.sleep(10)
elif scenario == "other_tool":
    delta('{"pattern": "*"}', "glob")
    time.sleep(10)
elif scenario in ("other_skill", "prefix_skill"):
    delta(json.dumps({"skill": "other" if scenario == "other_skill" else name + "-other"}))
    time.sleep(10)
elif scenario == "non_target_view":
    delta(json.dumps({"path": skill_path + ".backup"}), "view")
elif scenario in ("assistant_skill", "assistant_view"):
    tool = "skill" if scenario == "assistant_skill" else "view"
    emit({"type": "assistant.message", "data": {"content": "", "toolRequests": [
        {"toolCallId": "first", "name": tool, "arguments": {"skill": name} if tool == "skill" else {"path": skill_path}}
    ]}}, newline=False)
elif scenario in ("success", "missing_discovery", "disabled_skill"):
    emit({"type": "assistant.message", "data": {"content": "Mentioning " + name + " is not an invocation.", "toolRequests": []}})
    emit({"type": "result", "exitCode": 0}, newline=False)
elif scenario == "stderr_flood":
    sys.stderr.buffer.write(b"diagnostic\n" * 20000)
    sys.stderr.buffer.flush()
    emit({"type": "result", "exitCode": 0})
elif scenario == "exit_error":
    sys.stderr.write("CLI authentication failed\n")
    sys.stderr.flush()
    sys.exit(7)
elif scenario == "result_then_exit_error":
    emit({"type": "result", "exitCode": 0})
    sys.stderr.write("late CLI failure\n")
    sys.exit(9)
elif scenario == "result_error":
    emit({"type": "session.error", "data": {"message": "model unavailable", "errorType": "model"}})
elif scenario == "subtype_error":
    emit({"type": "result", "exitCode": 2, "error": "turn limit reached"})
elif scenario == "assistant_error":
    emit({"type": "session.error", "data": {"message": "authentication_failed"}})
elif scenario == "incomplete":
    sys.stdout.write('{"type": "assistant.tool_call_delta", "data":')
    sys.stdout.flush()
elif scenario == "message_only":
    emit({"type": "assistant.idle", "data": {}})
elif scenario == "incomplete_arguments":
    delta('{"skill":')
    emit({"type": "result", "exitCode": 0})
elif scenario == "missing_tool_call_id":
    emit({"type": "assistant.tool_call_delta", "data": {"toolName": "skill", "inputDelta": '{"skill":'}})
    emit({"type": "result", "exitCode": 0})
elif scenario in ("missing_tool_name", "missing_skill_argument", "missing_view_path"):
    tool = {"missing_tool_name": None, "missing_skill_argument": "skill", "missing_view_path": "view"}[scenario]
    emit({"type": "assistant.message", "data": {"toolRequests": [{"name": tool, "arguments": {}}]}})
elif scenario == "timeout":
    sys.stderr.write("still waiting\n")
    sys.stderr.flush()
    sys.stdout.write('{"type":')
    sys.stdout.flush()
    time.sleep(10)
'''


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / f".evaluation-{uuid.uuid4().hex}"
        self.commands = self.root / ".github" / "skills"
        self.commands.mkdir(parents=True)
        self.sentinel = self.commands / "existing.md"
        self.sentinel.write_text("keep", encoding="utf-8")
        self.processes = []
        self.candidates = []
        self.addCleanup(shutil.rmtree, self.root)
        resolver = patch("scripts.copilot_cli.shutil.which", return_value="copilot")
        resolver.start()
        self.addCleanup(resolver.stop)

    def invoke(self, scenario, timeout=3, description="caf\u00e9"):
        popen = subprocess.Popen

        def launch(cmd, **kwargs):
            self.assertEqual(cmd[0], "copilot")
            self.assertNotIn("--allow-all-tools", cmd)
            self.assertEqual(cmd[cmd.index("--model") + 1], "compatible-copilot-model")
            self.assertEqual(cmd[cmd.index("--available-tools") + 1:cmd.index("--allow-tool")], ["skill", "view"])
            candidate = Path(cmd[cmd.index("--add-dir") + 1])
            self.candidates.append(candidate)
            command = next((candidate / ".github" / "skills").glob("demo-eval-*/SKILL.md"))
            self.assertEqual(
                parse_skill_md(command.parent)[1],
                description.rstrip("\n") + "\n",
            )
            self.assertIn("name: " + command.parent.name, command.read_text(encoding="utf-8"))
            self.assertEqual(kwargs["stdin"].read().decode("utf-8"), scenario)
            kwargs["stdin"].seek(0)
            process = popen(
                [sys.executable, "-u", "-c", FAKE_COPILOT, scenario, command.parent.name, str(command)],
                **kwargs,
            )
            self.processes.append(process)
            return process

        with patch.object(run_eval.subprocess, "Popen", side_effect=launch):
            return run_eval.run_single_query(
            scenario, "demo", description, timeout, "compatible-copilot-model"
            )

    def tearDown(self):
        self.assertEqual(list(self.commands.iterdir()), [self.sentinel])
        self.assertTrue(all(not candidate.exists() for candidate in self.candidates))
        for process in self.processes:
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)

    def test_partial_json_and_utf8_detect_tools_before_process_finishes(self):
        for scenario in ("partial_skill", "partial_view", "initial_input", "interleaved_tools"):
            with self.subTest(scenario=scenario):
                self.assertTrue(self.invoke(scenario))

    def test_first_other_tool_or_skill_is_negative_without_waiting(self):
        for scenario in ("other_tool", "other_skill", "prefix_skill", "non_target_view"):
            with self.subTest(scenario=scenario):
                self.assertFalse(self.invoke(scenario))

    def test_fast_exit_and_final_unterminated_assistant_line(self):
        for scenario in ("assistant_skill", "assistant_view"):
            with self.subTest(scenario=scenario):
                self.assertTrue(self.invoke(scenario))

    def test_successful_result_is_negative_including_final_unterminated_line(self):
        self.assertFalse(self.invoke("success"))

    def test_stderr_is_drained_without_deadlocking(self):
        self.assertFalse(self.invoke("stderr_flood"))

    def test_cli_errors_are_not_negative_results(self):
        scenarios = {
            "exit_error": "exited 7.*CLI authentication failed",
            "result_then_exit_error": "exited 9.*late CLI failure",
            "result_error": "model unavailable",
            "subtype_error": "turn limit reached",
            "assistant_error": "authentication_failed",
        }
        for scenario, message in scenarios.items():
            with self.subTest(scenario=scenario):
                with self.assertRaisesRegex(RuntimeError, "(?s)" + message) as raised:
                    self.invoke(scenario)
                self.assertIn("Copilot CLI version:", str(raised.exception))

    def test_incomplete_stream_is_not_negative(self):
        for scenario in ("incomplete", "message_only", "incomplete_arguments"):
            with self.subTest(scenario=scenario):
                with self.assertRaisesRegex(RuntimeError, "incomplete stream"):
                    self.invoke(scenario)

    def test_invalid_tool_requests_are_not_negative_results(self):
        for scenario in ("missing_tool_name", "missing_skill_argument", "missing_view_path", "missing_tool_call_id"):
            with self.subTest(scenario=scenario), self.assertRaisesRegex(RuntimeError, "invalid"):
                self.invoke(scenario)

    def test_timeout_on_partial_line_is_bounded_and_cleans_up(self):
        start = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "timed out"):
            self.invoke("timeout", timeout=0.3)
        self.assertLess(time.monotonic() - start, 3)

    def test_candidate_description_preserves_blank_lines(self):
        self.assertFalse(
            self.invoke("success", description="First line\n\nSecond line\n")
        )

    def test_candidate_cleanup_preserves_the_primary_error_on_windows(self):
        temporary_directory = tempfile.TemporaryDirectory
        with patch.object(
            run_eval.tempfile,
            "TemporaryDirectory",
            wraps=temporary_directory,
        ) as temporary:
            self.assertFalse(self.invoke("success"))
        temporary.assert_called_once_with(
            prefix="copilot-skill-eval-",
            ignore_cleanup_errors=True,
        )

    def test_launch_failure_cleans_command_file(self):
        temporary = tempfile.TemporaryDirectory(prefix="launch-failure-")
        candidate = Path(temporary.name)
        with patch.object(run_eval.tempfile, "TemporaryDirectory", return_value=temporary), \
             patch.object(run_eval.subprocess, "Popen", side_effect=FileNotFoundError("copilot missing")):
            with self.assertRaisesRegex(FileNotFoundError, "copilot missing"):
                run_eval.run_single_query("query", "demo", "description", 1)
        self.assertFalse(candidate.exists())

    def test_missing_discovery_event_can_score_a_no_tool_answer(self):
        self.assertFalse(self.invoke("missing_discovery"))

    def test_explicitly_disabled_candidate_cannot_pass(self):
        with self.assertRaisesRegex(RuntimeError, "discover"):
            self.invoke("disabled_skill")

    def test_original_skill_competitor_aborts_the_measurement(self):
        with self.assertRaisesRegex(RuntimeError, "original skill being optimized.*installed/SKILL.md"):
            self.invoke("duplicate_original")

    def test_loop_startup_uses_report_renderer_instead_of_forced_meta_refresh(self):
        eval_path = self.root / "trigger.json"
        report_path = self.root / "report.html"
        eval_path.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
        argv = [
            "run_loop", "--eval-set", str(eval_path),
            "--skill-path", str(Path(__file__).resolve().parents[1]),
            "--report", str(report_path), "--holdout", "0",
        ]
        with patch.object(sys, "argv", argv), \
             patch.object(sys, "stdout", new_callable=io.StringIO), \
             patch.object(sys, "stderr", new_callable=io.StringIO), \
             patch.object(run_loop, "run_loop", return_value={"history": []}), \
             patch.object(run_loop.webbrowser, "open"), \
             patch.object(run_loop, "generate_html", return_value="<html>report controls</html>") as render:
            run_loop.main()
        self.assertEqual(render.call_args_list[0].args[0]["history"], [])
        self.assertTrue(render.call_args_list[0].kwargs["auto_refresh"])
        self.assertFalse(render.call_args_list[-1].kwargs["auto_refresh"])
        self.assertEqual(report_path.read_text(encoding="utf-8"), "<html>report controls</html>")

    def test_documented_task_workspace_layout_is_aggregated(self):
        from scripts.aggregate_benchmark import load_run_results

        eval_dir = self.root / "eval-7-output-check"
        eval_dir.mkdir()
        (eval_dir / "eval_metadata.json").write_text(json.dumps({
            "eval_id": 7, "eval_name": "output-check", "prompt": "Check output",
            "expectations": ["Output is complete"],
        }), encoding="utf-8")
        for config in ("with_skill", "without_skill", "old_skill"):
            run_dir = eval_dir / config / "run-1"
            (run_dir / "outputs").mkdir(parents=True)
            (run_dir / "grading.json").write_text(json.dumps({
                "expectations": [{"text": "Output is complete", "passed": True, "evidence": "Checked"}],
                "summary": {"passed": 1, "failed": 0, "total": 1, "pass_rate": 1.0},
            }), encoding="utf-8")
            (run_dir / "timing.json").write_text(json.dumps({
                "total_tokens": 42, "total_duration_seconds": 2.5,
            }), encoding="utf-8")
        results = load_run_results(self.root)
        self.assertEqual(set(results), {"with_skill", "without_skill", "old_skill"})
        for rows in results.values():
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["eval_id"], 7)
            self.assertEqual(rows[0]["run_number"], 1)
            self.assertEqual(rows[0]["pass_rate"], 1.0)
            self.assertEqual(rows[0]["tokens"], 42)
            self.assertEqual(rows[0]["time_seconds"], 2.5)


class EvaluationTests(unittest.TestCase):
    def evaluate(self, eval_set, outcomes, **options):
        futures = []
        for outcome in outcomes:
            future = Future()
            if isinstance(outcome, Exception):
                future.set_exception(outcome)
            else:
                future.set_result(outcome)
            futures.append(future)
        with patch.object(run_eval, "ThreadPoolExecutor") as executor, \
             patch.object(run_eval, "copilot_version", return_value="test-version"):
            executor.return_value.submit.side_effect = futures
            with patch.object(run_eval, "as_completed", side_effect=lambda _: reversed(futures)):
                return run_eval.run_eval(
                    eval_set, "demo", "description",
                    **({"num_workers": 2, "timeout": 1, **options}),
                )

    def test_duplicate_queries_keep_independent_counts_labels_and_input_order(self):
        entries = [
            {"query": "same", "should_trigger": True},
            {"query": "same", "should_trigger": False},
            {"query": "third", "should_trigger": True},
            {"query": "same", "should_trigger": True},
        ]
        before = copy.deepcopy(entries)
        result = self.evaluate(entries, [True, True, False, False, False, True, False, False], runs_per_query=2)
        rows = result["results"]
        self.assertEqual([row["eval_id"] for row in rows], [0, 1, 2, 3])
        self.assertEqual([row["query"] for row in rows], ["same", "same", "third", "same"])
        self.assertEqual([row["triggers"] for row in rows], [2, 0, 1, 0])
        self.assertEqual([row["runs"] for row in rows], [2, 2, 2, 2])
        self.assertEqual([row["pass"] for row in rows], [True, True, True, False])
        self.assertEqual(result["summary"], {"total": 4, "passed": 3, "failed": 1})
        self.assertEqual(result["copilot_cli_version"], "test-version")
        self.assertEqual(entries, before)

    def test_failed_worker_aborts_instead_of_passing_a_negative_query(self):
        with self.assertRaisesRegex(RuntimeError, "entry 0, run 1 failed.*CLI unavailable"):
            self.evaluate([{"query": "negative", "should_trigger": False}], [RuntimeError("CLI unavailable")])

    def test_failed_worker_does_not_wait_for_active_workers(self):
        failed = Future()
        failed.set_exception(RuntimeError("CLI unavailable"))
        executor = mock.Mock()
        executor.submit.return_value = failed
        with patch.object(run_eval, "ThreadPoolExecutor", return_value=executor), \
             patch.object(run_eval, "copilot_version", return_value="test-version"), \
             patch.object(run_eval, "as_completed", return_value=[failed]), \
             self.assertRaises(RuntimeError):
            run_eval.run_eval(
                [{"query": "negative", "should_trigger": False}],
                "demo", "description", 1, 1,
            )
        executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    def test_failed_worker_signals_active_siblings_to_stop(self):
        active_started = threading.Event()
        cancellation_seen = threading.Event()

        def evaluate(query, _name, _description, _timeout, _model, cancelled, _version):
            if query == "slow":
                active_started.set()
                if cancelled.wait(1):
                    cancellation_seen.set()
                raise RuntimeError("cancelled")
            self.assertTrue(active_started.wait(1))
            raise RuntimeError("CLI unavailable")

        with patch.object(run_eval, "run_single_query", side_effect=evaluate), \
             patch.object(run_eval, "copilot_version", return_value="test-version"), \
             self.assertRaisesRegex(RuntimeError, "CLI unavailable"):
            run_eval.run_eval(
                [
                    {"query": "slow", "should_trigger": True},
                    {"query": "fail", "should_trigger": True},
                ],
                "demo", "description", 2, 1,
            )
        self.assertTrue(cancellation_seen.is_set())

    def test_cli_reports_invalid_eval_files_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            task_shaped = root / "task-evals.json"
            task_shaped.write_text('{"evals": []}', encoding="utf-8")
            cases = (
                (root / "missing.json", "Error:"),
                (malformed, "Error:"),
                (task_shaped, "Error: Trigger eval set must be a nonempty list"),
            )
            for invalid, expected in cases:
                with self.subTest(invalid=invalid), patch.object(sys, "argv", [
                    "run_eval", "--eval-set", str(invalid), "--skill-path", str(root),
                ]), patch.object(sys, "stderr", new_callable=io.StringIO) as stderr, \
                     self.assertRaises(SystemExit) as raised:
                    run_eval.main()
                self.assertEqual(raised.exception.code, 1)
                self.assertIn(expected, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_invalid_trigger_inputs_fail_before_launch(self):
        invalid = [[], {}, {"evals": []}, [None], [{"query": " ", "should_trigger": True}],
                   [{"query": "q", "should_trigger": "false"}], [{"prompt": "task", "expectations": []}]]
        with patch.object(run_eval, "ThreadPoolExecutor") as executor:
            for entries in invalid:
                with self.subTest(entries=entries), self.assertRaises(ValueError):
                    run_eval.run_eval(entries, "demo", "description", 1, 1)
            executor.assert_not_called()

    def test_invalid_numeric_options_fail_before_launch(self):
        for options in ({"num_workers": 0}, {"runs_per_query": 0}, {"timeout": 0},
                        {"timeout": float("nan")}, {"trigger_threshold": 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.evaluate([{"query": "q", "should_trigger": True}], [], **options)


class HoldoutTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"query": "identical query", "should_trigger": label}
            for label in (True, False, True, False, True, False)
        ]

    def test_split_is_reproducible_ordered_and_does_not_reset_global_rng(self):
        entries = [dict(item, eval_id=i) for i, item in enumerate(self.entries)]
        rng_state = random.getstate()
        train, test = run_loop.split_eval_set(entries, 0.4)
        self.assertEqual(random.getstate(), rng_state)
        self.assertEqual((train, test), run_loop.split_eval_set(entries, 0.4))
        self.assertEqual(len(train), 4)
        self.assertEqual(len(test), 2)
        ids = lambda rows: [row["eval_id"] for row in rows]
        self.assertEqual(ids(train), sorted(ids(train)))
        self.assertEqual(ids(test), sorted(ids(test)))
        self.assertFalse(set(ids(train)) & set(ids(test)))
        self.assertEqual(sorted(ids(train) + ids(test)), list(range(6)))

    def test_small_split_retains_training_examples_and_rejects_impossible_holdout(self):
        train, test = run_loop.split_eval_set(self.entries[:4], 0.99)
        self.assertEqual(len(train), 2)
        self.assertEqual(len(test), 2)
        self.assertEqual({item["should_trigger"] for item in train}, {True, False})
        self.assertEqual({item["should_trigger"] for item in test}, {True, False})
        with self.assertRaisesRegex(ValueError, "at least two entries for each label"):
            run_loop.split_eval_set(self.entries[:2], 0.4)
        imbalanced = [
            {"query": f"query {index}", "should_trigger": index == 0}
            for index in range(6)
        ]
        with self.assertRaisesRegex(ValueError, "at least two entries for each label"):
            run_loop.split_eval_set(imbalanced, 0.4)
        self.assertEqual(run_loop.split_eval_set(self.entries[:2], 0), (self.entries[:2], []))
        for fraction in (-0.1, 1, float("nan")):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                run_loop.split_eval_set(self.entries, fraction)

    def test_loop_maps_duplicate_entries_to_holdout_by_original_id_and_blinds_improver(self):
        original = copy.deepcopy(self.entries)
        batches = []
        report_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, report_dir)

        def evaluate(**kwargs):
            batches.append(copy.deepcopy(kwargs["eval_set"]))
            return {"results": [
                {"eval_id": i, "query": item["query"], "should_trigger": item["should_trigger"],
                 "trigger_rate": 0.0, "triggers": 0, "runs": 1, "pass": False}
                for i, item in enumerate(kwargs["eval_set"])
            ]}

        with patch.object(run_loop, "parse_skill_md", return_value=("demo", "old", "skill content")), \
             patch.object(run_loop, "run_eval", side_effect=evaluate), \
             patch.object(run_loop, "improve_description", return_value="new") as improve, \
             patch.object(run_loop, "generate_html", return_value="<html></html>") as render:
            result = run_loop.run_loop(
                self.entries, Path.cwd(), None, 1, 1, 2, 1, 0.5, 0.4,
                "copilot-model", False, report_dir / "report.html",
            )
        self.assertEqual(self.entries, original)
        self.assertEqual(result["train_size"], 4)
        self.assertEqual(result["test_size"], 2)
        first, second = result["history"]
        train_ids = [row["eval_id"] for row in first["train_results"]]
        test_ids = [row["eval_id"] for row in first["test_results"]]
        self.assertEqual(sorted(train_ids + test_ids), list(range(6)))
        self.assertFalse(set(train_ids) & set(test_ids))
        self.assertEqual(train_ids, [row["eval_id"] for row in second["train_results"]])
        self.assertEqual(test_ids, [row["eval_id"] for row in second["test_results"]])
        self.assertEqual(batches[0], batches[1])
        self.assertEqual([item["eval_id"] for item in batches[0]], list(range(6)))
        sent = improve.call_args.kwargs
        self.assertEqual([row["eval_id"] for row in sent["eval_results"]["results"]], train_ids)
        self.assertEqual(sent["history"], [])
        self.assertTrue(all(call.args[0]["test_size"] == 2 for call in render.call_args_list))

    def test_loop_without_holdout_keeps_all_entries_in_train(self):
        rows = [
            {"eval_id": i, "query": item["query"], "should_trigger": item["should_trigger"], "pass": True}
            for i, item in enumerate(self.entries)
        ]
        with patch.object(run_loop, "parse_skill_md", return_value=("demo", "old", "content")), \
             patch.object(run_loop, "run_eval", return_value={"results": rows}), \
             patch.object(run_loop, "improve_description") as improve:
            result = run_loop.run_loop(
                self.entries, Path.cwd(), None, 1, 1, 2, 1, 0.5, 0, "copilot-model", False
            )
        self.assertEqual(result["train_size"], 6)
        self.assertEqual(result["test_size"], 0)
        self.assertEqual(result["best_score"], "6/6")
        self.assertEqual(result["history"][0]["train_results"], rows)
        self.assertIsNone(result["history"][0]["test_results"])
        improve.assert_not_called()

    def test_best_description_uses_correct_run_rate_then_earliest_iteration(self):
        def attempt(iteration, description, triggers):
            return {
                "iteration": iteration,
                "description": description,
                "test_passed": 1,
                "test_total": 1,
                "test_results": [{
                    "should_trigger": True,
                    "triggers": triggers,
                    "runs": 3,
                    "pass": True,
                }],
            }

        history = [attempt(1, "first", 2), attempt(2, "second", 3)]
        output = run_loop.build_output(
            history, "original", "latest", 0.4, [{}], [{}], "done"
        )
        self.assertEqual(output["best_description"], "second")

        history.append(attempt(3, "third", 3))
        output = run_loop.build_output(
            history, "original", "latest", 0.4, [{}], [{}], "done"
        )
        self.assertEqual(output["best_description"], "second")

    def test_loop_aborts_on_evaluator_failure_without_improving(self):
        with patch.object(run_loop, "parse_skill_md", return_value=("demo", "old", "content")), \
             patch.object(run_loop, "copilot_version", return_value="test-version"), \
             patch.object(run_loop, "run_eval", side_effect=RuntimeError("CLI failed")), \
             patch.object(run_loop, "improve_description") as improve:
            result = run_loop.run_loop(
                self.entries, Path.cwd(), None, 1, 1, 2, 1, 0.5, 0.4, "copilot-model", False
            )
        self.assertEqual(result["iterations_run"], 0)
        self.assertEqual(result["best_score"], "not evaluated")
        self.assertEqual(result["error"], "CLI failed")
        self.assertEqual(result["copilot_cli_version"], "test-version")
        improve.assert_not_called()

    def test_loop_keeps_completed_iterations_when_a_later_evaluation_fails(self):
        rows = [
            {"eval_id": index, "query": item["query"], "should_trigger": item["should_trigger"],
             "trigger_rate": 0.0, "triggers": 0, "runs": 1, "pass": False}
            for index, item in enumerate(self.entries)
        ]
        with patch.object(run_loop, "parse_skill_md", return_value=("demo", "old", "content")), \
             patch.object(run_loop, "run_eval", side_effect=[{"results": rows}, RuntimeError("CLI failed")]), \
             patch.object(run_loop, "improve_description", return_value="new"):
            result = run_loop.run_loop(
                self.entries, Path.cwd(), None, 1, 1, 2, 1, 0.5, 0, "copilot-model", False
            )
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["description"], "old")
        self.assertEqual(result["final_description"], "new")
        self.assertEqual(result["error"], "CLI failed")

    def test_loop_preserves_completed_iteration_when_improver_times_out(self):
        rows = [
            {"eval_id": index, "query": item["query"], "should_trigger": item["should_trigger"],
             "trigger_rate": 0.0, "triggers": 0, "runs": 1, "pass": False}
            for index, item in enumerate(self.entries)
        ]
        timeout = subprocess.TimeoutExpired("copilot", 300)
        with patch.object(run_loop, "parse_skill_md", return_value=("demo", "old", "content")), \
             patch.object(run_loop, "run_eval", return_value={"results": rows}), \
             patch.object(run_loop, "improve_description", side_effect=timeout):
            result = run_loop.run_loop(
                self.entries, Path.cwd(), None, 1, 1, 2, 1, 0.5, 0,
                "copilot-model", False,
            )
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["description"], "old")
        self.assertIn("timed out after 300 seconds", result["error"])

    def test_main_persists_structured_failure_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
            output = {
                "error": "CLI failed", "history": [], "best_score": "not evaluated",
                "original_description": "Demo skill.", "best_description": "Demo skill.",
            }
            argv = [
                "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                "--report", "none", "--results-dir", str(root / "results"), "--holdout", "0",
            ]
            with patch.object(sys, "argv", argv), \
                 patch.object(run_loop, "run_loop", return_value=output):
                with self.assertRaises(SystemExit) as raised:
                    run_loop.main()
            self.assertEqual(raised.exception.code, 1)
            result_file = next((root / "results").glob("*/results.json"))
            self.assertEqual(json.loads(result_file.read_text(encoding="utf-8"))["error"], "CLI failed")

    def test_main_uses_a_default_results_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
            output = {"history": [], "best_score": "not evaluated"}
            with patch.object(sys, "argv", [
                "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                "--report", "none", "--holdout", "0",
            ]), patch.object(run_loop, "run_loop", return_value=output):
                run_loop.main()
            self.assertTrue(next((root / "skill-creator-results").glob("*/results.json")).exists())

    def test_concurrent_starts_use_distinct_result_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(
                json.dumps([{"query": "q", "should_trigger": True}]),
                encoding="utf-8",
            )
            argv = [
                "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                "--report", "none", "--holdout", "0",
            ]
            with patch.object(sys, "argv", argv), \
                 patch.object(run_loop, "run_loop", return_value={"history": []}), \
                 patch.object(run_loop.time, "strftime", return_value="same-second"):
                run_loop.main()
                run_loop.main()
            result_files = list((root / "skill-creator-results").glob("*/results.json"))
            self.assertEqual(len(result_files), 2)
            self.assertNotEqual(result_files[0].parent, result_files[1].parent)

    def test_main_default_report_uses_temp_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
            output = {"history": [], "best_score": "not evaluated"}
            with patch.object(sys, "argv", [
                "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                "--holdout", "0",
            ]), patch.object(run_loop, "run_loop", return_value=output), \
                 patch.object(run_loop.tempfile, "gettempdir", return_value=str(root)), \
                 patch.object(run_loop, "atomic_write_text") as write, \
                 patch.object(run_loop.webbrowser, "open") as opened:
                run_loop.main()
            self.assertTrue(any(call.args[0].parent == root for call in write.call_args_list))
            opened.assert_called_once()

    def test_main_reports_eval_input_errors_without_tracebacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            for eval_set in (root / "missing.json", malformed):
                with self.subTest(eval_set=eval_set), patch.object(sys, "argv", [
                    "run_loop", "--eval-set", str(eval_set), "--skill-path", str(root),
                    "--report", "none",
                ]), patch.object(sys, "stderr", new_callable=io.StringIO) as stderr, \
                     self.assertRaises(SystemExit) as raised:
                    run_loop.main()
                self.assertEqual(raised.exception.code, 1)
                self.assertIn("Error:", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_reports_output_path_errors_before_opening_browser(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
            blocker = root / "blocker"
            blocker.write_text("file", encoding="utf-8")
            report_directory = root / "report-directory"
            report_directory.mkdir()
            cases = (
                ["--results-dir", str(blocker / "nested"), "--report", "none"],
                ["--results-dir", str(root / "results"), "--report", str(report_directory)],
            )
            for options in cases:
                with self.subTest(options=options), patch.object(sys, "argv", [
                    "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                    "--holdout", "0", *options,
                ]), patch.object(sys, "stderr", new_callable=io.StringIO) as stderr, \
                     patch.object(run_loop.webbrowser, "open") as opened, \
                     self.assertRaises(SystemExit) as raised:
                    run_loop.main()
                self.assertEqual(raised.exception.code, 1)
                self.assertIn("Error:", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                opened.assert_not_called()

    def test_main_reports_final_persistence_errors_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
            with patch.object(sys, "argv", [
                "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                "--holdout", "0", "--report", "none",
            ]), patch.object(run_loop, "run_loop", return_value={"history": []}), \
                 patch.object(run_loop, "atomic_write_text", side_effect=OSError("disk full")), \
                 patch.object(sys, "stderr", new_callable=io.StringIO) as stderr, \
                 self.assertRaises(SystemExit) as raised:
                run_loop.main()
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("Error: disk full", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_rejects_impossible_holdout_before_opening_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            eval_set = root / "evals.json"
            eval_set.write_text(json.dumps([{"query": "q", "should_trigger": True}]), encoding="utf-8")
            report = root / "report.html"
            with patch.object(sys, "argv", [
                "run_loop", "--eval-set", str(eval_set), "--skill-path", str(skill),
                "--report", str(report),
            ]), patch.object(run_loop.webbrowser, "open") as opened, \
                 patch.object(run_loop, "run_loop") as execute, \
                 patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    run_loop.main()
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("holdout needs at least two entries", stderr.getvalue())
            opened.assert_not_called()
            execute.assert_not_called()
            self.assertFalse(report.exists())

    def test_atomic_report_write_preserves_previous_file_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.html"
            report.write_text("previous", encoding="utf-8")
            with patch.object(Path, "replace", side_effect=OSError("Disk error")):
                with self.assertRaisesRegex(OSError, "Disk error"):
                    atomic_write_text(report, "partial")
            self.assertEqual(report.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(root.iterdir()), [report])

    @unittest.skipUnless(sys.platform == "win32", "Windows read-only replacement behavior")
    def test_atomic_write_read_only_destination_preserves_error_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.html"
            report.write_text("previous", encoding="utf-8")
            report.chmod(stat.S_IREAD)
            try:
                with self.assertRaises(PermissionError) as raised:
                    atomic_write_text(report, "partial")
                self.assertIn("report.html", str(raised.exception))
                self.assertEqual(report.read_text(encoding="utf-8"), "previous")
                self.assertEqual(list(root.iterdir()), [report])
            finally:
                report.chmod(stat.S_IWRITE)

    def test_skill_reader_uses_utf8_and_preserves_name(self):
        skill_path = Path(__file__).resolve().parents[1]
        name, description, content = parse_skill_md(skill_path)
        self.assertEqual(name, "skill-creator")
        self.assertTrue(description)
        self.assertIn("—", content)


class BenchmarkAndPackagingTests(unittest.TestCase):
    def add_run(self, root, config, number, pass_rate, tokens=84852, timing=4.0, timing_file_duration=3.0, eval_id=1):
        run_dir = root / f"eval-{eval_id}-comparison" / config / f"run-{number}"
        run_dir.mkdir(parents=True)
        (run_dir.parent.parent / "eval_metadata.json").write_text(
            json.dumps({"eval_id": eval_id, "eval_name": f"Comparison {eval_id}"}), encoding="utf-8"
        )
        grading = {
            "summary": {"pass_rate": pass_rate, "passed": round(pass_rate * 10), "failed": 0, "total": 10},
            "expectations": [{"text": "Unicode evidence", "passed": True, "evidence": "Caf\u00e9"}],
        }
        if timing is not None:
            grading["timing"] = {"total_duration_seconds": timing}
        (run_dir / "grading.json").write_text(json.dumps(grading), encoding="utf-8")
        if tokens is not None:
            timing_data = {"total_tokens": tokens}
            if timing_file_duration is not None:
                timing_data["total_duration_seconds"] = timing_file_duration
            (run_dir / "timing.json").write_text(json.dumps(timing_data), encoding="utf-8")

    def test_benchmark_orders_primary_before_baseline_and_uses_actual_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "old_skill", 1, 0.2)
            self.add_run(root, "old_skill", 2, 0.2)
            self.add_run(root, "with_skill", 1, 0.9)
            loaded = aggregate_benchmark.load_run_results(root)
            self.assertEqual(loaded["with_skill"][0]["tokens"], 84852)
            summary = aggregate_benchmark.aggregate_results(loaded)
            self.assertEqual(list(summary), ["with_skill", "old_skill", "delta"])
            self.assertEqual(summary["delta"]["pass_rate"], "+70%")
            benchmark = aggregate_benchmark.generate_benchmark(
                root, "demo", analysis_notes=["Skill improves the tested expectation."]
            )
            self.assertNotIn("executor_model", benchmark["metadata"])
            self.assertEqual(benchmark["metadata"]["runs_per_configuration"], {"with_skill": 1, "old_skill": 2})
            self.assertEqual(benchmark["runs"][0]["configuration"], "with_skill")
            self.assertEqual(benchmark["runs"][0]["result"]["tokens"], 84852)
            self.assertEqual(benchmark["runs"][0]["eval_name"], "Comparison 1")
            markdown = aggregate_benchmark.generate_markdown(benchmark)
            self.assertNotIn("**Model**", markdown)
            self.assertIn("with skill: 1, old skill: 2", markdown)
            self.assertIn("| Pass Rate | 90% ± 0% | 20% ± 0% | +70% |", markdown)
            self.assertIn("## Notes", markdown)
            self.assertIn("Skill improves the tested expectation.", markdown)

    def test_analysis_notes_cli_merges_validated_notes_into_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9)
            notes_path = root / "analysis_notes.json"
            notes_path.write_text(json.dumps(["A measured observation."]), encoding="utf-8")
            with patch.object(sys, "argv", [
                "aggregate_benchmark", str(root), "--notes", str(notes_path),
            ]), contextlib.redirect_stdout(io.StringIO()):
                aggregate_benchmark.main()
            benchmark = json.loads((root / "benchmark.json").read_text(encoding="utf-8"))
            self.assertEqual(benchmark["notes"], ["A measured observation."])
            markdown = (root / "benchmark.md").read_text(encoding="utf-8")
            self.assertIn("A measured observation.", markdown)
            self.assertTrue(markdown.endswith("\n"))

            notes_path.write_text('{"note":"wrong shape"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON array"):
                aggregate_benchmark.load_analysis_notes(notes_path)

    def test_reaggregation_preserves_existing_analysis_notes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9)
            (root / "benchmark.json").write_text(
                json.dumps({"notes": ["Preserve this observation."]}),
                encoding="utf-8",
            )
            with patch.object(sys, "argv", ["aggregate_benchmark", str(root)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                aggregate_benchmark.main()
            benchmark = json.loads((root / "benchmark.json").read_text(encoding="utf-8"))
            self.assertEqual(benchmark["notes"], ["Preserve this observation."])
            self.assertIn(
                "Preserve this observation.",
                (root / "benchmark.md").read_text(encoding="utf-8"),
            )

    def test_benchmark_omits_tokens_when_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9, tokens=None)
            self.add_run(root, "without_skill", 1, 0.2, tokens=None)
            benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertNotIn("tokens", benchmark["runs"][0]["result"])
            self.assertNotIn("tokens", benchmark["run_summary"]["with_skill"])
            self.assertNotIn("Tokens", aggregate_benchmark.generate_markdown(benchmark))

    def test_benchmark_omits_incomplete_measurements_and_counts_runs_per_eval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for eval_id in (1, 2):
                for config, pass_rate in (("with_skill", 0.9), ("without_skill", 0.2)):
                    for number in (1, 2, 3):
                        self.add_run(
                            root, config, number, pass_rate,
                            tokens=100 if number != 3 else None,
                            timing=4.0 if number != 3 else None,
                            timing_file_duration=None,
                            eval_id=eval_id,
                        )
            benchmark = aggregate_benchmark.generate_benchmark(root, "demo", executor_model="model-a", analyzer_model="model-b")
            self.assertEqual(benchmark["metadata"]["runs_per_configuration"], 3)
            self.assertEqual(benchmark["metadata"]["executor_model"], "model-a")
            self.assertEqual(benchmark["metadata"]["analyzer_model"], "model-b")
            self.assertNotIn("time_seconds", benchmark["run_summary"]["with_skill"])
            self.assertNotIn("tokens", benchmark["run_summary"]["with_skill"])
            self.assertIn("time_seconds", benchmark["runs"][0]["result"])
            self.assertNotIn("time_seconds", benchmark["runs"][2]["result"])
            self.assertNotIn("tokens", benchmark["run_summary"]["delta"])
            markdown = aggregate_benchmark.generate_markdown(benchmark)
            self.assertNotIn("| Time |", markdown)
            self.assertNotIn("| Tokens |", markdown)
            self.assertLess(markdown.index("**Date**"), markdown.index("**Executor model**"))
            self.assertLess(markdown.index("**Executor model**"), markdown.index("**Analyzer model**"))
            self.assertLess(markdown.index("**Analyzer model**"), markdown.index("**Evals**"))

    def test_invalid_run_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9)
            invalid = root / "eval-1-comparison" / "with_skill" / "run-retry"
            invalid.mkdir()
            (invalid / "grading.json").write_text("{}", encoding="utf-8")
            self.assertEqual(len(aggregate_benchmark.load_run_results(root)["with_skill"]), 1)

    def test_ungraded_baseline_is_not_reported_as_zero_percent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9)
            (root / "eval-1-comparison" / "without_skill" / "run-1").mkdir(parents=True)
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertEqual(list(benchmark["run_summary"]), ["with_skill"])
            self.assertEqual(benchmark["metadata"]["runs_per_configuration"], 1)
            self.assertNotIn("delta", benchmark["run_summary"])
            markdown = aggregate_benchmark.generate_markdown(benchmark)
            self.assertIn("| Metric | With Skill |", markdown)
            self.assertNotIn("Config B", markdown)
            self.assertNotIn("| Delta |", markdown)
            self.assertIn("grading.json not found", stderr.getvalue())

    def test_entirely_ungraded_workspace_does_not_report_zero_percent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "eval-1-comparison" / "with_skill" / "run-1").mkdir(parents=True)
            with patch("sys.stderr", new_callable=io.StringIO):
                benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertEqual(benchmark["run_summary"], {})
            markdown = aggregate_benchmark.generate_markdown(benchmark)
            self.assertIn("No graded runs available.", markdown)
            self.assertNotIn("0%", markdown)

    def test_missing_pass_rate_is_skipped_as_ungraded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9)
            grading = root / "eval-1-comparison" / "with_skill" / "run-1" / "grading.json"
            grading.write_text(json.dumps({"summary": {"passed": 1, "total": 1}}), encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertEqual(benchmark["run_summary"], {})
            self.assertIn("Missing or invalid summary.pass_rate", stderr.getvalue())

    def test_mixed_eval_id_types_sort_without_crashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9, eval_id=1)
            self.add_run(root, "with_skill", 1, 0.8, eval_id="2")
            benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertEqual(benchmark["metadata"]["evals_run"], [1, "2"])

    def test_malformed_grading_shapes_are_omitted_without_fabricated_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "eval-12-comparison" / "with_skill" / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir.parent.parent / "eval_metadata.json").write_text(
                json.dumps({"eval_name": "Directory fallback"}), encoding="utf-8"
            )
            (run_dir / "grading.json").write_text(json.dumps({
                "summary": {"pass_rate": 0.5, "passed": 1, "total": 2},
                "execution_metrics": "invalid",
                "expectations": {"text": "not a list"},
                "user_notes_summary": {
                    "uncertainties": "not a list",
                    "needs_review": ["Keep this", 7],
                    "workarounds": [],
                },
            }), encoding="utf-8")
            invalid_root = run_dir.parent / "run-2"
            invalid_root.mkdir()
            (invalid_root / "grading.json").write_text("[]", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertEqual(len(benchmark["runs"]), 1)
            result = benchmark["runs"][0]["result"]
            self.assertEqual(benchmark["runs"][0]["eval_id"], 12)
            self.assertNotIn("tool_calls", result)
            self.assertNotIn("errors", result)
            self.assertEqual(benchmark["runs"][0]["expectations"], [])
            self.assertEqual(benchmark["runs"][0]["notes"], ["Keep this"])
            self.assertIn("Invalid execution_metrics", stderr.getvalue())
            self.assertIn("Invalid expectations", stderr.getvalue())
            self.assertIn("grading.json must contain an object", stderr.getvalue())

    def test_invalid_metadata_ids_are_normalized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory_id, metadata_id in ((7, None), (8, [1])):
                self.add_run(root, "with_skill", 1, 0.9, eval_id=directory_id)
                metadata = root / f"eval-{directory_id}-comparison" / "eval_metadata.json"
                value = json.loads(metadata.read_text(encoding="utf-8"))
                value["eval_id"] = metadata_id
                metadata.write_text(json.dumps(value), encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                benchmark = aggregate_benchmark.generate_benchmark(root, "demo")
            self.assertEqual(benchmark["metadata"]["evals_run"], [7, 8])
            self.assertIn("Invalid eval_id", stderr.getvalue())

    def test_empty_statistics_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "without measured values"):
            aggregate_benchmark.calculate_stats([])

    def test_markdown_summary_includes_every_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.add_run(root, "with_skill", 1, 0.9)
            self.add_run(root, "old_skill", 1, 0.6)
            self.add_run(root, "without_skill", 1, 0.2)
            markdown = aggregate_benchmark.generate_markdown(
                aggregate_benchmark.generate_benchmark(root, "demo")
            )
            self.assertIn(
                "| Metric | With Skill | Old Skill | Without Skill | Delta |",
                markdown,
            )
            self.assertIn("Delta compares With Skill minus Old Skill.", markdown)

    def test_validator_and_packager_need_no_pyyaml_and_preserve_utf8(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "unicode-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: unicode-skill\ndescription: Handles Caf\u00e9 and \u6771\u4eac requests.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
            package = package_skill(skill, root / "packages")
            self.assertTrue(package.exists())

    def test_validator_rejects_unsafe_plain_yaml_descriptions(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            skill_md.write_text(
                "---\nname: demo\ndescription: Use when: the user asks.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(
                validate_skill(skill),
                (False, "Plain description is not YAML-safe; quote it or use a description: | block"),
            )
            skill_md.write_text(
                '---\nname: demo\ndescription: "Use when: the user asks."\n---\n',
                encoding="utf-8",
            )
            self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
            skill_md.write_text(
                "---\nname: demo\ndescription: |\n  Use when: the user asks.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
            self.assertEqual(
                parse_skill_md(skill)[1],
                "Use when: the user asks.\n",
            )

    def test_validator_rejects_frontmatter_without_value_separator(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            for frontmatter in (
                "name:demo\ndescription: Demo skill.",
                "name: demo\ndescription:Demo skill.",
            ):
                with self.subTest(frontmatter=frontmatter):
                    skill_md.write_text(
                        f"---\n{frontmatter}\n---\n", encoding="utf-8"
                    )
                    self.assertFalse(validate_skill(skill)[0])
                    with self.assertRaisesRegex(ValueError, "separated from keys"):
                        parse_skill_md(skill)

    def test_quoted_yaml_descriptions_decode_without_stripping_content_quotes(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            cases = (
                ("'It''s useful.'", "It's useful."),
                ('"Say \\"hi\\" and use \\u6771\\u4eac."', 'Say "hi" and use 東京.'),
                ('Use when the user says "deploy"', 'Use when the user says "deploy"'),
            )
            for scalar, expected in cases:
                with self.subTest(scalar=scalar):
                    skill_md.write_text(
                        f"---\nname: demo\ndescription: {scalar}\n---\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
                    self.assertEqual(parse_skill_md(skill)[1], expected)
            skill_md.write_text(
                '---\nname: demo\ndescription: "Deploy" helper for "prod"\n---\n',
                encoding="utf-8",
            )
            self.assertEqual(
                validate_skill(skill),
                (False, "Invalid double-quoted YAML scalar"),
            )

    def test_canonical_block_description_preserves_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            skill_md.write_text(
                "---\nname: demo\ndescription: |\n"
                "  One.\n\n"
                "    Indented.\n"
                "  One after.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_skill_md(skill)[1],
                "One.\n\n  Indented.\nOne after.\n",
            )
            self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
            skill_md.write_text(
                "---\nname: demo\ndescription: |\n  Before.\n  ---\n  After.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(parse_skill_md(skill)[1], "Before.\n---\nAfter.\n")

    def test_validator_rejects_noncanonical_description_blocks_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            for header in (">", "|-", "|+", "|2", "| # comment"):
                with self.subTest(header=header):
                    skill_md.write_text(
                        f"---\nname: demo\ndescription: {header}\n  Text.\n---\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(
                        validate_skill(skill),
                        (False, "Description blocks must use exactly 'description: |'"),
                    )
            skill_md.write_text(
                "---\nname: demo\nname: duplicate\ndescription: Demo.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(
                validate_skill(skill),
                (False, "Duplicate frontmatter property: name"),
            )
            skill_md.write_text(
                "---\nname: demo\ndescription: |\n  Text.\n    \n---\n",
                encoding="utf-8",
            )
            self.assertEqual(
                validate_skill(skill),
                (False, "Blank description block lines must be empty"),
            )

    def test_block_description_blank_lines_cannot_bypass_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            for invalid, message in (
                ("x" * 1100, "Description is too long"),
                ("contains <angles>", "Description cannot contain angle brackets"),
            ):
                with self.subTest(message=message):
                    skill_md.write_text(
                        "---\nname: demo\ndescription: |\n"
                        "  Short first paragraph.\n\n"
                        f"  {invalid}\n---\n",
                        encoding="utf-8",
                    )
                    valid, error = validate_skill(skill)
                    self.assertFalse(valid)
                    self.assertIn(message, error)
                    self.assertIn(invalid, parse_skill_md(skill)[1])

    def test_validator_rejects_wrapped_plain_descriptions_without_truncating(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            for continuation in ("contains <angles>", "x" * 1100):
                with self.subTest(continuation=continuation[:20]):
                    skill_md.write_text(
                        "---\nname: demo\ndescription: Short description\n"
                        f"  {continuation}\n---\n",
                        encoding="utf-8",
                    )
                    expected = "Wrapped descriptions must use exactly 'description: |'"
                    self.assertEqual(validate_skill(skill), (False, expected))
                    with self.assertRaisesRegex(ValueError, "Wrapped descriptions"):
                        parse_skill_md(skill)

    def test_validator_accepts_utf8_bom_and_rejects_wrapped_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            skill_md = skill / "SKILL.md"
            skill_md.write_text(
                "\ufeff---\nname: demo\ndescription: Demo skill.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
            self.assertEqual(parse_skill_md(skill)[0], "demo")

            skill_md.write_bytes(
                b"---\r\nname: demo\r\ndescription: |\r\n  Windows lines.\r\n---\r\n"
            )
            self.assertEqual(validate_skill(skill), (True, "Skill is valid!"))
            self.assertEqual(parse_skill_md(skill)[1], "Windows lines.\n")

            skill_md.write_text(
                "---\nname: demo\n  continuation\ndescription: Demo skill.\n---\n",
                encoding="utf-8",
            )
            expected = "Names must use a single-line YAML scalar"
            self.assertEqual(validate_skill(skill), (False, expected))
            with self.assertRaisesRegex(ValueError, "single-line YAML scalar"):
                parse_skill_md(skill)

    def test_packager_excludes_development_roots_and_skill_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "demo"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            for directory in (skill / ".pytest_cache", skill / ".git"):
                directory.mkdir()
                (directory / "metadata").write_text("private", encoding="utf-8")
            for file_path in (
                skill / "evals" / "evals.json",
                skill / "tests" / "test_demo.py",
                skill / "skill-creator-results" / "run" / "results.json",
                skill / "logs" / "run.log",
                skill / "playwright-report" / "index.html",
                skill / "test-results" / "result.json",
                skill / "scripts" / "tests" / "helper.py",
                skill / "references" / "evals" / "example.json",
            ):
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("content", encoding="utf-8")
            (skill / "stale.skill").write_bytes(b"stale")
            output_dir = skill / "package-output"
            output_dir.mkdir()
            (output_dir / "private.txt").write_text("private", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                package = package_skill(skill, output_dir)
            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
            self.assertRegex(output.getvalue(), r"Skipped \d+ excluded file\(s\)\.")
            self.assertNotIn("Skipped:", output.getvalue())
            self.assertFalse(any(
                ".pytest_cache" in name
                or "/.git/" in name
                or name.startswith("demo/evals/")
                or name.startswith("demo/tests/")
                or name.startswith("demo/skill-creator-results/")
                or name.startswith("demo/logs/")
                or name.startswith("demo/playwright-report/")
                or name.startswith("demo/test-results/")
                or name.endswith(".log")
                or name.endswith(".skill")
                or name.startswith("demo/package-output/")
                for name in names
            ))
            self.assertIn("demo/scripts/tests/helper.py", names)
            self.assertIn("demo/references/evals/example.json", names)

    def test_failed_packaging_preserves_existing_archive_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "demo"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            destination = root / "demo.skill"
            destination.write_bytes(b"previous archive")
            with patch.object(zipfile.ZipFile, "write", side_effect=OSError("disk full")):
                self.assertIsNone(package_skill(skill, root))
            self.assertEqual(destination.read_bytes(), b"previous archive")
            self.assertEqual(set(root.iterdir()), {destination, skill})

    def test_packaging_into_skill_directory_excludes_temporary_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            skill = Path(temporary) / "demo"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8"
            )
            package = package_skill(skill, skill)
            with zipfile.ZipFile(package) as archive:
                self.assertEqual(archive.namelist(), ["demo/SKILL.md"])


if __name__ == "__main__":
    unittest.main()

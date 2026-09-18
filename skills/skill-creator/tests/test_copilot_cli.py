"""Copilot event contracts and optional real-CLI checks against an offline local fixture."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts.copilot_cli import copilot_command, copilot_version, response_text
from scripts.improve_description import _call_copilot, improve_description
from scripts.run_eval import run_single_query


def output_events(content):
    return "\n".join(json.dumps(event) for event in [
        {"type": "assistant.message", "data": {"content": content, "toolRequests": []}},
        {"type": "result", "exitCode": 0},
    ])


class CopilotContracts(unittest.TestCase):
    def test_command_uses_resolved_executable_and_restricted_tools(self):
        with patch("scripts.copilot_cli.shutil.which", return_value="copilot.exe"):
            command = copilot_command(None)
            self.assertEqual(command[0], "copilot.exe")
            self.assertEqual(command[command.index("--available-tools") + 1], "none")
            self.assertNotIn("--model", command)
            self.assertNotIn("--allow-all", command)
            command = copilot_command("chosen-model", ("skill", "view"))
            self.assertEqual(command[-2:], ["--model", "chosen-model"])
            self.assertNotIn("--allow-all-tools", command)
        with patch("scripts.copilot_cli.shutil.which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "Copilot CLI.*PATH"):
                copilot_command(None)

    def test_response_requires_final_success_and_content(self):
        self.assertEqual(response_text(output_events("A description")), "A description")
        bad_outputs = [
            ('{"type":"assistant.message","data":{"content":"partial"}}', "incomplete stream"),
            ('{"type":"session.error","data":{"message":"auth failure"}}', "auth failure"),
            (output_events("text").replace('"exitCode": 0', '"exitCode": 1'), "complete successfully"),
            (output_events(""), "no description text"),
            ("invalid JSON", "invalid JSONL"),
        ]
        for output, message in bad_outputs:
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                response_text(output)

    def test_version_probe_is_cached_and_nonfatal(self):
        copilot_version.cache_clear()
        result = subprocess.CompletedProcess([], 0, "Copilot CLI 1.2.3\n", "")
        with patch("scripts.copilot_cli.shutil.which", return_value="copilot.exe"), \
             patch("scripts.copilot_cli.subprocess.run", return_value=result) as run:
            self.assertEqual(copilot_version(), "Copilot CLI 1.2.3")
            self.assertEqual(copilot_version(), "Copilot CLI 1.2.3")
            run.assert_called_once()
        copilot_version.cache_clear()
        with patch("scripts.copilot_cli.shutil.which", return_value=None):
            self.assertIsNone(copilot_version())
        copilot_version.cache_clear()
        with patch("scripts.copilot_cli.shutil.which", return_value="copilot.exe"), \
             patch(
                 "scripts.copilot_cli.subprocess.run",
                 return_value=subprocess.CompletedProcess([], 0, " \n", ""),
             ):
            self.assertIsNone(copilot_version())
        copilot_version.cache_clear()

    def test_improver_pipes_large_utf8_prompts_without_tool_permissions(self):
        prompt = "caf\u00e9 " * 10000
        result = subprocess.CompletedProcess([], 0, output_events("Description"), "")
        with patch("scripts.copilot_cli.shutil.which", return_value="copilot"), \
             patch("scripts.improve_description.subprocess.run", return_value=result) as run:
            self.assertEqual(_call_copilot(prompt, None), "Description")
            args, kwargs = run.call_args
            self.assertNotIn(prompt, args[0])
            self.assertEqual(kwargs["input"], prompt)
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertNotIn("--allow-tool", args[0])
        with patch("scripts.copilot_cli.shutil.which", return_value="copilot"), \
             patch("scripts.improve_description.subprocess.run", return_value=subprocess.CompletedProcess([], 3, "", "auth failed")):
            with self.assertRaisesRegex(RuntimeError, "auth failed"):
                _call_copilot("prompt", None)

    def test_improved_description_is_not_empty_or_over_limit(self):
        scores = {"results": [], "summary": {"passed": 0, "total": 0}}
        for response in ("<new_description></new_description>", '<new_description>" "</new_description>'):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                log_dir = Path(directory)
                with patch("scripts.improve_description._call_copilot", return_value=response):
                    with self.assertRaisesRegex(RuntimeError, "empty skill description"):
                        improve_description(
                            "demo", "content", "old", scores, [], None, log_dir, 1
                        )
                transcript = json.loads(
                    (log_dir / "improve_iter_1.json").read_text(encoding="utf-8")
                )
                self.assertEqual(transcript["response"], response)
        with patch("scripts.improve_description._call_copilot", return_value="x" * 1025):
            with self.assertRaisesRegex(RuntimeError, "exceeds 1024"):
                improve_description("demo", "content", "old", scores, [], None)
        with patch("scripts.improve_description._call_copilot", side_effect=["x" * 1025, "<new_description>Shorter.</new_description>"]) as call:
            self.assertEqual(improve_description("demo", "content", "old", scores, [], None), "Shorter.")
            self.assertEqual(call.call_count, 2)
        with patch("scripts.improve_description._call_copilot", return_value="x" * 1024) as call:
            self.assertEqual(len(improve_description("demo", "content", "old", scores, [], None)), 1024)
            call.assert_called_once()
        with patch(
            "scripts.improve_description._call_copilot",
            side_effect=[
                "<new_description>Compare files with <500 lines.</new_description>",
                "<new_description>Compare files with fewer than 500 lines.</new_description>",
            ],
        ) as call:
            self.assertEqual(
                improve_description("demo", "content", "old", scores, [], None),
                "Compare files with fewer than 500 lines.",
            )
            self.assertIn("must not contain the angle-bracket", call.call_args_list[0].args[0])
            self.assertEqual(call.call_count, 2)
        with patch(
            "scripts.improve_description._call_copilot",
            return_value='<new_description>Use when the user says "deploy"</new_description>',
        ):
            self.assertEqual(
                improve_description("demo", "content", "old", scores, [], None),
                'Use when the user says "deploy"',
            )
        with patch(
            "scripts.improve_description._call_copilot",
            side_effect=[
                "<new_description>Use for <files>.</new_description>",
                "<new_description>Still <invalid>.</new_description>",
            ],
        ):
            with tempfile.TemporaryDirectory() as temporary:
                log_dir = Path(temporary)
                with self.assertRaisesRegex(RuntimeError, "still contains angle brackets"):
                    improve_description(
                        "demo", "content", "old", scores, [], None, log_dir, 1
                    )
                transcript = json.loads(
                    (log_dir / "improve_iter_1.json").read_text(encoding="utf-8")
                )
                self.assertIn("rewrite_prompt", transcript)
                self.assertEqual(
                    transcript["rewrite_response"],
                    "<new_description>Still <invalid>.</new_description>",
                )
        with patch(
            "scripts.improve_description._call_copilot",
            return_value="<new_description>Use when: the user asks.</new_description>",
        ) as call:
            self.assertEqual(
                improve_description("demo", "content", "old", scores, [], None),
                "Use when: the user asks.",
            )
            call.assert_called_once()

    def test_improver_keeps_history_outside_scores_and_does_not_repeat_current_description(self):
        scores = {
            "results": [{
                "query": "missed", "should_trigger": True, "pass": False,
                "triggers": 0, "runs": 3,
            }],
            "summary": {"passed": 0, "total": 1},
        }
        history = [{
            "description": "previous",
            "train_passed": 0,
            "train_total": 1,
            "train_results": scores["results"],
        }]
        with patch(
            "scripts.improve_description._call_copilot",
            return_value="<new_description>Improved.</new_description>",
        ) as call:
            improve_description("demo", "content", "current", scores, history, None)
        prompt = call.call_args.args[0]
        self.assertLess(prompt.index("</scores_summary>"), prompt.index("PREVIOUS ATTEMPTS"))
        self.assertEqual(prompt.count('Description: "previous"'), 1)
        self.assertEqual(prompt.count('"current"'), 1)


class LocalModelHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tools = [item["function"]["name"] for item in request.get("tools", [])]
        self.server.tools_seen.append(tools)
        trigger = self.server.trigger and len(self.server.tools_seen) == 1
        delta = {"role": "assistant", "content": "<new_description>Local fixture description.</new_description>"}
        if trigger:
            delta = {"role": "assistant", "content": None, "tool_calls": [{
                "index": 0, "id": "fixture-call", "type": "function",
                "function": {"name": "skill", "arguments": json.dumps({"skill": self.server.skill_name})},
            }]}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for content, finish in [(delta, None), ({}, "tool_calls" if trigger else "stop")]:
            payload = {"choices": [{"index": 0, "delta": content, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")


@unittest.skipUnless(shutil.which("copilot"), "Copilot CLI is not installed")
class InstalledCopilotTests(unittest.TestCase):
    def test_actual_executable_skill_discovery_events_and_tool_free_improvement(self):
        with tempfile.TemporaryDirectory(prefix="copilot-offline-test-") as temporary:
            root = Path(temporary)
            working = root / "work"
            working.mkdir()
            with HTTPServer(("127.0.0.1", 0), LocalModelHandler) as server:
                server.tools_seen = []
                server.trigger = True
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                environment = {key: value for key, value in os.environ.items()
                               if not key.startswith(("COPILOT_PROVIDER_", "OTEL_", "COPILOT_OTEL_"))
                               and key.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
                environment.update({
                    "COPILOT_HOME": str(root / "config"),
                    "COPILOT_OFFLINE": "true",
                    "COPILOT_PROVIDER_TYPE": "openai",
                    "COPILOT_PROVIDER_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "COPILOT_PROVIDER_WIRE_API": "completions",
                    "NO_PROXY": "*",
                })
                popen = subprocess.Popen

                def launch(command, **kwargs):
                    candidate_root = Path(command[command.index("--add-dir") + 1])
                    server.skill_name = next((candidate_root / ".github" / "skills").iterdir()).name
                    return popen(command, **kwargs)

                try:
                    with patch.dict(os.environ, environment, clear=True):
                        with patch("scripts.run_eval.subprocess.Popen", side_effect=launch):
                            self.assertTrue(run_single_query("Use the candidate skill.", "demo", "Local fixture.", 60, "fixture"))
                        self.assertEqual(set(server.tools_seen[0]), {"skill", "view"})
                        server.trigger = False
                        server.tools_seen = []
                        self.assertFalse(run_single_query("Answer without a tool.", "demo", "Local fixture.", 60, "fixture"))
                        server.tools_seen = []
                        self.assertIn("Local fixture description.", _call_copilot("Return a description.", "fixture", timeout=60))
                        self.assertTrue(server.tools_seen)
                        self.assertTrue(all(not tools for tools in server.tools_seen), server.tools_seen)
                finally:
                    server.shutdown()
                    thread.join()


if __name__ == "__main__":
    unittest.main()

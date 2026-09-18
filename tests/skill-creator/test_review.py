import contextlib
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import urlopen
from urllib.parse import urlparse


from skill_path import SKILL
from scripts import generate_review as review
from scripts.generate_report import generate_html as generate_report


class ReviewTests(unittest.TestCase):
    def test_large_outputs_are_referenced_without_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "large.bin"
            output.write_bytes(b"x" * (review.MAX_EMBED_BYTES + 1))
            embedded = review.embed_file(output)
            self.assertEqual(embedded["type"], "external")
            self.assertEqual(embedded["size_bytes"], review.MAX_EMBED_BYTES + 1)
            self.assertEqual(embedded["path"], str(output.resolve()))
            self.assertNotIn("data_uri", embedded)

    def test_total_embedding_budget_includes_json_escaping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("<" * 900_000, encoding="utf-8")
            second.write_text("x" * 5_200_000, encoding="utf-8")
            budget = [review.MAX_TOTAL_EMBED_BYTES]
            self.assertEqual(review.embed_file(first, budget)["type"], "text")
            self.assertEqual(review.embed_file(second, budget)["type"], "external")
            self.assertGreaterEqual(budget[0], 0)

    def test_nested_metadata_and_missing_ids_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluation = root / "eval-1"
            output = evaluation / "with_skill" / "run-1" / "outputs"
            output.mkdir(parents=True)
            (evaluation / "eval_metadata.json").write_text(json.dumps({"eval_id": 1, "prompt": "Nested prompt"}), encoding="utf-8")
            (root / "unlabelled" / "outputs").mkdir(parents=True)
            string_id = root / "eval-string" / "with_skill" / "outputs"
            string_id.mkdir(parents=True)
            (string_id.parent / "eval_metadata.json").write_text(
                json.dumps({"eval_id": "2", "prompt": "String ID"}), encoding="utf-8"
            )
            runs = review.find_runs(root)
            self.assertEqual(runs[0]["prompt"], "Nested prompt")
            self.assertEqual(runs[0]["eval_id"], 1)
            self.assertEqual(runs[1]["eval_id"], "2")
            self.assertIsNone(runs[2]["eval_id"])

    def test_nearest_metadata_id_is_preserved_while_prompt_comes_from_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluation = root / "eval-3"
            run = evaluation / "with_skill" / "run-1"
            (run / "outputs").mkdir(parents=True)
            (run / "eval_metadata.json").write_text(
                json.dumps({"eval_id": 7}), encoding="utf-8"
            )
            (evaluation / "eval_metadata.json").write_text(
                json.dumps({"eval_id": 3, "prompt": "Parent prompt"}),
                encoding="utf-8",
            )
            result = review.find_runs(root)[0]
            self.assertEqual(result["eval_id"], 7)
            self.assertEqual(result["prompt"], "Parent prompt")

    def test_parent_metadata_id_is_used_with_nearer_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluation = root / "eval-3"
            run = evaluation / "with_skill" / "run-1"
            (run / "outputs").mkdir(parents=True)
            (run / "eval_metadata.json").write_text(
                json.dumps({"prompt": "Run prompt"}), encoding="utf-8"
            )
            (evaluation / "eval_metadata.json").write_text(
                json.dumps({"eval_id": 3, "prompt": "Parent prompt"}),
                encoding="utf-8",
            )
            result = review.find_runs(root)[0]
            self.assertEqual(result["eval_id"], 3)
            self.assertEqual(result["prompt"], "Run prompt")

    def test_nested_output_files_use_relative_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "eval-1" / "with_skill" / "outputs"
            nested = outputs / "site" / "index.html"
            nested.parent.mkdir(parents=True)
            nested.write_text("<h1>Result</h1>", encoding="utf-8")
            run = review.find_runs(root)[0]
            self.assertEqual(run["outputs"][0]["name"], "site/index.html")
            self.assertEqual(run["outputs"][0]["content"], "<h1>Result</h1>")

    def test_malformed_metadata_and_grading_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "eval-1" / "with_skill"
            (run / "outputs").mkdir(parents=True)
            (run / "eval_metadata.json").write_text("[]", encoding="utf-8")
            (run / "grading.json").write_text('"invalid"', encoding="utf-8")
            with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                result = review.find_runs(root)[0]
            self.assertEqual(result["prompt"], "(No prompt found)")
            self.assertIsNone(result["grading"])
            self.assertIn("Invalid metadata", stderr.getvalue())
            self.assertIn("Invalid grading", stderr.getvalue())

    def test_invalid_metadata_types_use_transcript_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "eval-1" / "with_skill"
            (run / "outputs").mkdir(parents=True)
            (run / "eval_metadata.json").write_text(
                json.dumps({"eval_id": {"invalid": 1}, "prompt": {"invalid": 1}}),
                encoding="utf-8",
            )
            (run / "transcript.md").write_text(
                "## Eval Prompt\n\nRecovered prompt\n\n## Output\n",
                encoding="utf-8",
            )
            with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                result = review.find_runs(root)[0]
            self.assertEqual(result["prompt"], "Recovered prompt")
            self.assertIsNone(result["eval_id"])
            self.assertIn("prompt must be a string", stderr.getvalue())

    def test_embedded_text_cannot_end_the_data_script(self):
        data = review.generate_html([{"id": "example", "prompt": "</script><p>text", "outputs": []}], "Example")
        self.assertIn(r"\u003c/script>", data)
        self.assertNotIn("</script><p>text", data)
        self.assertIn('"server_mode": false', data)
        self.assertIn('"server_mode": true', review.generate_html([], "Example", server_mode=True))

    def test_optimization_report_without_holdout(self):
        data = {"history": [{"iteration": 1, "train_results": [], "test_results": None}]}
        self.assertIn("Not evaluated", generate_report(data))
        report = generate_report({"history": [], "test_size": None})
        self.assertIn("(training set)", report)
        self.assertIn("<strong>Test queries:</strong> ?", report)

        report = generate_report({
            "history": [{
                "iteration": 1,
                "train_passed": 0,
                "train_results": [],
                "test_passed": 1,
                "test_results": [{
                    "eval_id": 1, "query": "q", "should_trigger": True,
                    "triggers": 1, "runs": 1, "pass": True,
                }],
            }],
        })
        self.assertIn("(held-out test set)", report)

    def test_failed_optimization_report_shows_status_and_escaped_error(self):
        report = generate_report({
            "history": [],
            "exit_reason": "failed: CLI error",
            "error": "model <unavailable>",
        })
        self.assertIn("<strong>Exit reason:</strong> failed: CLI error", report)
        self.assertIn(
            '<p class="error" role="alert"><strong>Run failed:</strong> model &lt;unavailable&gt;</p>',
            report,
        )

    def test_invalid_benchmark_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.json"
            for content, message in (
                ("not json", "Could not read benchmark"),
                ("[]", "must contain an object"),
            ):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    with mock.patch.object(
                        sys, "stderr", new_callable=io.StringIO
                    ) as stderr:
                        self.assertIsNone(review.load_benchmark(path))
                    self.assertIn(message, stderr.getvalue())
            path.unlink()
            with mock.patch.object(
                sys, "stderr", new_callable=io.StringIO
            ) as stderr:
                self.assertIsNone(review.load_benchmark(path))
            self.assertIn("benchmark file not found", stderr.getvalue())

    def test_optimization_report_discloses_holdout_selection_bias(self):
        report = generate_report({
            "history": [],
            "best_score": "2/3",
            "test_size": 3,
        })
        self.assertIn("optimistically biased model-selection estimate", report)
        self.assertIn("Best query score:</strong> 2/3 queries passed (held-out test set)", report)
        self.assertIn(
            "Train and Test run scores in the iteration table count correct individual runs",
            report,
        )

    def test_optimization_report_uses_same_best_iteration_tiebreak(self):
        def attempt(iteration, description, triggers):
            result = {
                "eval_id": 1,
                "query": "query",
                "should_trigger": True,
                "triggers": triggers,
                "runs": 3,
                "pass": True,
            }
            return {
                "iteration": iteration,
                "description": description,
                "train_passed": 1,
                "train_total": 1,
                "train_results": [result],
                "test_passed": 1,
                "test_total": 1,
                "test_results": [result],
            }

        report = generate_report({
            "history": [attempt(1, "first", 2), attempt(2, "second", 3)],
            "test_size": 1,
        })
        self.assertIn("Iteration 2 (Best)", report)
        self.assertNotIn("Iteration 1 (Best)", report)

    def test_auto_refresh_pauses_only_for_refresh_controls_or_open_descriptions(self):
        report = generate_report({"history": []}, auto_refresh=True)
        self.assertIn("refresh-controls :focus, .table-container:focus-within", report)
        self.assertIn("Screen-reader browse-mode reading cannot be detected", report)
        self.assertNotIn("document.activeElement === document.body", report)

    def test_occupied_port_selects_another_without_stopping_existing_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            with review.ThreadingHTTPServer(("127.0.0.1", 0), review.BaseHTTPRequestHandler) as occupied:
                port = occupied.server_port
                with mock.patch.object(sys, "argv", ["generate_review.py", str(root), "--port", str(port), "--open"]), \
                     mock.patch.object(review.webbrowser, "open") as opened, \
                     mock.patch.object(review.ThreadingHTTPServer, "serve_forever"), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    review.main()
                self.assertNotEqual(urlparse(opened.call_args.args[0]).port, port)
                self.assertEqual(occupied.socket.getsockname()[1], port)

    def test_failed_feedback_replacement_keeps_previous_save(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "feedback.json"
            destination.write_text('{"reviews": [], "status": "complete"}', encoding="utf-8")
            body = b'{"reviews": [], "status": "in_progress"}'
            handler = object.__new__(review.ReviewHandler)
            handler.path = "/api/feedback"
            handler.workspace = Path(directory)
            handler.feedback_path = destination
            handler.server = mock.Mock(server_port=3117)
            handler.headers = {
                "Content-Length": str(len(body)),
                "Host": "localhost:3117",
                "Origin": "http://localhost:3117",
            }
            handler.rfile = io.BytesIO(body)
            handler.wfile = io.BytesIO()
            handler.send_response = mock.Mock()
            handler.send_header = mock.Mock()
            handler.end_headers = mock.Mock()
            with mock.patch.object(Path, "replace", side_effect=OSError("Disk error")):
                handler.do_POST()
            handler.send_response.assert_called_once_with(500)
            self.assertEqual(json.loads(destination.read_text())["status"], "complete")
            self.assertIn("Disk error", handler.wfile.getvalue().decode())
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_feedback_rejects_cross_origin_posts(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "feedback.json"
            destination.write_text('{"status":"complete"}', encoding="utf-8")
            handler = object.__new__(review.ReviewHandler)
            handler.path = "/api/feedback"
            handler.feedback_path = destination
            handler.server = mock.Mock(server_port=3117)
            handler.headers = {
                "Content-Length": "2",
                "Host": "localhost:3117",
                "Origin": "https://example.invalid",
            }
            handler.rfile = io.BytesIO(b"{}")
            handler.send_error = mock.Mock()
            handler.do_POST()
            handler.send_error.assert_called_once_with(
                403, "Feedback saves are accepted only from this review page"
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), '{"status":"complete"}')

    def test_feedback_rejects_posts_without_origin(self):
        handler = object.__new__(review.ReviewHandler)
        handler.path = "/api/feedback"
        handler.feedback_path = Path("unused")
        handler.server = mock.Mock(server_port=3117)
        handler.headers = {"Content-Length": "2", "Host": "localhost:3117"}
        handler.rfile = io.BytesIO(b"{}")
        handler.send_error = mock.Mock()
        handler.do_POST()
        handler.send_error.assert_called_once_with(
            403, "Feedback saves are accepted only from this review page"
        )

    def test_get_rejects_foreign_host(self):
        handler = object.__new__(review.ReviewHandler)
        handler.path = "/"
        handler.server = mock.Mock(server_port=3117)
        handler.headers = {"Host": "example.invalid"}
        handler.send_error = mock.Mock()
        handler.do_GET()
        handler.send_error.assert_called_once_with(
            403, "Review data is available only from this review page"
        )

    def test_idle_connection_does_not_block_other_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "eval-1" / "with_skill"
            (run / "outputs").mkdir(parents=True)
            handler = review.partial(
                review.ReviewHandler, root, "Example", root / "feedback.json",
                {}, None, review.MAX_TOTAL_EMBED_BYTES,
            )
            with review.ReviewServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                idle = socket.create_connection(server.server_address, timeout=1)
                try:
                    with urlopen(f"http://localhost:{server.server_port}", timeout=2) as response:
                        self.assertEqual(response.status, 200)
                finally:
                    idle.close()
                    server.shutdown()
                    thread.join(timeout=2)

    def test_malformed_previous_feedback_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "feedback.json").write_text(
                json.dumps({"reviews": ["invalid", {"run_id": "run", "feedback": 5}]}),
                encoding="utf-8",
            )
            self.assertEqual(review.load_previous_iteration(root), {})

    def test_static_output_uses_atomic_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            destination = root / "review.html"
            with mock.patch.object(sys, "argv", [
                "generate_review.py", str(root), "--static", str(destination),
            ]), mock.patch.object(review, "atomic_write_text") as write, \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                review.main()
            write.assert_called_once()
            self.assertEqual(write.call_args.args[0], destination)

    def test_feedback_rejects_malformed_content_length_without_resetting_connection(self):
        handler = object.__new__(review.ReviewHandler)
        handler.path = "/api/feedback"
        handler.feedback_path = Path("unused")
        handler.server = mock.Mock(server_port=3117)
        handler.headers = {
            "Content-Length": "invalid",
            "Host": "localhost:3117",
            "Origin": "http://localhost:3117",
        }
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.do_POST()
        handler.send_response.assert_called_once_with(400)
        self.assertIn("invalid literal", handler.wfile.getvalue().decode())

    def test_feedback_rejects_malformed_review_entries(self):
        body = b'{"reviews":[{"run_id":"run","feedback":5}]}'
        handler = object.__new__(review.ReviewHandler)
        handler.path = "/api/feedback"
        handler.workspace = Path("unused-workspace")
        handler.feedback_path = Path("unused")
        handler.server = mock.Mock(server_port=3117)
        handler.headers = {
            "Content-Length": str(len(body)),
            "Host": "localhost:3117",
            "Origin": "http://localhost:3117",
        }
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.do_POST()
        handler.send_response.assert_called_once_with(400)
        self.assertIn("string run_id and feedback", handler.wfile.getvalue().decode())

    def feedback_handler(self, body: bytes, destination: Path, length: str | None = None):
        handler = object.__new__(review.ReviewHandler)
        handler.path = "/api/feedback"
        handler.workspace = destination.parent
        handler.feedback_path = destination
        handler.server = mock.Mock(server_port=3117)
        handler.headers = {
            "Content-Length": length if length is not None else str(len(body)),
            "Host": "localhost:3117",
            "Origin": "http://localhost:3117",
        }
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        return handler

    def test_server_does_not_open_browser_without_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            stdout = io.StringIO()
            with mock.patch.object(sys, "argv", ["generate_review.py", str(root), "--port", "0"]), \
                 mock.patch.object(review.webbrowser, "open") as opened, \
                 mock.patch.object(review.ThreadingHTTPServer, "serve_forever"), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                review.main()
            opened.assert_not_called()
            self.assertRegex(stdout.getvalue(), r"URL:\s+http://localhost:\d+")

    def test_static_output_prints_path_and_opens_only_with_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            destination = root / "review.html"
            for extra, expected_calls in (([], 0), (["--open"], 1)):
                stdout = io.StringIO()
                with self.subTest(extra=extra), mock.patch.object(sys, "argv", [
                    "generate_review.py", str(root), "--static", str(destination), *extra,
                ]), mock.patch.object(review.webbrowser, "open") as opened, \
                     contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit):
                    review.main()
                self.assertEqual(opened.call_count, expected_calls)
                self.assertIn(str(destination.resolve()), stdout.getvalue())
                self.assertIn(destination.resolve().as_uri(), stdout.getvalue())

    def test_port_must_be_in_range(self):
        for port in ("-1", "65536", "http"):
            with self.subTest(port=port), \
                 mock.patch.object(sys, "argv", ["generate_review.py", ".", "--port", port]), \
                 contextlib.redirect_stderr(io.StringIO()) as stderr, \
                 self.assertRaises(SystemExit) as raised:
                review.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("port", stderr.getvalue())
        self.assertEqual(review.port_number("0"), 0)
        self.assertEqual(review.port_number("65535"), 65535)

    def test_feedback_rejects_oversized_body_without_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "feedback.json"
            handler = self.feedback_handler(b"{}", destination, str(review.MAX_FEEDBACK_BYTES + 1))
            handler.rfile = mock.Mock()
            handler.do_POST()
            handler.send_response.assert_called_once_with(413)
            handler.rfile.read.assert_not_called()
            self.assertFalse(destination.exists())

    def test_feedback_rejects_bad_fields_and_types(self):
        bad_payloads = [
            {"reviews": [], "status": "done"},
            {"reviews": [], "extra": 1},
            {"reviews": [{"run_id": "", "feedback": "x"}]},
            {"reviews": [{"run_id": "r", "feedback": "x", "timestamp": 5}]},
            {"reviews": [{"run_id": "r", "feedback": "x", "score": 1}]},
            {"reviews": "not a list"},
            ["not", "an", "object"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "feedback.json"
            (Path(directory) / "r" / "outputs").mkdir(parents=True)
            for payload in bad_payloads:
                with self.subTest(payload=payload):
                    handler = self.feedback_handler(json.dumps(payload).encode(), destination)
                    handler.do_POST()
                    handler.send_response.assert_called_once_with(400)
                    self.assertFalse(destination.exists())
            good = {"reviews": [{"run_id": "r", "feedback": "ok", "timestamp": "t"}], "status": "complete"}
            handler = self.feedback_handler(json.dumps(good).encode(), destination)
            handler.do_POST()
            handler.send_response.assert_called_once_with(200)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), good)

    def test_flat_spec_feedback_map_is_loaded_for_previous_iteration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for config in ("with_skill", "without_skill"):
                (root / "eval-chart" / config / "outputs").mkdir(parents=True)
            (root / "eval-chart" / "eval_metadata.json").write_text(
                json.dumps({"eval_id": 1, "prompt": "p"}), encoding="utf-8"
            )
            (root / "feedback.json").write_text(json.dumps({
                "eval-chart": "Missing axis labels.",
                "eval-gone": "Orphan feedback.",
                "eval-empty": "",
            }), encoding="utf-8")
            previous = review.load_previous_iteration(root)
            self.assertEqual(previous["eval-chart-with_skill"]["feedback"], "Missing axis labels.")
            self.assertEqual(previous["eval-chart-without_skill"]["feedback"], "Missing axis labels.")
            self.assertEqual(previous["eval-gone"]["feedback"], "Orphan feedback.")
            self.assertNotIn("eval-empty", previous)
            self.assertEqual(review.find_runs(root)[0]["eval_dir"], "eval-chart")

    def test_symlinked_outputs_are_not_embedded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "secret.txt"
            secret.write_text("TOP SECRET", encoding="utf-8")
            outputs = root / "eval-1" / "with_skill" / "outputs"
            outputs.mkdir(parents=True)
            (outputs / "real.txt").write_text("visible", encoding="utf-8")
            link = outputs / "link.txt"
            try:
                link.symlink_to(secret)
            except OSError as error:
                self.skipTest(f"Symlinks unavailable: {error}")
            self.assertEqual(review.embed_file(link)["type"], "error")
            with mock.patch.object(sys, "stderr", new_callable=io.StringIO):
                run = review.find_runs(root)[0]
            self.assertEqual([output["name"] for output in run["outputs"]], ["real.txt"])
            self.assertNotIn("TOP SECRET", json.dumps(run))

    def test_server_binds_loopback_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            with mock.patch.object(sys, "argv", ["generate_review.py", str(root), "--port", "0"]), \
                 mock.patch.object(review, "ReviewServer", wraps=review.ReviewServer) as server, \
                 mock.patch.object(review.ThreadingHTTPServer, "serve_forever"), \
                 contextlib.redirect_stdout(io.StringIO()):
                review.main()
            self.assertEqual(server.call_args.args[0][0], "127.0.0.1")

    def test_viewer_reads_spec_and_legacy_grading_fields(self):
        template = (SKILL / "assets" / "viewer.html").read_text(encoding="utf-8")
        self.assertIn("grading.assertion_results", template)
        self.assertIn("grading.expectations", template)
        self.assertIn("run.assertion_results", template)
        self.assertIn("Content-Security-Policy", template)

    def test_user_notes_are_attached_to_the_run_not_listed_as_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "eval-1" / "with_skill" / "outputs"
            outputs.mkdir(parents=True)
            (outputs / "answer.txt").write_text("Answer", encoding="utf-8")
            (outputs / "user_notes.md").write_text("<b>Unsure</b> about 2023 data", encoding="utf-8")
            (root / "eval-2" / "with_skill" / "outputs").mkdir(parents=True)
            runs = review.find_runs(root)
            self.assertEqual([output["name"] for output in runs[0]["outputs"]], ["answer.txt"])
            self.assertEqual(runs[0]["user_notes"]["type"], "text")
            self.assertEqual(runs[0]["user_notes"]["content"], "<b>Unsure</b> about 2023 data")
            self.assertIsNone(runs[1]["user_notes"])
            html = review.generate_html(runs, "Example")
            self.assertIn("\\u003cb>Unsure", html)
            self.assertNotIn("<b>Unsure", html)

    def test_feedback_rejects_unknown_run_ids_but_keeps_saved_orphans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            destination = root / "feedback.json"
            destination.write_text(json.dumps({"reviews": [
                {"run_id": "removed-run", "feedback": "Keep this review"},
            ]}), encoding="utf-8")
            unknown = {"reviews": [{"run_id": "eval-9-with_skill", "feedback": "x"}]}
            handler = self.feedback_handler(json.dumps(unknown).encode(), destination)
            handler.do_POST()
            handler.send_response.assert_called_once_with(400)
            self.assertIn("Unknown run_id", json.loads(handler.wfile.getvalue())["error"])
            self.assertIn("removed-run", destination.read_text(encoding="utf-8"))
            good = {"reviews": [
                {"run_id": "eval-1-with_skill", "feedback": "ok"},
                {"run_id": "removed-run", "feedback": "Keep this review"},
            ], "status": "complete"}
            handler = self.feedback_handler(json.dumps(good).encode(), destination)
            handler.do_POST()
            handler.send_response.assert_called_once_with(200)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), good)

    def test_flat_feedback_keys_remain_savable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            destination = root / "feedback.json"
            destination.write_text(json.dumps({"eval-gone": "Flat orphan"}), encoding="utf-8")
            body = {"reviews": [{"run_id": "eval-gone", "feedback": "Flat orphan"}]}
            handler = self.feedback_handler(json.dumps(body).encode(), destination)
            handler.do_POST()
            handler.send_response.assert_called_once_with(200)

    def test_live_api_errors_are_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval-1" / "with_skill" / "outputs").mkdir(parents=True)
            handler = review.partial(
                review.ReviewHandler, root, "Example", root / "feedback.json",
                {}, None, review.MAX_TOTAL_EMBED_BYTES,
            )
            with review.ReviewServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                port = server.server_port
                origin = f"http://localhost:{port}"

                def request(method, path, body=b"", headers=None):
                    import http.client
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    try:
                        sent = {"Host": f"localhost:{port}", "Origin": origin, **(headers or {})}
                        connection.putrequest(method, path, skip_host=True)
                        for name, value in sent.items():
                            if value is not None:
                                connection.putheader(name, value)
                        if "Content-Length" not in sent:
                            connection.putheader("Content-Length", str(len(body)))
                        connection.endheaders(body)
                        response = connection.getresponse()
                        return response.status, response.getheader("Content-Type"), response.read()
                    finally:
                        connection.close()

                valid = json.dumps({"reviews": [{"run_id": "eval-1-with_skill", "feedback": "ok"}]}).encode()
                cases = [
                    ("GET", "/api/feedback", b"", {"Host": "example.invalid"}, 403),
                    ("POST", "/api/feedback", valid, {"Origin": None}, 403),
                    ("POST", "/api/feedback", valid, {"Origin": "http://example.invalid"}, 403),
                    ("GET", "/api/unknown", b"", None, 404),
                    ("POST", "/api/unknown", valid, None, 404),
                    ("PUT", "/api/feedback", valid, None, 501),
                    ("POST", "/api/feedback", b"{", None, 400),
                    ("POST", "/api/feedback", json.dumps({"reviews": [
                        {"run_id": "not-a-run", "feedback": "x"},
                    ]}).encode(), None, 400),
                    # Declare an oversized body without sending it; the server rejects it from
                    # the header, and streaming 1 MB into a closed socket races on Windows.
                    ("POST", "/api/feedback", b"",
                     {"Content-Length": str(review.MAX_FEEDBACK_BYTES + 1)}, 413),
                ]
                try:
                    for method, path, body, headers, expected in cases:
                        with self.subTest(method=method, path=path, status=expected, headers=headers):
                            status, content_type, payload = request(method, path, body, headers)
                            self.assertEqual(status, expected)
                            self.assertEqual(content_type, "application/json")
                            self.assertIsInstance(json.loads(payload)["error"], str)
                    status, content_type, payload = request("POST", "/api/feedback", valid)
                    self.assertEqual((status, json.loads(payload)), (200, {"ok": True}))
                    status, content_type, _ = request("GET", "/missing")
                    self.assertEqual(status, 404)
                    self.assertIn("text/html", content_type)
                finally:
                    server.shutdown()
                    thread.join(timeout=2)


class PrepareEvalReviewTests(unittest.TestCase):
    def setUp(self):
        from scripts import prepare_eval_review
        self.module = prepare_eval_review
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.skill = self.root / "demo-skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Handles <b>bold</b> & caf\u00e9 requests.\n---\n\nBody\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.directory.cleanup()

    def run_main(self, eval_set, *extra):
        eval_path = self.root / "eval_set.json"
        eval_path.write_text(json.dumps(eval_set), encoding="utf-8")
        output = self.root / "out" / "review.html"
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", [
            "prepare_eval_review", "--eval-set", str(eval_path),
            "--skill-path", str(self.skill), "--output", str(output), *extra,
        ]), mock.patch.object(self.module.webbrowser, "open") as opened, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                self.module.main()
                code = 0
            except SystemExit as error:
                code = error.code
        return code, output, stdout.getvalue(), stderr.getvalue(), opened

    def test_hostile_queries_cannot_end_script_and_text_is_escaped(self):
        hostile = '</script><img src=x onerror=alert(1)> & \u2028 __SKILL_NAME_PLACEHOLDER__'
        code, output, stdout, _, opened = self.run_main([{"query": hostile, "should_trigger": True}])
        self.assertEqual(code, 0)
        opened.assert_not_called()
        self.assertEqual(stdout.strip(), str(output.resolve()))
        page = output.read_text(encoding="utf-8")
        self.assertNotIn("</script><img", page)
        self.assertNotIn("\u2028", page)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertIn("\\u0026", page)
        self.assertIn("__SKILL_NAME_PLACEHOLDER__", page)
        self.assertNotIn("__EVAL_DATA_PLACEHOLDER__", page)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; caf\u00e9", page)
        self.assertIn("Eval Set Review - demo-skill", page)
        start = page.index("const EVAL_DATA = ") + len("const EVAL_DATA = ")
        data = json.loads(page[start:page.index(";\n", start)])
        self.assertEqual(data, [{"query": hostile, "should_trigger": True}])

    def test_open_flag_opens_browser(self):
        code, output, _, _, opened = self.run_main([{"query": "q", "should_trigger": False}], "--open")
        self.assertEqual(code, 0)
        opened.assert_called_once_with(output.resolve().as_uri())

    def test_invalid_eval_sets_are_rejected(self):
        for eval_set in (
            [],
            {"query": "q", "should_trigger": True},
            [{"query": "q", "should_trigger": "true"}],
            [{"query": "  ", "should_trigger": True}],
            ["q"],
        ):
            with self.subTest(eval_set=eval_set):
                code, output, _, stderr, _ = self.run_main(eval_set)
                self.assertEqual(code, 1)
                self.assertIn("invalid eval set", stderr)
                self.assertFalse(output.exists())

    def test_missing_skill_md_is_reported(self):
        (self.skill / "SKILL.md").unlink()
        code, _, _, stderr, _ = self.run_main([{"query": "q", "should_trigger": True}])
        self.assertEqual(code, 1)
        self.assertIn("SKILL.md", stderr)


if __name__ == "__main__":
    unittest.main()

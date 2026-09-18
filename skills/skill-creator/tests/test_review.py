import importlib.util
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


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
spec = importlib.util.spec_from_file_location("review", SKILL / "eval-viewer" / "generate_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
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
                with mock.patch.object(sys, "argv", ["generate_review.py", str(root), "--port", str(port)]), \
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


if __name__ == "__main__":
    unittest.main()

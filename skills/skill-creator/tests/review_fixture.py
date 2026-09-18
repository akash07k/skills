"""Local browser-test fixtures; no model calls or external services."""

import argparse
import html
import importlib.util
import json
import sys
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
from scripts.generate_report import generate_html as generate_report

spec = importlib.util.spec_from_file_location("generate_review", SKILL / "eval-viewer" / "generate_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def create_fixture(root: Path) -> None:
    grading = {
        "summary": {"passed": 1, "failed": 1, "total": 2, "pass_rate": 0.5},
        "expectations": [
            {"text": "Has a heading", "passed": True, "evidence": "A heading is present."},
            {"text": "Has all rows", "passed": False, "evidence": "The last row is missing."},
        ],
    }
    runs = []
    for index, config in enumerate(["with_skill", "without_skill"]):
        directory = root / "workspace" / "eval-1" / config
        (directory / "outputs").mkdir(parents=True, exist_ok=True)
        (directory / "outputs" / "answer.txt").write_text("Output including </script> text.\nSecond line.", encoding="utf-8")
        (directory / "eval_metadata.json").write_text(json.dumps({"eval_id": 1, "prompt": f"Prompt for {config}"}), encoding="utf-8")
        (directory / "grading.json").write_text(json.dumps(grading), encoding="utf-8")
        runs.append({
            "eval_id": 1, "eval_name": "Example evaluation", "configuration": config, "run_number": 1,
            "result": {"pass_rate": 0.5, "passed": 1, "total": 2, "time_seconds": 1, "errors": 0},
            "expectations": grading["expectations"],
        })
    stat = {"mean": 0.5, "stddev": 0}
    benchmark = {
        "metadata": {"skill_name": "Example", "evals_run": [1], "runs_per_configuration": 1},
        "run_summary": {
            "with_skill": {
                "pass_rate": stat,
                "time_seconds": {"mean": 2, "stddev": 0},
                "tokens": {"mean": 8, "stddev": 0},
            },
            "without_skill": {
                "pass_rate": stat,
                "time_seconds": {"mean": 1, "stddev": 0},
                "tokens": {"mean": 4, "stddev": 0},
            },
            "delta": {"pass_rate": "+0%", "time_seconds": "+1.0", "tokens": "+4"},
        },
        "runs": runs, "notes": ["Example benchmark note."],
    }
    (root / "benchmark.json").write_text(json.dumps(benchmark), encoding="utf-8")
    discovered = review.find_runs(root / "workspace")
    previous = {discovered[0]["id"]: {"feedback": "Earlier feedback", "outputs": [{"name": "old.txt", "type": "text", "content": "Previous answer"}]}}
    (root / "previous.json").write_text(json.dumps(previous), encoding="utf-8")
    (root / "static.html").write_text(review.generate_html(discovered, "Example", previous, benchmark), encoding="utf-8")
    single_benchmark = {
        "metadata": {"skill_name": "Example", "evals_run": [1], "runs_per_configuration": 1},
        "run_summary": {"with_skill": {"pass_rate": stat}},
        "runs": [runs[0]],
        "notes": [],
    }
    (root / "single.html").write_text(
        review.generate_html([discovered[0]], "Example", benchmark=single_benchmark),
        encoding="utf-8",
    )
    three_benchmark = {
        "metadata": {"skill_name": "Example", "evals_run": [1], "runs_per_configuration": 1},
        "run_summary": {
            "with_skill": {"pass_rate": stat},
            "old_skill": {"pass_rate": {"mean": 0.4, "stddev": 0}},
            "without_skill": {"pass_rate": stat},
            "delta": {"pass_rate": "+10%"},
        },
        "runs": runs,
        "notes": [],
    }
    (root / "three.html").write_text(
        review.generate_html(discovered, "Example", benchmark=three_benchmark),
        encoding="utf-8",
    )
    unsafe_value = '<img src=x onerror="document.body.dataset.injected=\'yes\'">'
    escaped_benchmark = {
        "metadata": {
            "skill_name": "Example",
            "evals_run": [1],
            "runs_per_configuration": {unsafe_value: {"<eval>": 1}, "baseline": 1},
        },
        "run_summary": {
            unsafe_value: {"pass_rate": stat},
            "baseline": {"pass_rate": stat},
            "delta": {"pass_rate": unsafe_value},
        },
        "runs": [dict(runs[0], configuration=unsafe_value, run_number=unsafe_value)],
        "notes": [],
    }
    (root / "escaped.html").write_text(
        review.generate_html([discovered[0]], "Example", benchmark=escaped_benchmark),
        encoding="utf-8",
    )
    malformed_benchmark = {
        "metadata": {"skill_name": "Example", "evals_run": 3, "runs_per_configuration": 1},
        "run_summary": {"with_skill": {"pass_rate": 0.8, "time_seconds": 42.0}},
        "runs": [{
            "eval_id": 1,
            "configuration": "with_skill",
            "run_number": 1,
            "result": {"passed": 2, "total": 3},
        }],
        "notes": "not a list",
    }
    (root / "malformed-benchmark.html").write_text(
        review.generate_html([discovered[0]], "Example", benchmark=malformed_benchmark),
        encoding="utf-8",
    )
    (root / "benchmark-error.html").write_text(
        review.generate_html(discovered, "Example", benchmark=[], server_mode=True),
        encoding="utf-8",
    )
    hostile_grading = {
        "summary": {
            "passed": unsafe_value,
            "failed": unsafe_value,
            "total": unsafe_value,
            "pass_rate": 0.5,
        },
        "expectations": {"text": unsafe_value, "passed": True},
    }
    hostile_run = dict(discovered[0], grading=hostile_grading)
    (root / "hostile-grades.html").write_text(
        review.generate_html([hostile_run], "Hostile grades"),
        encoding="utf-8",
    )
    (root / "empty.html").write_text(review.generate_html([], "Empty"), encoding="utf-8")
    media = [
        {"name": "image.svg", "type": "image", "data_uri": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E"},
        {"name": "document.pdf", "type": "pdf", "data_uri": "data:application/pdf;base64,JVBERi0xLjQKJSVFT0Y="},
        {"name": "data.xlsx", "type": "xlsx", "data_b64": "dGVzdA=="},
        {"name": "archive.bin", "type": "binary", "data_uri": "data:application/octet-stream;base64,dGVzdA=="},
        {"name": "large.bin", "type": "external", "path": r"C:\workspace\large.bin", "size_bytes": 6291456},
        {"name": "unreadable.txt", "type": "error", "content": "Error reading file"},
    ]
    media_run = dict(discovered[0], outputs=media)
    (root / "media.html").write_text(review.generate_html([media_run], "Media examples", {media_run["id"]: {"outputs": media}}), encoding="utf-8")
    hostile_query = '</script><img src=x onerror="document.body.dataset.injected=\'yes\'">'
    queries = [{"query": hostile_query, "should_trigger": True}, {"query": hostile_query, "should_trigger": False}]
    editor = (SKILL / "assets" / "eval_review.html").read_text(encoding="utf-8")
    editor = editor.replace("__EVAL_DATA_PLACEHOLDER__", json.dumps(queries).replace("<", "\\u003c"))
    editor = editor.replace("__SKILL_NAME_PLACEHOLDER__", html.escape("Example"))
    editor = editor.replace("__SKILL_DESCRIPTION_PLACEHOLDER__", html.escape("Example description"))
    (root / "editor.html").write_text(editor, encoding="utf-8")
    results = [
        {"eval_id": 0, "query": "Repeated query", "should_trigger": True, "pass": True, "triggers": 3, "runs": 3},
        {"eval_id": 1, "query": "Repeated query", "should_trigger": False, "pass": False, "triggers": 2, "runs": 3},
    ]
    report = {"history": [{"iteration": 1, "description": "A full description.", "train_passed": 1, "train_results": results, "test_results": results}]}
    (root / "report.html").write_text(generate_report(report, auto_refresh=True, skill_name="Example"), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if not args.serve:
        create_fixture(args.root)
    else:
        handler = partial(
            review.ReviewHandler, args.root / "workspace", "Example",
            args.root / "workspace" / "feedback.json",
            json.loads((args.root / "previous.json").read_text(encoding="utf-8")),
            args.root / "benchmark.json",
            review.MAX_TOTAL_EMBED_BYTES,
        )
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}"}), flush=True)
            server.serve_forever()

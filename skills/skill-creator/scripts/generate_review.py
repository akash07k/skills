#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
r"""Generate and serve a review page for eval results.

Reads the workspace directory, discovers runs (directories with outputs/),
embeds output data up to a safe size into a self-contained HTML page, and
serves it via a tiny HTTP server. Feedback auto-saves to feedback.json.

Usage:
    python scripts/generate_review.py <workspace-path> [--port PORT] [--skill-name NAME] [--open]
    python scripts/generate_review.py <workspace-path> --previous-workspace <previous-iteration>
    python scripts/generate_review.py <workspace-path> --static <review.html>

The server listens on 127.0.0.1 only and prints its URL. The browser opens
only when --open is passed.

No dependencies beyond the Python stdlib are required.
"""

import argparse
import base64
import errno
import json
import mimetypes
import os
import re
import sys
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

if sys.version_info < (3, 13):
    sys.exit("skill-creator scripts require Python 3.13 or later.")

if not __package__:
    # Allow `python <skill>/scripts/<name>.py` from any working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import atomic_write_text, ensure_utf8_stdio, eval_sort_key

# Files to exclude from output listings
METADATA_FILES = {"transcript.md", "user_notes.md", "metrics.json"}

# Extensions we render as inline text
TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".yaml", ".yml", ".xml", ".html", ".css", ".sh", ".rb", ".go", ".rs",
    ".java", ".c", ".cpp", ".h", ".hpp", ".sql", ".r", ".toml",
}

# Extensions we render as inline images
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
MAX_EMBED_BYTES = 5 * 1024 * 1024
MAX_TOTAL_EMBED_BYTES = 10 * 1024 * 1024
MAX_FEEDBACK_BYTES = 1024 * 1024
FEEDBACK_STATUSES = {"in_progress", "complete"}

# MIME type overrides for common types
MIME_OVERRIDES = {
    ".svg": "image/svg+xml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def get_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def load_benchmark(path: Path) -> dict | None:
    """Load benchmark data or report why it is unavailable."""
    if not path.exists():
        print(f"Warning: benchmark file not found: {path}", file=sys.stderr)
        return None
    try:
        benchmark = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(benchmark, dict):
            raise ValueError("benchmark.json must contain an object")
        return benchmark
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"Warning: Could not read benchmark from {path}: {error}", file=sys.stderr)
        return None


def find_run_dirs(workspace: Path) -> list[Path]:
    """Recursively find directories that contain an outputs/ subdirectory."""
    run_dirs: list[Path] = []
    skip = {"node_modules", ".git", "__pycache__", "skill", "inputs"}
    for current_path, directories, _ in os.walk(workspace):
        directories[:] = sorted(name for name in directories if name not in skip)
        if "outputs" not in directories:
            continue
        run_dirs.append(Path(current_path))
        directories.clear()
    return run_dirs


def run_id_for(root: Path, run_dir: Path) -> str:
    return str(run_dir.relative_to(root)).replace("/", "-").replace("\\", "-")


def find_runs(workspace: Path, budget: list[int] | None = None) -> list[dict]:
    """Build run dicts for every directory that contains an outputs/ subdirectory."""
    budget = budget if budget is not None else [MAX_TOTAL_EMBED_BYTES]
    runs = [build_run(workspace, run_dir, budget) for run_dir in find_run_dirs(workspace)]
    runs.sort(key=lambda r: (eval_sort_key(r["eval_id"]), r["id"]))
    return runs


def is_link(path: Path) -> bool:
    """Treat symlinks and Windows junctions as links that must not be embedded."""
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def eval_directory(root: Path, run_dir: Path) -> str:
    """Return the eval directory (relative to root) that owns a run."""
    relative = run_dir.relative_to(root)
    for depth in range(1, len(relative.parts) + 1):
        if relative.parts[depth - 1].startswith("eval-"):
            return Path(*relative.parts[:depth]).as_posix()
    for depth in range(1, len(relative.parts) + 1):
        candidate = Path(*relative.parts[:depth])
        if (root / candidate / "eval_metadata.json").is_file():
            return candidate.as_posix()
    return relative.parts[0] if relative.parts else ""


def build_run(root: Path, run_dir: Path, budget: list[int]) -> dict:
    """Build a run dict with prompt, outputs, and grading data."""
    prompt = ""
    eval_id = None

    # Nested run-N directories share the evaluation metadata with their siblings.
    for directory in [run_dir, *run_dir.parents]:
        if not directory.is_relative_to(root):
            break
        candidate = directory / "eval_metadata.json"
        if candidate.exists():
            try:
                metadata = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if not isinstance(metadata, dict):
                    raise ValueError("eval_metadata.json must contain an object")
                candidate_prompt = metadata.get("prompt", "")
                candidate_eval_id = metadata.get("eval_id")
                if not isinstance(candidate_prompt, str):
                    raise ValueError("eval_metadata.json prompt must be a string")
                if (
                    candidate_eval_id is not None
                    and not isinstance(candidate_eval_id, (str, int))
                ) or isinstance(candidate_eval_id, bool):
                    raise ValueError("eval_metadata.json eval_id must be a string, integer, or null")
                if not prompt:
                    prompt = candidate_prompt
                if eval_id is None:
                    eval_id = candidate_eval_id
            except (json.JSONDecodeError, OSError, ValueError) as error:
                print(f"Warning: Invalid metadata in {candidate}: {error}", file=sys.stderr)
            if prompt and eval_id is not None:
                break

    # Fall back to transcript.md
    if not prompt:
        for candidate in [run_dir / "transcript.md", run_dir / "outputs" / "transcript.md"]:
            if candidate.exists():
                try:
                    text = candidate.read_text(encoding="utf-8")
                    match = re.search(r"## Eval Prompt\n\n([\s\S]*?)(?=\n##|$)", text)
                    if match:
                        prompt = match.group(1).strip()
                except OSError:
                    pass
                if prompt:
                    break

    if not prompt:
        prompt = "(No prompt found)"

    run_id = run_id_for(root, run_dir)

    # Collect output files
    outputs_dir = run_dir / "outputs"
    output_files: list[dict] = []
    user_notes = None
    if outputs_dir.is_dir() and not is_link(outputs_dir):
        for f in sorted(outputs_dir.rglob("*")):
            if is_link(f):
                print(f"Warning: Skipping linked output {f}", file=sys.stderr)
                continue
            if f.is_file() and f.name not in METADATA_FILES:
                embedded = embed_file(f, budget)
                embedded["name"] = f.relative_to(outputs_dir).as_posix()
                output_files.append(embedded)
        # Executor notes are shown in the Notes section, not as an output file.
        notes_file = outputs_dir / "user_notes.md"
        if notes_file.is_file() or is_link(notes_file):
            user_notes = embed_file(notes_file, budget)

    # Load grading if present
    grading = None
    for candidate in [run_dir / "grading.json", run_dir.parent / "grading.json"]:
        if candidate.exists():
            try:
                grading = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if not isinstance(grading, dict):
                    raise ValueError("grading.json must contain an object")
            except (json.JSONDecodeError, OSError, ValueError) as error:
                print(f"Warning: Invalid grading in {candidate}: {error}", file=sys.stderr)
                grading = None
            if grading:
                break

    return {
        "id": run_id,
        "eval_dir": eval_directory(root, run_dir),
        "prompt": prompt,
        "eval_id": eval_id,
        "outputs": output_files,
        "user_notes": user_notes,
        "grading": grading,
    }


def external_file(path: Path, size: int) -> dict:
    """Represent a local file without copying it into the review page."""
    return {
        "name": path.name,
        "type": "external",
        "path": str(path.resolve()),
        "size_bytes": size,
    }


def embed_file(path: Path, budget: list[int] | None = None) -> dict:
    """Read a file and return an embedded representation."""
    if budget is None:
        budget = [MAX_TOTAL_EMBED_BYTES]
    if is_link(path):
        return {"name": path.name, "type": "error", "content": "(Linked file not embedded)"}
    try:
        size = path.stat().st_size
    except OSError:
        return {"name": path.name, "type": "error", "content": "(Error reading file)"}
    if size > MAX_EMBED_BYTES:
        return external_file(path, size)

    ext = path.suffix.lower()
    mime = get_mime_type(path)

    if ext in TEXT_EXTENSIONS:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = "(Error reading file)"
        embedded_size = len(
            json.dumps(content).replace("<", "\\u003c").encode("utf-8")
        )
        if embedded_size > budget[0]:
            return external_file(path, size)
        budget[0] -= embedded_size
        return {
            "name": path.name,
            "type": "text",
            "content": content,
        }
    else:
        embedded_size = 4 * ((size + 2) // 3)
        if embedded_size > budget[0]:
            return external_file(path, size)
        budget[0] -= embedded_size

    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return {"name": path.name, "type": "error", "content": "(Error reading file)"}
    if ext == ".xlsx":
        return {
            "name": path.name,
            "type": "xlsx",
            "data_b64": b64,
        }
    file_type = "image" if ext in IMAGE_EXTENSIONS else "pdf" if ext == ".pdf" else "binary"
    result = {
        "name": path.name,
        "type": file_type,
        "data_uri": f"data:{mime};base64,{b64}",
    }
    if file_type != "pdf":
        result["mime"] = mime
    return result


def read_feedback(path: Path) -> dict:
    """Read feedback.json in the viewer format or the flat spec format.

    Returns {"reviews": {run_id: text}} for the viewer format, or
    {"flat": {key: text}} for the spec's {"eval-name": "feedback"} map.
    """
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("feedback.json must contain an object")
    if "reviews" in data:
        if not isinstance(data["reviews"], list):
            raise ValueError("feedback.json must contain an object with a reviews list")
        reviews = {
            review["run_id"]: review["feedback"]
            for review in data["reviews"]
            if isinstance(review, dict)
            and isinstance(review.get("run_id"), str)
            and isinstance(review.get("feedback"), str)
            and review["feedback"].strip()
        }
        return {"reviews": reviews}
    return {"flat": {
        key: value for key, value in data.items()
        if isinstance(value, str) and value.strip()
    }}


def load_previous_iteration(
    workspace: Path, budget: list[int] | None = None
) -> dict[str, dict]:
    """Load previous iteration's feedback and outputs.

    Returns a map of run_id -> {"feedback": str, "outputs": list[dict]}.
    Flat spec feedback keys match a run ID or the run's eval directory name.
    """
    result: dict[str, dict] = {}

    feedback: dict = {"reviews": {}}
    feedback_path = workspace / "feedback.json"
    if feedback_path.exists():
        try:
            feedback = read_feedback(feedback_path)
        except (json.JSONDecodeError, OSError, ValueError) as error:
            print(f"Warning: Invalid feedback in {feedback_path}: {error}", file=sys.stderr)

    prev_runs = find_runs(workspace, budget)
    feedback_map: dict[str, str] = dict(feedback.get("reviews", {}))
    flat = feedback.get("flat", {})
    used = set()
    for run in prev_runs:
        for key in (run["id"], run.get("eval_dir")):
            if key in flat:
                feedback_map[run["id"]] = flat[key]
                used.add(key)
                break
    feedback_map.update({key: value for key, value in flat.items() if key not in used})

    for run in prev_runs:
        result[run["id"]] = {
            "feedback": feedback_map.get(run["id"], ""),
            "outputs": run.get("outputs", []),
        }

    # Also add feedback for run_ids that had feedback but no matching run
    for run_id, fb in feedback_map.items():
        if run_id not in result:
            result[run_id] = {"feedback": fb, "outputs": []}

    return result


def generate_html(
    runs: list[dict],
    skill_name: str,
    previous: dict[str, dict] | None = None,
    benchmark: dict | None = None,
    server_mode: bool = False,
) -> str:
    """Generate the complete standalone HTML page with embedded data."""
    template_path = SKILL_ROOT / "assets" / "viewer.html"
    template = template_path.read_text(encoding="utf-8")

    embedded = {
        "skill_name": skill_name,
        "runs": runs,
        "previous": previous or {},
        "server_mode": server_mode,
    }
    if benchmark is not None:
        embedded["benchmark"] = benchmark

    data_json = json.dumps(embedded).replace("<", "\\u003c")

    return template.replace("/*__EMBEDDED_DATA__*/", f"const EMBEDDED_DATA = {data_json};")


def validate_feedback(data: object, known_run_ids: set[str] | None = None) -> None:
    """Reject feedback saves that do not match the viewer's payload shape."""
    if not isinstance(data, dict) or not isinstance(data.get("reviews"), list):
        raise ValueError("Expected JSON object with a reviews list")
    unknown = set(data) - {"reviews", "status"}
    if unknown:
        raise ValueError(f"Unexpected feedback fields: {', '.join(sorted(unknown))}")
    if "status" in data and data["status"] not in FEEDBACK_STATUSES:
        raise ValueError("status must be \"in_progress\" or \"complete\"")
    for review in data["reviews"]:
        if (
            not isinstance(review, dict)
            or not isinstance(review.get("run_id"), str)
            or not review["run_id"]
            or not isinstance(review.get("feedback"), str)
        ):
            raise ValueError("Each review must contain string run_id and feedback fields")
        if set(review) - {"run_id", "feedback", "timestamp"}:
            raise ValueError("Reviews may contain only run_id, feedback, and timestamp")
        if "timestamp" in review and not isinstance(review["timestamp"], str):
            raise ValueError("Review timestamp must be a string")
    if known_run_ids is not None:
        unknown_ids = sorted({review["run_id"] for review in data["reviews"]} - known_run_ids)
        if unknown_ids:
            shown = ", ".join(unknown_ids[:5]) + (", ..." if len(unknown_ids) > 5 else "")
            raise ValueError(f"Unknown run_id not in this workspace: {shown}")


def saved_feedback_ids(path: Path) -> set[str]:
    """Run IDs and flat keys already in feedback.json, so orphaned reviews stay savable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    if isinstance(data.get("reviews"), list):
        return {
            review["run_id"] for review in data["reviews"]
            if isinstance(review, dict) and isinstance(review.get("run_id"), str)
        }
    return {key for key, value in data.items() if isinstance(value, str)}


# ---------------------------------------------------------------------------
# HTTP server (stdlib only, zero dependencies)
# ---------------------------------------------------------------------------

class ReviewServer(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR can bind an occupied port instead of reporting a conflict.
    allow_reuse_address = sys.platform != "win32"


class ReviewHandler(BaseHTTPRequestHandler):
    """Serves the review HTML and handles feedback saves.

    Regenerates the HTML on each page load so that refreshing the browser
    picks up new eval outputs without restarting the server.
    """
    timeout = 10

    def __init__(
        self,
        workspace: Path,
        skill_name: str,
        feedback_path: Path,
        previous: dict[str, dict],
        benchmark_path: Path | None,
        embed_budget: int,
        *args,
        **kwargs,
    ):
        self.workspace = workspace
        self.skill_name = skill_name
        self.feedback_path = feedback_path
        self.previous = previous
        self.benchmark_path = benchmark_path
        self.embed_budget = embed_budget
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.headers.get("Host") not in self.allowed_hosts():
            self.send_error(403, "Review data is available only from this review page")
            return
        if self.path == "/" or self.path == "/index.html":
            # Regenerate HTML on each request (re-scans workspace for new outputs)
            runs = find_runs(self.workspace, [self.embed_budget])
            benchmark = load_benchmark(self.benchmark_path) if self.benchmark_path else None
            html = generate_html(runs, self.skill_name, self.previous, benchmark, server_mode=True)
            content = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/api/feedback":
            data = b"{}"
            if self.feedback_path.exists():
                data = self.feedback_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/feedback":
            allowed_hosts = self.allowed_hosts()
            origin = self.headers.get("Origin")
            if (
                self.headers.get("Host") not in allowed_hosts
                or origin is None
                or urlparse(origin).scheme != "http"
                or urlparse(origin).netloc not in allowed_hosts
            ):
                self.send_error(403, "Feedback saves are accepted only from this review page")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length < 0:
                    raise ValueError("Content-Length must not be negative")
                if length > MAX_FEEDBACK_BYTES:
                    self.send_json(413, {"error": "Feedback is too large"}, close=True)
                    return
                body = self.rfile.read(length)
                data = json.loads(body)
                known = {run_id_for(self.workspace, run) for run in find_run_dirs(self.workspace)}
                validate_feedback(data, known | saved_feedback_ids(self.feedback_path))
                atomic_write_text(self.feedback_path, json.dumps(data, indent=2) + "\n")
            except (json.JSONDecodeError, OSError, ValueError) as e:
                status = 400 if isinstance(e, (json.JSONDecodeError, ValueError)) else 500
                self.send_json(status, {"error": str(e)})
                return
            self.send_json(200, {"ok": True})
        else:
            self.send_error(404)

    def send_json(self, status: int, payload: dict, close: bool = False) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if getattr(self, "command", None) != "HEAD":
            self.wfile.write(body)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Send API errors as JSON; other paths keep the standard HTML error page."""
        if not urlparse(getattr(self, "path", "") or "").path.startswith("/api/"):
            super().send_error(code, message, explain)
            return
        self.log_error("code %d, message %s", code, message)
        if message is None:
            message = self.responses.get(code, ("Request failed",))[0]
        self.send_json(code, {"error": message}, close=True)

    def allowed_hosts(self) -> set[str]:
        port = self.server.server_port
        return {f"localhost:{port}", f"127.0.0.1:{port}"}

    def log_message(self, format: str, *args: object) -> None:
        # Suppress request logging to keep terminal clean
        pass


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r}") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 0 and 65535, got {port}")
    return port


def main() -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Generate and serve eval review")
    parser.add_argument("workspace", type=Path, help="Path to workspace directory")
    parser.add_argument(
        "--port", "-p", type=port_number, default=3117,
        help="Server port, 0-65535; 0 picks a free port (default: 3117)",
    )
    parser.add_argument("--skill-name", "-n", type=str, default=None, help="Skill name for header")
    parser.add_argument(
        "--previous-workspace", type=Path, default=None,
        help="Path to previous iteration's workspace (shows old outputs and feedback as context)",
    )
    parser.add_argument(
        "--benchmark", type=Path, default=None,
        help="Path to benchmark.json to show in the Benchmark tab",
    )
    parser.add_argument(
        "--static", "-s", type=Path, default=None,
        help="Write standalone HTML to this path instead of starting a server",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="Open the review page in the default browser",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"Error: {workspace} is not a directory", file=sys.stderr)
        sys.exit(1)

    embed_budget = [MAX_TOTAL_EMBED_BYTES]
    runs = find_runs(workspace, embed_budget)
    if not runs:
        print(f"No runs found in {workspace}", file=sys.stderr)
        sys.exit(1)
    remaining_after_current = embed_budget[0]

    skill_name = args.skill_name or workspace.name.replace("-workspace", "")
    feedback_path = workspace / "feedback.json"

    previous: dict[str, dict] = {}
    if args.previous_workspace:
        previous = load_previous_iteration(args.previous_workspace.resolve(), embed_budget)
        if previous and not any(run["id"] in previous for run in runs):
            print(
                "Warning: No current run matches the previous workspace; "
                "keep eval directory names stable between iterations.",
                file=sys.stderr,
            )
    previous_embed_bytes = remaining_after_current - embed_budget[0]

    benchmark_path = args.benchmark.resolve() if args.benchmark else None
    benchmark = load_benchmark(benchmark_path) if benchmark_path else None

    if args.static:
        html = generate_html(runs, skill_name, previous, benchmark)
        static_path = args.static.resolve()
        atomic_write_text(args.static, html)
        print(f"\n  Static viewer written to: {static_path}")
        print(f"  URL:       {static_path.as_uri()}\n")
        if args.open:
            webbrowser.open(static_path.as_uri())
        sys.exit(0)

    port = args.port
    handler = partial(
        ReviewHandler, workspace, skill_name, feedback_path, previous,
        benchmark_path, MAX_TOTAL_EMBED_BYTES - previous_embed_bytes,
    )
    try:
        server = ReviewServer(("127.0.0.1", port), handler)
    except OSError as error:
        if error.errno != errno.EADDRINUSE and getattr(error, "winerror", None) != 10048:
            raise
        print(f"Port {port} is in use; using an available port instead.", file=sys.stderr)
        server = ReviewServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    url = f"http://localhost:{port}"
    print("\n  Eval Viewer")
    print(f"  URL:       {url}")
    print(f"  Workspace: {workspace}")
    print(f"  Feedback:  {feedback_path}")
    if previous:
        print(f"  Previous:  {args.previous_workspace} ({len(previous)} runs)")
    if benchmark is not None:
        print(f"  Benchmark: {benchmark_path}")
    print("\n  Press Ctrl+C to stop.\n", flush=True)

    if args.open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

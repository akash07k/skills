#!/usr/bin/env python3
"""Run trigger evaluation for a skill description.

Tests whether a skill's description causes Copilot to trigger (read the skill)
for a set of queries. Outputs results as JSON.
"""

import argparse
import json
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.utils import parse_skill_md
from scripts.copilot_cli import check_event, copilot_command, copilot_version


def validate_eval_set(eval_set: list[dict]) -> None:
    """Validate trigger queries, not the task-oriented evals.json format."""
    if not isinstance(eval_set, list) or not eval_set:
        raise ValueError("Trigger eval set must be a nonempty list of query/should_trigger objects")
    for index, item in enumerate(eval_set):
        if not isinstance(item, dict) or not isinstance(item.get("query"), str) or not item["query"].strip():
            raise ValueError(f"Trigger eval entry {index} must have a nonempty query string")
        if type(item.get("should_trigger")) is not bool:
            raise ValueError(f"Trigger eval entry {index} must have a boolean should_trigger")


def _read_stream(stream, source: str, events: queue.Queue, stopped: threading.Event) -> None:
    """Read pipes in threads: Windows select() only supports sockets."""
    def send(chunk):
        while not stopped.is_set():
            try:
                events.put((source, chunk), timeout=0.1)
                return
            except queue.Full:
                pass

    try:
        while not stopped.is_set():
            chunk = stream.readline() if source == "stdout" else stream.read1(8192)
            if not chunk:
                break
            send(chunk)
    except Exception as exc:
        send(exc)
    finally:
        stream.close()
        send(None)


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    model: str | None = None,
    cancelled: threading.Event | None = None,
    cli_version: str | None = None,
) -> bool:
    """Run a single query and return whether the skill was triggered.

    Loads one temporary .github/skills candidate through --add-dir.
    Measures the first tool decision with read-only tools available; it does
    not execute the task or benchmark the quality of generated outputs.
    Timeout, CLI, and incomplete-stream failures raise instead of scoring
    an infrastructure failure as a negative trigger decision.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_name) or len(skill_name) > 64:
        raise ValueError("skill_name must be a lowercase hyphenated name of at most 64 characters")
    if cancelled and cancelled.is_set():
        raise RuntimeError("evaluation cancelled")
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name[:45].rstrip('-')}-eval-{unique_id}"
    cmd = copilot_command(model, tools=("skill", "view"))

    with tempfile.TemporaryDirectory(
        prefix="copilot-skill-eval-", ignore_cleanup_errors=True
    ) as temporary:
        candidate_root = Path(temporary)
        skill_file = candidate_root / ".github" / "skills" / clean_name / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        # Use YAML block scalar to avoid breaking on quotes in description
        indented_desc = "\n".join(
            f"  {line}" if line else ""
            for line in skill_description.rstrip("\n").split("\n")
        )
        command_content = (
            f"---\n"
            f"name: {clean_name}\n"
            f"description: |\n"
            f"{indented_desc}\n"
            f"---\n\n"
            f"# {skill_name}\n\n"
            f"This skill handles: {skill_description}\n"
        )
        skill_file.write_text(command_content, encoding="utf-8")
        prompt_file = candidate_root / "prompt.txt"
        prompt_file.write_text(query, encoding="utf-8")
        cmd.extend(["--add-dir", str(candidate_root)])
        # Redirecting a file avoids Windows argv limits and a blocking stdin pipe.
        with prompt_file.open("rb") as prompt_input:
            process = subprocess.Popen(
                cmd, stdin=prompt_input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=candidate_root,
            )

        deadline = time.monotonic() + timeout
        events = queue.Queue(maxsize=64)
        stopped = threading.Event()
        readers = [
            threading.Thread(target=_read_stream, args=(stream, source, events, stopped), daemon=True)
            for stream, source in ((process.stdout, "stdout"), (process.stderr, "stderr"))
        ]
        diagnostics = deque(maxlen=16)
        completed = False
        discovered = None
        pending_tool_name = None
        pending_tool_id = None
        accumulated_json = ""

        def failure(message):
            detail = b"".join(diagnostics).decode("utf-8", errors="replace").strip()
            version = cli_version or "unknown"
            return RuntimeError(
                f"Copilot {message}\nCopilot CLI version: {version}"
                + (f"\n{detail}" if detail else "")
            )

        def decision(tool_name, arguments):
            if not isinstance(tool_name, str) or not tool_name:
                raise failure("returned an invalid tool name")
            if not isinstance(arguments, dict):
                raise failure("returned invalid tool arguments")
            if tool_name == "skill":
                if not isinstance(arguments.get("skill"), str) or not arguments["skill"]:
                    raise failure("returned invalid skill tool arguments")
                return arguments.get("skill") == clean_name
            if tool_name == "view":
                path = arguments.get("path")
                if not isinstance(path, str) or not path:
                    raise failure("returned invalid view tool arguments")
                absolute = Path(path) if Path(path).is_absolute() else candidate_root / path
                return os.path.normcase(str(absolute.resolve())) == os.path.normcase(str(skill_file.resolve()))
            return False

        try:
            for reader in readers:
                reader.start()
            open_streams = len(readers)
            while open_streams:
                if cancelled and cancelled.is_set():
                    raise failure("evaluation cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(str(failure(f"timed out after {timeout}s")))
                try:
                    source, chunk = events.get(timeout=min(remaining, 0.1))
                except queue.Empty:
                    continue
                if isinstance(chunk, Exception):
                    raise failure(f"could not read {source}: {chunk}") from chunk
                if chunk is None:
                    open_streams -= 1
                    continue
                if source == "stderr":
                    diagnostics.append(chunk)
                    continue
                try:
                    event = json.loads(chunk)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    diagnostics.append(chunk[-8192:])
                    raise failure("returned invalid JSONL output (incomplete stream)") from error
                if not isinstance(event, dict):
                    raise failure("returned a non-object JSONL event")
                try:
                    check_event(event)
                except RuntimeError as error:
                    raise failure(str(error).removeprefix("Copilot ")) from error
                data = event.get("data", {})

                # Stop at the first tool decision, before tool execution completes.
                if event.get("type") == "session.skills_loaded":
                    loaded_skills = data.get("skills", [])
                    competing_skill = next((
                        skill for skill in loaded_skills
                        if skill.get("name") == skill_name and skill.get("enabled") is True
                    ), None)
                    if competing_skill:
                        raise failure(
                            "also loaded the original skill being optimized"
                            f" ({competing_skill.get('path', 'path unknown')}); run from a project"
                            " that does not contain or install that skill"
                        )
                    discovered = any(
                        skill.get("name") == clean_name and skill.get("enabled") is True
                        for skill in loaded_skills
                    )
                    if not discovered:
                        raise failure("did not discover the enabled candidate skill")
                elif event.get("type") == "assistant.tool_call_delta":
                    tool_call_id = data.get("toolCallId")
                    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                        raise failure("returned an invalid tool call id")
                    if pending_tool_id is None:
                        pending_tool_id = tool_call_id
                        pending_tool_name = data.get("toolName")
                    if tool_call_id != pending_tool_id:
                        continue
                    pending_tool_name = data.get("toolName") or pending_tool_name
                    if pending_tool_name and pending_tool_name not in ("skill", "view"):
                        return decision(pending_tool_name, {})
                    accumulated_json += data.get("inputDelta", "")
                    try:
                        arguments = json.loads(accumulated_json)
                    except json.JSONDecodeError:
                        continue
                    if pending_tool_name is None:
                        continue
                    return decision(pending_tool_name, arguments)
                elif event.get("type") == "assistant.message":
                    requests = data.get("toolRequests", [])
                    if requests:
                        return decision(requests[0].get("name"), requests[0].get("arguments"))
                elif event.get("type") == "tool.execution_start":
                    return decision(data.get("toolName"), data.get("arguments"))
                elif event.get("type") == "result":
                    completed = True

            try:
                returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise TimeoutError(str(failure(f"timed out after {timeout}s"))) from None
            if returncode != 0:
                raise failure(f"exited {returncode}")
            if not completed:
                raise failure("ended without a result or tool decision (incomplete stream)")
            if pending_tool_id is not None:
                raise failure("ended with incomplete tool arguments (incomplete stream)")
            return False
        finally:
            stopped.set()
            if process.poll() is None:
                process.kill()
            process.wait()
            for reader in readers:
                if reader.ident is not None:
                    reader.join(timeout=1)


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
) -> dict:
    """Return one result per input entry, in input order, or raise on run failure."""
    validate_eval_set(eval_set)
    if num_workers < 1 or runs_per_query < 1:
        raise ValueError("num_workers and runs_per_query must be positive")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    if not 0 <= trigger_threshold <= 1:
        raise ValueError("trigger_threshold must be between 0 and 1")
    results = []
    query_triggers = [[] for _ in eval_set]
    cancelled = threading.Event()
    cli_version = copilot_version()

    executor = ThreadPoolExecutor(max_workers=num_workers)
    try:
        future_to_info = {}
        for index, item in enumerate(eval_set):
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    run_single_query,
                    item["query"],
                    skill_name,
                    description,
                    timeout,
                    model,
                    cancelled,
                    cli_version,
                )
                future_to_info[future] = (index, run_idx)

        for future in as_completed(future_to_info):
            index, run_idx = future_to_info[future]
            try:
                query_triggers[index].append(future.result())
            except Exception as exc:
                cancelled.set()
                for pending in future_to_info:
                    pending.cancel()
                raise RuntimeError(
                    f"Trigger eval entry {index}, run {run_idx + 1} failed "
                    f"for {eval_set[index]['query']!r}: {exc}"
                ) from exc
    except Exception:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    for index, (item, triggers) in enumerate(zip(eval_set, query_triggers)):
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "eval_id": index,
            "query": item["query"],
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": sum(triggers),
            "runs": len(triggers),
            "pass": did_pass,
        })

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "copilot_cli_version": cli_version,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run trigger evaluation for a skill description")
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument("--num-workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout per query in seconds")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Number of runs per query")
    parser.add_argument("--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold")
    parser.add_argument("--model", default=None, help="Copilot model ID (default: user's configured Copilot model)")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    try:
        eval_set = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))
        validate_eval_set(eval_set)
        if not (skill_path / "SKILL.md").exists():
            raise ValueError(f"No SKILL.md found at {skill_path}")
        name, original_description, _ = parse_skill_md(skill_path)
        description = args.description or original_description
        call_count = len(eval_set) * args.runs_per_query
        print(
            f"Planned usage: {call_count} evaluation calls; "
            f"up to {min(args.num_workers, call_count)} concurrent.",
            file=sys.stderr,
        )
        if args.verbose:
            print(f"Evaluating: {description}", file=sys.stderr)
        output = run_eval(
            eval_set=eval_set,
            skill_name=name,
            description=description,
            num_workers=args.num_workers,
            timeout=args.timeout,
            runs_per_query=args.runs_per_query,
            trigger_threshold=args.trigger_threshold,
            model=args.model,
        )
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)



    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            print(f"  [{status}] rate={rate_str} expected={r['should_trigger']}: {r['query'][:70]}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

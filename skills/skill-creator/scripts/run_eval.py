#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Run trigger evaluation for a skill description.

Tests whether a skill's description causes Copilot to trigger (read the skill)
for a set of queries. Outputs results as JSON.

Usage:
    python scripts/run_eval.py --eval-set <trigger_evals.json> --skill-path <skill-dir>
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

if sys.version_info < (3, 13):
    sys.exit("skill-creator scripts require Python 3.13 or later.")

if not __package__:
    # Allow `python <skill>/scripts/<name>.py` from any working directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import ensure_utf8_stdio, parse_skill_md
from scripts.copilot_cli import (
    check_event, copilot_command, copilot_version, isolated_env, kill_process_tree,
    process_group_kwargs,
)

# Models often list the workspace before choosing a skill; this many other
# views without a skill decision scores as no trigger.
MAX_EXPLORATION_VIEWS = 8
# Offered but never approved, so a model can start the task without the skill.
WRITE_TOOLS = ("create", "edit", "apply_patch")


class DefaultsHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    """Show "(default: X)" only for options with a meaningful default value."""

    def _get_help_string(self, action):
        if action.default is None or isinstance(action.default, bool):
            return action.help
        return super()._get_help_string(action)


def positive_int(text: str) -> int:
    """argparse type: an integer of at least 1."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text!r}")
    return value


def _float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    return value


def threshold_fraction(text: str) -> float:
    """argparse type: a number strictly between 0 and 1."""
    value = _float(text)
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError(f"must be strictly between 0 and 1, got {text!r}")
    return value


def holdout_fraction(text: str) -> float:
    """argparse type: a number from 0 (inclusive) up to 1 (exclusive)."""
    value = _float(text)
    if not 0 <= value < 1:
        raise argparse.ArgumentTypeError(
            f"must be at least 0 and less than 1, got {text!r}"
        )
    return value


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

    Loads one temporary .github/skills candidate through --add-dir, with
    personal skills and plugins hidden. Scores the first skill decision:
    a skill call, or a view of the candidate SKILL.md. Other views are
    exploration, up to MAX_EXPLORATION_VIEWS, as are scratch writes to the
    CLI profile, .git, or prompt.txt; any other write-tool call is a
    negative, since the model started the task without the skill. It does not execute the task
    or benchmark the quality of generated outputs.
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
    cmd = copilot_command(model, tools=("skill", "view", *WRITE_TOOLS))

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
                cwd=candidate_root, env=isolated_env(candidate_root), **process_group_kwargs(),
            )
        try:
            return _await_decision(
                process, timeout, cancelled, cli_version,
                skill_name, clean_name, candidate_root, skill_file,
            )
        finally:
            # Covers timeouts, errors, and KeyboardInterrupt: kill the whole
            # Copilot process tree before the candidate directory is removed.
            kill_process_tree(process)
            process.wait()


def _await_decision(
    process: subprocess.Popen,
    timeout: float,
    cancelled: threading.Event | None,
    cli_version: str | None,
    skill_name: str,
    clean_name: str,
    candidate_root: Path,
    skill_file: Path,
) -> bool:
    """Read Copilot's JSONL stream until the first tool decision or the result."""
    deadline = time.monotonic() + timeout
    events = queue.Queue(maxsize=64)
    stopped = threading.Event()
    readers = [
        threading.Thread(target=_read_stream, args=(stream, source, events, stopped), daemon=True)
        for stream, source in ((process.stdout, "stdout"), (process.stderr, "stderr"))
    ]
    diagnostics = deque(maxlen=16)
    completed = False
    populated_discovery_reported = False
    candidate_discovered = False
    pending_tool_name = None
    pending_tool_id = None
    accumulated_json = ""
    explored = 0
    decided_ids = set()

    def failure(message):
        detail = b"".join(diagnostics).decode("utf-8", errors="replace").strip()
        version = cli_version or "unknown"
        return RuntimeError(
            f"Copilot {message}\nCopilot CLI version: {version}"
            + (f"\n{detail}" if detail else "")
        )

    def explore():
        # A non-candidate view, or a malformed skill/view call the model can retry.
        nonlocal explored
        explored += 1
        return False if explored > MAX_EXPLORATION_VIEWS else None

    def decision(tool_name, arguments):
        if populated_discovery_reported and not candidate_discovered:
            raise failure("did not discover the enabled candidate skill")
        if not isinstance(tool_name, str) or not tool_name:
            raise failure("returned an invalid tool name")
        if tool_name == "apply_patch" and isinstance(arguments, str):
            # Some models send apply_patch as a raw freeform patch, not JSON.
            arguments = {"input": arguments}
        if not isinstance(arguments, dict):
            raise failure("returned invalid tool arguments")
        if tool_name == "skill":
            if not isinstance(arguments.get("skill"), str) or not arguments["skill"]:
                return explore()
            return arguments.get("skill") == clean_name
        if tool_name == "view":
            path = arguments.get("path")
            if not isinstance(path, str) or not path:
                return explore()
            if same_path(path, skill_file):
                return True
            return explore()
        if tool_name in WRITE_TOOLS:
            if tool_name == "apply_patch":
                patch = arguments.get("input") or arguments.get("patch") or ""
                paths = re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", str(patch), re.M)
            else:
                paths = [arguments.get("path")]
            # Scratch notes in the CLI's own state or harness files are orientation, not task work.
            if paths and all(isinstance(p, str) and p and harness_owned(p) for p in paths):
                return explore()
        return False

    def resolve(path):
        absolute = Path(path) if Path(path).is_absolute() else candidate_root / path
        return os.path.normcase(str(absolute.resolve()))

    def same_path(path, target):
        return resolve(path) == os.path.normcase(str(target.resolve()))

    def harness_owned(path):
        resolved = resolve(path)
        return resolved == resolve("prompt.txt") or any(
            resolved == resolve(name) or resolved.startswith(resolve(name) + os.sep)
            for name in (".profile", ".git")
        )

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

            # Stop at the first skill decision, before tool execution completes.
            # Copilot CLI 1.0.99+ no longer emits session.skills_loaded, so these
            # discovery checks are best-effort and only run when the event exists.
            if event.get("type") == "session.skills_loaded":
                loaded_skills = data.get("skills", [])
                populated_discovery_reported = (
                    populated_discovery_reported or bool(loaded_skills)
                )
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
                candidate = next((
                    skill for skill in loaded_skills
                    if skill.get("name") == clean_name
                ), None)
                if candidate and candidate.get("enabled") is not True:
                    raise failure(
                        "reported the candidate skill as disabled"
                        f" ({candidate.get('path', 'path unknown')})"
                    )
                candidate_discovered = candidate_discovered or bool(candidate)
            elif event.get("type") == "assistant.tool_call_delta":
                tool_call_id = data.get("toolCallId")
                if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                    raise failure("returned an invalid tool call id")
                if tool_call_id in decided_ids:
                    continue
                if pending_tool_id is None:
                    pending_tool_id = tool_call_id
                    pending_tool_name = data.get("toolName")
                if tool_call_id != pending_tool_id:
                    continue
                pending_tool_name = data.get("toolName") or pending_tool_name
                if pending_tool_name and pending_tool_name not in ("skill", "view", *WRITE_TOOLS):
                    return decision(pending_tool_name, {})
                accumulated_json += data.get("inputDelta", "")
                try:
                    arguments = json.loads(accumulated_json)
                except json.JSONDecodeError:
                    continue
                if pending_tool_name is None:
                    continue
                result = decision(pending_tool_name, arguments)
                if result is not None:
                    return result
                decided_ids.add(pending_tool_id)
                pending_tool_id, pending_tool_name, accumulated_json = None, None, ""
            elif event.get("type") == "assistant.message":
                for request in data.get("toolRequests", []):
                    if request.get("toolCallId") in decided_ids:
                        continue
                    result = decision(request.get("name"), request.get("arguments"))
                    if result is not None:
                        return result
                    decided_ids.add(request.get("toolCallId"))
                    if request.get("toolCallId") == pending_tool_id:
                        pending_tool_id, pending_tool_name, accumulated_json = None, None, ""
            elif event.get("type") == "tool.execution_start":
                if data.get("toolCallId") in decided_ids:
                    continue
                result = decision(data.get("toolName"), data.get("arguments"))
                if result is not None:
                    return result
                decided_ids.add(data.get("toolCallId"))
                if data.get("toolCallId") == pending_tool_id:
                    pending_tool_id, pending_tool_name, accumulated_json = None, None, ""
            elif event.get("type") == "result":
                if populated_discovery_reported and not candidate_discovered:
                    raise failure("did not discover the enabled candidate skill")
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
        kill_process_tree(process)
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
    if not 0 < trigger_threshold < 1:
        raise ValueError("trigger_threshold must be strictly between 0 and 1")
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
    except BaseException:
        # Includes KeyboardInterrupt: workers see `cancelled`, kill their
        # Copilot process trees, and remove candidate directories before exit.
        cancelled.set()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    for index, (item, triggers) in enumerate(zip(eval_set, query_triggers)):
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        # agentskills.io: positives pass strictly above, negatives strictly below.
        if should_trigger:
            did_pass = trigger_rate > trigger_threshold
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
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="python scripts/run_eval.py",
        description="Run trigger evaluation for a skill description",
        epilog="Exit codes: 0 success, 1 error, 2 usage error, 130 interrupted (Ctrl+C).",
        formatter_class=DefaultsHelpFormatter,
    )
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument("--num-workers", type=positive_int, default=4, help="Number of parallel workers (at least 1)")
    parser.add_argument("--timeout", type=positive_int, default=60, help="Timeout per query in whole seconds (at least 1)")
    parser.add_argument("--runs-per-query", type=positive_int, default=3, help="Number of runs per query (at least 1)")
    parser.add_argument(
        "--trigger-threshold", type=threshold_fraction, default=0.5,
        help="Trigger rate threshold, strictly between 0 and 1. A should-trigger"
        " query passes only if its trigger rate is strictly above it; a should-not-trigger"
        " query passes only if its rate is strictly below it.",
    )
    parser.add_argument("--model", default=None, help="Copilot model ID (default: user's configured Copilot model)")
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print the evaluated description and per-query PASS/FAIL lines to stderr"
        " (stdout stays JSON). No per-query log files are written.",
    )
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    try:
        eval_set = json.loads(Path(args.eval_set).read_text(encoding="utf-8-sig"))
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
    except KeyboardInterrupt:
        print("Interrupted; Copilot processes were stopped.", file=sys.stderr)
        sys.exit(130)

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

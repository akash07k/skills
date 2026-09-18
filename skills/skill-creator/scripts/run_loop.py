#!/usr/bin/env python3
"""Run the eval + improve loop until all pass or max iterations reached.

Combines run_eval.py and improve_description.py in a loop, tracking history
and returning the best description found. Supports train/test split to prevent
overfitting.
"""

import argparse
import json
import random
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from scripts.generate_report import generate_html
from scripts.improve_description import improve_description
from scripts.run_eval import run_eval, validate_eval_set
from scripts.copilot_cli import copilot_version
from scripts.utils import atomic_write_text, best_iteration, parse_skill_md


def build_output(
    history: list[dict],
    original_description: str,
    current_description: str,
    holdout: float,
    train_set: list[dict],
    test_set: list[dict],
    exit_reason: str,
    error: str | None = None,
    copilot_cli_version: str | None = None,
) -> dict:
    """Build a complete result even when an evaluation fails partway through."""
    best = best_iteration(history, bool(test_set))
    if best:
        if test_set:
            best_score = f"{best['test_passed']}/{best['test_total']}"
        else:
            best_score = f"{best['train_passed']}/{best['train_total']}"
        best_description = best["description"]
    else:
        best_description = current_description
        best_score = "not evaluated"
    output = {
        "exit_reason": exit_reason,
        "original_description": original_description,
        "best_description": best_description,
        "best_score": best_score,
        "final_description": current_description,
        "iterations_run": len(history),
        "holdout": holdout,
        "train_size": len(train_set),
        "test_size": len(test_set),
        "copilot_cli_version": copilot_cli_version,
        "history": history,
    }
    if error:
        output["error"] = error
    return output


def split_eval_set(eval_set: list[dict], holdout: float, seed: int = 42) -> tuple[list[dict], list[dict]]:
    """Stratify by label while retaining each entry's identity and input order."""
    validate_eval_set(eval_set)
    if not 0 <= holdout < 1:
        raise ValueError("holdout must be between 0 (inclusive) and 1 (exclusive)")
    if holdout == 0:
        return list(eval_set), []
    rng = random.Random(seed)

    test_indices = set()
    for label in (True, False):
        indices = [i for i, item in enumerate(eval_set) if item["should_trigger"] == label]
        rng.shuffle(indices)
        # Keep a training example of each label, even for small eval sets.
        count = min(max(1, int(len(indices) * holdout)), max(0, len(indices) - 1))
        test_indices.update(indices[:count])
    if not test_indices:
        raise ValueError("holdout needs at least two entries for each label; add queries or set holdout=0")
    train_set = [item for i, item in enumerate(eval_set) if i not in test_indices]
    test_set = [item for i, item in enumerate(eval_set) if i in test_indices]
    if {item["should_trigger"] for item in test_set} != {True, False}:
        raise ValueError("holdout needs at least two entries for each label; add queries or set holdout=0")

    return train_set, test_set


def run_loop(
    eval_set: list[dict],
    skill_path: Path,
    description_override: str | None,
    num_workers: int,
    timeout: int,
    max_iterations: int,
    runs_per_query: int,
    trigger_threshold: float,
    holdout: float,
    model: str | None,
    verbose: bool,
    live_report_path: Path | None = None,
    log_dir: Path | None = None,
) -> dict:
    """Run the eval + improvement loop."""
    validate_eval_set(eval_set)
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    if not 0 <= holdout < 1:
        raise ValueError("holdout must be between 0 (inclusive) and 1 (exclusive)")
    eval_set = [dict(item, eval_id=index) for index, item in enumerate(eval_set)]
    name, original_description, content = parse_skill_md(skill_path)
    current_description = description_override or original_description

    # Split into train/test if holdout > 0
    if holdout > 0:
        train_set, test_set = split_eval_set(eval_set, holdout)
        if verbose:
            print(f"Split: {len(train_set)} train, {len(test_set)} test (holdout={holdout})", file=sys.stderr)
    else:
        train_set = eval_set
        test_set = []

    history = []
    exit_reason = "unknown"
    cli_version = copilot_version()

    try:
        for iteration in range(1, max_iterations + 1):
            if verbose:
                print(f"\n{'='*60}", file=sys.stderr)
                print(f"Iteration {iteration}/{max_iterations}", file=sys.stderr)
                print(f"Description: {current_description}", file=sys.stderr)
                print(f"{'='*60}", file=sys.stderr)

            # Evaluate train + test together in one batch for parallelism
            t0 = time.time()
            all_results = run_eval(
                eval_set=eval_set,
                skill_name=name,
                description=current_description,
                num_workers=num_workers,
                timeout=timeout,
                runs_per_query=runs_per_query,
                trigger_threshold=trigger_threshold,
                model=model,
            )
            cli_version = all_results.get("copilot_cli_version")
            eval_elapsed = time.time() - t0

            # Query text is not an identity: identical queries may be in both sets.
            train_ids = {item["eval_id"] for item in train_set}
            train_results = [r for r in all_results["results"] if r["eval_id"] in train_ids]
            test_results = [r for r in all_results["results"] if r["eval_id"] not in train_ids]

            train_passed = sum(1 for r in train_results if r["pass"])
            train_total = len(train_results)
            train_failed = train_total - train_passed

            if test_set:
                test_passed = sum(1 for r in test_results if r["pass"])
                test_total = len(test_results)
            else:
                test_passed = None
                test_total = None
                test_results = None

            history.append({
            "iteration": iteration,
            "description": current_description,
            "train_passed": train_passed,
            "train_total": train_total,
            "train_results": train_results,
            "test_passed": test_passed,
            "test_total": test_total,
            "test_results": test_results,
            })

            # Write live report if path provided
            if live_report_path:
                partial_output = {
                    "original_description": original_description,
                    "best_description": current_description,
                    "best_score": "in progress",
                    "iterations_run": len(history),
                    "holdout": holdout,
                    "train_size": len(train_set),
                    "test_size": len(test_set),
                    "history": history,
                }
                atomic_write_text(
                    live_report_path,
                    generate_html(partial_output, auto_refresh=True, skill_name=name),
                )

            if verbose:
                def print_eval_stats(label, results, elapsed):
                    pos = [r for r in results if r["should_trigger"]]
                    neg = [r for r in results if not r["should_trigger"]]
                    tp = sum(r["triggers"] for r in pos)
                    pos_runs = sum(r["runs"] for r in pos)
                    fn = pos_runs - tp
                    fp = sum(r["triggers"] for r in neg)
                    neg_runs = sum(r["runs"] for r in neg)
                    tn = neg_runs - fp
                    total = tp + tn + fp + fn
                    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
                    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
                    accuracy = (tp + tn) / total if total > 0 else 0.0
                    print(f"{label}: {tp+tn}/{total} correct, precision={precision:.0%} recall={recall:.0%} accuracy={accuracy:.0%} ({elapsed:.1f}s)", file=sys.stderr)
                    for r in results:
                        status = "PASS" if r["pass"] else "FAIL"
                        rate_str = f"{r['triggers']}/{r['runs']}"
                        print(f"  [{status}] rate={rate_str} expected={r['should_trigger']}: {r['query'][:60]}", file=sys.stderr)

                print_eval_stats("Train", train_results, eval_elapsed)
                if test_results is not None:
                    print_eval_stats("Test ", test_results, 0)

            if train_failed == 0:
                exit_reason = f"all_passed (iteration {iteration})"
                if verbose:
                    print(f"\nAll train queries passed on iteration {iteration}!", file=sys.stderr)
                break

            if iteration == max_iterations:
                exit_reason = f"max_iterations ({max_iterations})"
                if verbose:
                    print(f"\nMax iterations reached ({max_iterations}).", file=sys.stderr)
                break

            # Improve the description based on train results
            if verbose:
                print("\nImproving description...", file=sys.stderr)

            t0 = time.time()
            # Strip test scores from history so improvement model can't see them
            blinded_history = [
                {k: v for k, v in h.items() if not k.startswith("test_")}
                for h in history
            ][:-1]
            new_description = improve_description(
                skill_name=name,
                skill_content=content,
                current_description=current_description,
                eval_results={
                    "results": train_results,
                    "summary": {
                        "passed": train_passed,
                        "failed": train_failed,
                        "total": train_total,
                    },
                },
                history=blinded_history,
                model=model,
                log_dir=log_dir,
                iteration=iteration,
            )
            improve_elapsed = time.time() - t0

            if verbose:
                print(f"Proposed ({improve_elapsed:.1f}s): {new_description}", file=sys.stderr)

            current_description = new_description
    except (RuntimeError, TimeoutError, OSError, ValueError, subprocess.SubprocessError) as error:
        exit_reason = f"failed: {error}"
        if verbose:
            print(f"\nEvaluation failed: {error}", file=sys.stderr)
        return build_output(
            history, original_description, current_description, holdout, train_set, test_set,
            exit_reason, str(error), cli_version,
        )

    if verbose:
        print(f"\nExit reason: {exit_reason}", file=sys.stderr)
    return build_output(
        history, original_description, current_description, holdout, train_set, test_set, exit_reason,
        copilot_cli_version=cli_version,
    )


def main():
    parser = argparse.ArgumentParser(description="Run eval + improve loop")
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override starting description")
    parser.add_argument("--num-workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout per query in seconds")
    parser.add_argument("--max-iterations", type=int, default=5, help="Max improvement iterations")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Number of runs per query")
    parser.add_argument("--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold")
    parser.add_argument("--holdout", type=float, default=0.4, help="Fraction of eval set to hold out for testing (0 to disable)")
    parser.add_argument("--model", default=None, help="Copilot model ID for evaluation and improvement (default: user's configured Copilot model)")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    parser.add_argument("--report", default="auto", help="Generate HTML report at this path (default: 'auto' for temp file, 'none' to disable)")
    parser.add_argument("--results-dir", default=None, help="Save results.json, report.html, and improvement logs to a timestamped subdirectory here")
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    try:
        eval_set = json.loads(Path(args.eval_set).read_text(encoding="utf-8"))
        if not (skill_path / "SKILL.md").exists():
            raise ValueError(f"No SKILL.md found at {skill_path}")
        if args.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        split_eval_set(eval_set, args.holdout)
        name, _, _ = parse_skill_md(skill_path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    try:
        calls_per_iteration = len(eval_set) * args.runs_per_query
        print(
            f"Planned usage: {calls_per_iteration} evaluation calls per iteration, "
            f"up to {calls_per_iteration * args.max_iterations} evaluation calls and "
            f"{2 * max(0, args.max_iterations - 1)} description-improvement calls; "
            f"up to {min(args.num_workers, calls_per_iteration)} concurrent evaluations.",
            file=sys.stderr,
        )
        # Create durable output storage before opening a live report.
        timestamp = time.strftime("%Y-%m-%d_%H%M%S")
        results_root = Path(args.results_dir) if args.results_dir else Path(args.eval_set).resolve().parent / "skill-creator-results"
        results_root.mkdir(parents=True, exist_ok=True)
        results_dir = Path(tempfile.mkdtemp(prefix=f"{timestamp}_", dir=results_root))

        if args.report != "none":
            if args.report == "auto":
                live_report_path = Path(tempfile.gettempdir()) / f"skill_description_report_{skill_path.name}_{results_dir.name}.html"
            else:
                live_report_path = Path(args.report)
            atomic_write_text(
                live_report_path,
                generate_html({"history": [], "best_score": "starting"}, auto_refresh=True, skill_name=name),
            )
            webbrowser.open(str(live_report_path))
        else:
            live_report_path = None
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    log_dir = results_dir / "logs"

    output = run_loop(
        eval_set=eval_set,
        skill_path=skill_path,
        description_override=args.description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        max_iterations=args.max_iterations,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        holdout=args.holdout,
        model=args.model,
        verbose=args.verbose,
        live_report_path=live_report_path,
        log_dir=log_dir,
    )

    # Save JSON output
    json_output = json.dumps(output, indent=2)
    print(json_output)
    try:
        atomic_write_text(results_dir / "results.json", json_output + "\n")

        # Write final HTML report (without auto-refresh)
        if live_report_path:
            final_report = generate_html(output, auto_refresh=False, skill_name=name)
            atomic_write_text(live_report_path, final_report)
            atomic_write_text(results_dir / "report.html", final_report)
            print(f"\nReport: {live_report_path}", file=sys.stderr)
    except OSError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    print(f"Results saved to: {results_dir}", file=sys.stderr)
    if output.get("error"):
        print(f"Error: {output['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

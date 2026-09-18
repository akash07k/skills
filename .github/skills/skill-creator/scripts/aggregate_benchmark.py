#!/usr/bin/env python3
"""
Aggregate individual run results into benchmark summary statistics.

Reads grading.json files from run directories and produces:
- run_summary with mean, stddev, min, max for each metric
- delta between with_skill and without_skill configurations

Usage:
    python -m scripts.aggregate_benchmark <benchmark_dir>

Example:
    python -m scripts.aggregate_benchmark benchmarks/2026-01-15T10-30-00/

The script reads the skill-creator workspace layout:

    <benchmark_dir>/
    └── eval-N/
        ├── with_skill/
        │   ├── run-1/grading.json
        │   └── run-2/grading.json
        └── without_skill/
            ├── run-1/grading.json
            └── run-2/grading.json
"""

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.utils import atomic_write_text, eval_sort_key

BASELINE_CONFIGS = {"baseline", "old_skill", "without_skill"}


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_analysis_notes(path: Path) -> list[str]:
    """Load analyzer observations from a JSON array of nonempty strings."""
    try:
        notes = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read analysis notes from {path}: {error}") from error
    if not isinstance(notes, list) or any(
        not isinstance(note, str) or not note.strip() for note in notes
    ):
        raise ValueError("Analysis notes must be a JSON array of nonempty strings")
    return notes


def load_existing_analysis_notes(path: Path) -> list[str]:
    """Preserve analyzer observations when regenerating an existing benchmark."""
    if not path.exists():
        return []
    try:
        benchmark = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(benchmark, dict):
            raise ValueError("benchmark.json must contain an object")
        notes = benchmark.get("notes", [])
        if not isinstance(notes, list) or any(
            not isinstance(note, str) or not note.strip() for note in notes
        ):
            raise ValueError("benchmark notes must be a JSON array of nonempty strings")
        return notes
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Warning: Could not preserve analysis notes from {path}: {error}", file=sys.stderr)
        return []


def directory_eval_id(eval_dir: Path, fallback: int) -> int:
    try:
        return int(eval_dir.name.split("-", 2)[1])
    except (IndexError, ValueError):
        return fallback


def calculate_stats(values: list[float]) -> dict:
    """Calculate mean, stddev, min, max for a list of values."""
    if not values:
        raise ValueError("Cannot calculate statistics without measured values")

    return {
        "mean": round(statistics.fmean(values), 4),
        "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4)
    }


def load_run_results(benchmark_dir: Path) -> dict:
    """
    Load all run results from a benchmark directory.

    Returns dict keyed by config name (e.g. "with_skill"/"without_skill",
    or "new_skill"/"old_skill"), each containing a list of run results.
    """
    if not list(benchmark_dir.glob("eval-*")):
        print(f"No eval directories found in {benchmark_dir}", file=sys.stderr)
        return {}

    results: dict[str, list] = {}

    for eval_idx, eval_dir in enumerate(sorted(benchmark_dir.glob("eval-*"))):
        metadata = {}
        fallback_eval_id = directory_eval_id(eval_dir, eval_idx)
        metadata_path = eval_dir / "eval_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as mf:
                    metadata = json.load(mf)
                    if not isinstance(metadata, dict):
                        raise ValueError("eval_metadata.json must contain an object")
                    eval_id = metadata.get("eval_id")
                    if eval_id is None:
                        eval_id = fallback_eval_id
                    elif not isinstance(eval_id, (int, str)) or isinstance(eval_id, bool):
                        print(
                            f"Warning: Invalid eval_id in {metadata_path}; "
                            f"using directory ID {fallback_eval_id}",
                            file=sys.stderr,
                        )
                        eval_id = fallback_eval_id
            except (json.JSONDecodeError, OSError, ValueError) as error:
                print(f"Warning: Invalid metadata in {metadata_path}: {error}", file=sys.stderr)
                metadata = {}
                eval_id = fallback_eval_id
        else:
            eval_id = fallback_eval_id

        # Discover config directories dynamically rather than hardcoding names
        for config_dir in sorted(eval_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            # Skip non-config directories (inputs, outputs, etc.)
            if not list(config_dir.glob("run-*")):
                continue
            config = config_dir.name

            for run_dir in sorted(config_dir.glob("run-*")):
                try:
                    run_number = int(run_dir.name.split("-", 1)[1])
                except (IndexError, ValueError):
                    print(f"Warning: Skipping invalid run directory name: {run_dir}", file=sys.stderr)
                    continue
                grading_file = run_dir / "grading.json"

                if not grading_file.exists():
                    print(f"Warning: grading.json not found in {run_dir}", file=sys.stderr)
                    continue

                try:
                    with open(grading_file, encoding="utf-8") as f:
                        grading = json.load(f)
                    if not isinstance(grading, dict):
                        raise ValueError("grading.json must contain an object")
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    print(f"Warning: Invalid JSON in {grading_file}: {e}", file=sys.stderr)
                    continue

                summary = grading.get("summary")
                if not isinstance(summary, dict):
                    print(f"Warning: Invalid summary in {grading_file}", file=sys.stderr)
                    continue
                pass_rate = summary.get("pass_rate")
                if (
                    not is_number(pass_rate)
                ):
                    print(
                        f"Warning: Missing or invalid summary.pass_rate in {grading_file}",
                        file=sys.stderr,
                    )
                    continue

                # Extract metrics
                result = {
                    "eval_id": eval_id,
                    "run_number": run_number,
                    "pass_rate": pass_rate,
                }
                for key in ("passed", "failed", "total"):
                    if is_number(summary.get(key)):
                        result[key] = summary[key]
                if isinstance(metadata.get("eval_name"), str) and metadata["eval_name"]:
                    result["eval_name"] = metadata["eval_name"]

                # Read the host-recorded timing file even when the grader copied duration.
                timing = grading.get("timing", {})
                if isinstance(timing, dict) and is_number(timing.get("total_duration_seconds")):
                    result["time_seconds"] = timing["total_duration_seconds"]
                timing_file = run_dir / "timing.json"
                if timing_file.exists():
                    try:
                        with open(timing_file, encoding="utf-8") as tf:
                            timing_data = json.load(tf)
                        if not isinstance(timing_data, dict):
                            raise ValueError("timing.json must contain an object")
                        if "time_seconds" not in result and is_number(timing_data.get("total_duration_seconds")):
                            result["time_seconds"] = timing_data["total_duration_seconds"]
                        if is_number(timing_data.get("total_tokens")):
                            result["tokens"] = timing_data["total_tokens"]
                    except (json.JSONDecodeError, OSError, ValueError) as error:
                        print(f"Warning: Invalid timing data in {timing_file}: {error}", file=sys.stderr)

                # Extract metrics if available
                metrics = grading.get("execution_metrics")
                if metrics is not None and not isinstance(metrics, dict):
                    print(f"Warning: Invalid execution_metrics in {grading_file}", file=sys.stderr)
                    metrics = {}
                metrics = metrics or {}
                for source, target in (
                    ("total_tool_calls", "tool_calls"),
                    ("errors_encountered", "errors"),
                ):
                    if is_number(metrics.get(source)):
                        result[target] = metrics[source]

                # Extract expectations — viewer requires fields: text, passed, evidence
                raw_expectations = grading.get("expectations", [])
                if not isinstance(raw_expectations, list):
                    print(f"Warning: Invalid expectations in {grading_file}", file=sys.stderr)
                    raw_expectations = []
                expectations = []
                for exp in raw_expectations:
                    if (
                        not isinstance(exp, dict)
                        or not isinstance(exp.get("text"), str)
                        or type(exp.get("passed")) is not bool
                    ):
                        print(
                            f"Warning: expectation in {grading_file} missing required fields "
                            f"(text, passed, evidence): {exp}",
                            file=sys.stderr,
                        )
                        continue
                    expectation = {"text": exp["text"], "passed": exp["passed"]}
                    if isinstance(exp.get("evidence"), str):
                        expectation["evidence"] = exp["evidence"]
                    expectations.append(expectation)
                result["expectations"] = expectations

                # Extract notes from user_notes_summary
                notes_summary = grading.get("user_notes_summary")
                if notes_summary is not None and not isinstance(notes_summary, dict):
                    print(f"Warning: Invalid user_notes_summary in {grading_file}", file=sys.stderr)
                    notes_summary = {}
                notes_summary = notes_summary or {}
                notes = []
                for field in ("uncertainties", "needs_review", "workarounds"):
                    values = notes_summary.get(field, [])
                    if not isinstance(values, list):
                        print(f"Warning: Invalid {field} notes in {grading_file}", file=sys.stderr)
                        continue
                    notes.extend(value for value in values if isinstance(value, str))
                result["notes"] = notes

                results.setdefault(config, []).append(result)

    return results


def ordered_configs(configs: list[str]) -> list[str]:
    """Place candidate configurations before known baseline configurations."""
    return (
        [config for config in configs if config not in BASELINE_CONFIGS]
        + [config for config in configs if config in BASELINE_CONFIGS]
    )


def run_count_metadata(results: dict[str, list]) -> int | dict:
    """Return runs per evaluation, preserving differences by configuration/eval."""
    counts = {}
    for config in ordered_configs(list(results)):
        per_eval = {}
        for result in results[config]:
            eval_id = str(result["eval_id"])
            per_eval[eval_id] = per_eval.get(eval_id, 0) + 1
        unique_counts = set(per_eval.values())
        counts[config] = next(iter(unique_counts)) if len(unique_counts) == 1 else per_eval
    if not counts:
        return 0
    flat_counts = [count for count in counts.values() if isinstance(count, int)]
    return flat_counts[0] if len(flat_counts) == len(counts) and len(set(flat_counts)) == 1 else counts


def aggregate_results(results: dict) -> dict:
    """
    Aggregate run results into summary statistics.

    Returns run_summary with stats for each configuration and delta.
    """
    run_summary = {}
    configs = ordered_configs([config for config, runs in results.items() if runs])

    for config in configs:
        runs = results[config]

        pass_rates = [r["pass_rate"] for r in runs]
        times = [r["time_seconds"] for r in runs if "time_seconds" in r]
        tokens = [r["tokens"] for r in runs if "tokens" in r]

        run_summary[config] = {
            "pass_rate": calculate_stats(pass_rates),
        }
        if len(times) == len(runs):
            run_summary[config]["time_seconds"] = calculate_stats(times)
        if len(tokens) == len(runs):
            run_summary[config]["tokens"] = calculate_stats(tokens)

    if len(configs) < 2:
        return run_summary

    primary = run_summary[configs[0]]
    baseline = run_summary[configs[1]]
    delta_pass_rate = primary.get("pass_rate", {}).get("mean", 0) - baseline.get("pass_rate", {}).get("mean", 0)
    delta_time = None
    if primary.get("time_seconds") and baseline.get("time_seconds"):
        delta_time = primary["time_seconds"]["mean"] - baseline["time_seconds"]["mean"]
    delta_tokens = None
    if primary.get("tokens") and baseline.get("tokens"):
        delta_tokens = primary["tokens"]["mean"] - baseline["tokens"]["mean"]

    run_summary["delta"] = {
        "pass_rate": f"{delta_pass_rate * 100:+.0f}%",
    }
    if delta_time is not None:
        run_summary["delta"]["time_seconds"] = f"{delta_time:+.1f}"
    if delta_tokens is not None:
        run_summary["delta"]["tokens"] = f"{delta_tokens:+.0f}"

    return run_summary


def generate_benchmark(
    benchmark_dir: Path,
    skill_name: str = "",
    skill_path: str = "",
    executor_model: str = "",
    analyzer_model: str = "",
    analysis_notes: list[str] | None = None,
) -> dict:
    """
    Generate complete benchmark.json from run results.
    """
    results = load_run_results(benchmark_dir)
    run_summary = aggregate_results(results)

    # Build runs array for benchmark.json
    runs = []
    for config in ordered_configs(list(results)):
        for result in results[config]:
            runs.append({
                "eval_id": result["eval_id"],
                "configuration": config,
                "run_number": result["run_number"],
                "result": {
                    "pass_rate": result["pass_rate"],
                },
                "expectations": result["expectations"],
                "notes": result["notes"]
            })
            if "tokens" in result:
                runs[-1]["result"]["tokens"] = result["tokens"]
            if "time_seconds" in result:
                runs[-1]["result"]["time_seconds"] = result["time_seconds"]
            for key in ("passed", "failed", "total", "tool_calls", "errors"):
                if key in result:
                    runs[-1]["result"][key] = result[key]
            if "eval_name" in result:
                runs[-1]["eval_name"] = result["eval_name"]

    # Determine eval IDs from results
    eval_ids = sorted(set(
        r["eval_id"]
        for config in results.values()
        for r in config
    ), key=eval_sort_key)

    benchmark = {
        "metadata": {
            "skill_name": skill_name or "<skill-name>",
            "skill_path": skill_path or "<path/to/skill>",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evals_run": eval_ids,
            "runs_per_configuration": run_count_metadata(results)
        },
        "runs": runs,
        "run_summary": run_summary,
        "notes": list(analysis_notes or []),
    }
    if executor_model:
        benchmark["metadata"]["executor_model"] = executor_model
    if analyzer_model:
        benchmark["metadata"]["analyzer_model"] = analyzer_model

    return benchmark


def generate_markdown(benchmark: dict) -> str:
    """Generate human-readable benchmark.md from benchmark data."""
    metadata = benchmark["metadata"]
    run_summary = benchmark["run_summary"]
    configs = [k for k in run_summary if k != "delta"]

    runs_per_configuration = metadata.get("runs_per_configuration", "?")
    if isinstance(runs_per_configuration, dict):
        def format_run_count(count):
            if isinstance(count, dict):
                return (
                    ", ".join(f"eval {eval_id}: {runs}" for eval_id, runs in count.items())
                    or "no graded runs"
                )
            return str(count)
        run_count_text = ", ".join(
            f"{config.replace('_', ' ')}: {format_run_count(runs_per_configuration[config])}"
            for config in ordered_configs(list(runs_per_configuration))
        )
    else:
        run_count_text = f"{runs_per_configuration} runs each per configuration"

    lines = [
        f"# Skill Benchmark: {metadata['skill_name']}",
        "",
        f"**Date**: {metadata['timestamp']}",
    ]
    if metadata.get("executor_model"):
        lines.append(f"**Executor model**: {metadata['executor_model']}")
    if metadata.get("analyzer_model"):
        lines.append(f"**Analyzer model**: {metadata['analyzer_model']}")
    lines.extend([
        f"**Evals**: {', '.join(map(str, metadata['evals_run']))} ({run_count_text})",
        "",
        "## Summary",
        "",
    ])

    if not configs:
        lines.append("No graded runs available.")
    else:
        labels = [config.replace("_", " ").title() for config in configs]
        delta = run_summary.get("delta", {})
        has_delta = bool(delta) and len(configs) >= 2
        if has_delta:
            lines.append(f"Delta compares {labels[0]} minus {labels[1]}.")
            lines.append("")

        headers = ["Metric", *labels]
        if has_delta:
            headers.append("Delta")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("--------" for _ in headers) + "|")

        def append_metric(name, key, formatter, delta_suffix=""):
            values = [formatter(run_summary[config].get(key)) for config in configs]
            if has_delta:
                value = delta.get(key)
                values.append(f"{value}{delta_suffix}" if value is not None else "Not available")
            lines.append("| " + " | ".join([name, *values]) + " |")

        def format_pass_rate(stats):
            if not stats:
                return "Not available"
            return f"{stats['mean']*100:.0f}% ± {stats['stddev']*100:.0f}%"

        def format_time(stats):
            if not stats:
                return "Not available"
            return f"{stats['mean']:.1f}s ± {stats['stddev']:.1f}s"

        def format_tokens(stats):
            if not stats:
                return "Not available"
            return f"{stats['mean']:.0f} ± {stats['stddev']:.0f}"

        append_metric("Pass Rate", "pass_rate", format_pass_rate)
        if any(run_summary[config].get("time_seconds") for config in configs):
            append_metric("Time", "time_seconds", format_time, "s")
        if any(run_summary[config].get("tokens") for config in configs):
            append_metric("Tokens", "tokens", format_tokens)

    # Notes section
    if benchmark.get("notes"):
        lines.extend([
            "",
            "## Notes",
            ""
        ])
        for note in benchmark["notes"]:
            lines.append(f"- {note}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate benchmark run results into summary statistics"
    )
    parser.add_argument(
        "benchmark_dir",
        type=Path,
        help="Path to the benchmark directory"
    )
    parser.add_argument(
        "--skill-name",
        default="",
        help="Name of the skill being benchmarked"
    )
    parser.add_argument(
        "--skill-path",
        default="",
        help="Path to the skill being benchmarked"
    )
    parser.add_argument(
        "--executor-model",
        default="",
        help="Actual model used for task runs, when known"
    )
    parser.add_argument(
        "--analyzer-model",
        default="",
        help="Actual model used for analysis, when known"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output path for benchmark.json (default: <benchmark_dir>/benchmark.json)"
    )
    parser.add_argument(
        "--notes",
        type=Path,
        help="JSON array of analyst observations to include in benchmark.json and benchmark.md"
    )

    args = parser.parse_args()

    if not args.benchmark_dir.exists():
        print(f"Directory not found: {args.benchmark_dir}")
        sys.exit(1)

    output_json = args.output or (args.benchmark_dir / "benchmark.json")
    output_md = output_json.with_suffix(".md")
    try:
        analysis_notes = (
            load_analysis_notes(args.notes)
            if args.notes
            else load_existing_analysis_notes(output_json)
        )
    except ValueError as error:
        parser.error(str(error))

    # Generate benchmark
    benchmark = generate_benchmark(
        args.benchmark_dir, args.skill_name, args.skill_path,
        args.executor_model, args.analyzer_model, analysis_notes,
    )

    atomic_write_text(output_json, json.dumps(benchmark, indent=2) + "\n")
    print(f"Generated: {output_json}")

    markdown = generate_markdown(benchmark)
    atomic_write_text(output_md, markdown + "\n")
    print(f"Generated: {output_md}")

    # Print summary
    run_summary = benchmark["run_summary"]
    configs = [k for k in run_summary if k != "delta"]
    delta = run_summary.get("delta", {})

    print("\nSummary:")
    for config in configs:
        pr = run_summary[config]["pass_rate"]["mean"]
        label = config.replace("_", " ").title()
        print(f"  {label}: {pr*100:.1f}% pass rate")
    if delta:
        print(f"  Delta:         {delta['pass_rate']}")


if __name__ == "__main__":
    main()

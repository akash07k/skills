# JSON Schemas

This document defines the JSON schemas used by skill-creator.

## Contents

- [Task evals](#evalsjson) and [eval metadata](#eval_metadatajson)
- [Trigger eval set and results](#trigger-eval-set-and-results)
- [Grading](#gradingjson), [metrics](#metricsjson), and [timing](#timingjson)
- [Benchmark](#benchmarkjson), [feedback](#feedbackjson), [comparison](#comparisonjson), and [analysis](#analysisjson)

Task runs use the Agent Skills layout `<workspace>/iteration-<N>/eval-<name>/<configuration>/outputs/`, which is a single run. For repeated runs, use `<workspace>/iteration-<N>/eval-<name>/<configuration>/run-<number>/outputs/` instead. When `run-<number>` folders exist, they replace the single-run layout for that configuration. The aggregator and viewer treat a folder as an eval when its name starts with `eval-` or when it contains `eval_metadata.json`. In the schemas below, `<run-dir>` is the `<configuration>` folder for a single run, or the `run-<number>` folder for repeated runs. Save `grading.json` and `timing.json` directly in `<run-dir>`, not in `outputs/`. The configuration name `delta` is reserved; the aggregator stops with an error if a configuration folder has that name.

**Field names:** New files use the Agent Skills names: `assertions` (statement strings in `evals.json` and `eval_metadata.json`) and `assertion_results` (graded objects in `grading.json` and `benchmark.json` runs). The scripts and viewer still read the old name `expectations` in all of these places, so older workspaces keep working. Do not write both names in one file.

---

## evals.json

Defines task-execution evals for a skill. Located at `evals/evals.json` within the skill directory. This is not the trigger eval list accepted by `run_eval.py` and `run_loop.py`.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's example prompt",
      "expected_output": "Description of expected result",
      "files": ["evals/files/sample1.pdf"],
      "assertions": [
        "The output includes X",
        "The skill used script Y"
      ]
    }
  ]
}
```

**Fields:**
- `skill_name`: Name matching the skill's frontmatter
- `evals[].id`: Unique integer identifier
- `evals[].prompt`: The task to execute
- `evals[].expected_output`: Human-readable description of success
- `evals[].files`: Optional list of input file paths (relative to skill root)
- `evals[].assertions`: List of verifiable statement strings; use `[]` until drafted. Older files may name this field `expectations`; it is still read.

---

## eval_metadata.json

Describes one task eval. Place the canonical file at `<workspace>/iteration-<N>/eval-<name>/eval_metadata.json`, shared by all configurations and runs. The aggregator reads this location for the task ID; the viewer finds metadata in run ancestors without traversing above its workspace root. Optional run-local copies must retain the same task ID, prompt, and assertions. With this file present, the eval folder can have any name.

```json
{
  "eval_id": 1,
  "eval_name": "descriptive-name-here",
  "prompt": "User's example prompt",
  "assertions": [
    "The output includes X",
    "The skill used script Y"
  ]
}
```

- `eval_id`: The matching task's `evals[].id`
- `eval_name`: Human-readable name describing the test
- `prompt`: The task's prompt
- `assertions`: The same statement strings as in `evals.json`, or `[]` before drafting (legacy name `expectations` is still read)

These input statements are not grading results. `grading.json` uses an `assertion_results` array of objects with exactly `text`, `passed`, and `evidence`.

---

## Trigger eval set and results

Description optimization uses a separate, nonempty JSON list:

```json
[
  {"query": "Please do this task", "should_trigger": true},
  {"query": "Please do this other task", "should_trigger": false}
]
```

- `query`: Nonempty user prompt sent to the selected evaluation host (the
  bundled trigger runner currently sends it to Copilot CLI)
- `should_trigger`: JSON boolean, not a string

Duplicate query text is allowed and remains separate entries, including entries with different labels. Each entry receives `runs_per_query` runs. Repeated text can appear in both the train set and the held-out validation set (called "test" in script output); remove accidental duplicates if they would weaken the holdout.

`scripts/run_eval.py` returns the following compatible result shape:

```json
{
  "skill_name": "example-skill",
  "description": "Description being evaluated",
  "copilot_cli_version": "GitHub Copilot CLI 1.0.86.",
  "results": [
    {
      "eval_id": 0,
      "query": "Please do this task",
      "should_trigger": true,
      "trigger_rate": 1.0,
      "triggers": 3,
      "runs": 3,
      "pass": true
    },
    {
      "eval_id": 1,
      "query": "Please do this other task",
      "should_trigger": false,
      "trigger_rate": 0.0,
      "triggers": 0,
      "runs": 3,
      "pass": true
    }
  ],
  "summary": {"total": 2, "passed": 2, "failed": 0}
}
```

- `eval_id`: Zero-based position in the original trigger input list, assigned by the evaluator (not a task eval ID). Results retain input order, irrespective of worker completion order.
- `pass`: Positive entries pass when `trigger_rate > trigger_threshold` (strictly greater); negative entries pass when it is below that threshold.
- `summary`: Counts entries, not distinct query strings.
- `copilot_cli_version`: Observed CLI version for reproducibility, or `null` if
  the nonfatal version probe was unavailable.

The `copilot_cli_version` field records the bundled runner's current backend.
It describes the evaluation environment, not the skill's target client or
portability.

`scripts/run_loop.py` keeps these IDs and original relative order in every iteration's `train_results` and `test_results`. The improver receives only train rows and history with test fields removed. Match report rows by `eval_id`, not query text.

The evaluator loads a temporary candidate through `--add-dir`, runs the query from that isolated workspace (its own git root, with a throwaway `HOME` and `COPILOT_HOME`), and scores the first skill decision; up to 8 views of other paths count as exploration. When the CLI emits `session.skills_loaded`, the evaluator treats the events as incremental snapshots, rejects an explicitly disabled candidate, and rejects a reported original-skill conflict; some CLI versions omit that event. The temporary name uses an `-eval-<id>` suffix, making absolute scores approximate while keeping relative comparisons consistent. Only `skill`, `view`, and the never-approved write tools `create`, `edit`, and `apply_patch` are available; a write-tool call before a skill decision is a negative unless it only touches the CLI profile, `.git`, or `prompt.txt` (scratch exploration), and no other orientation calls are possible; an exact candidate skill name or candidate file path counts as selection. This measures trigger choice, not task completion or output quality. A no-tool answer requires a successful terminal `result` before scoring negative. Timeouts, failed CLI launches/exits, authentication/model errors, invalid discovery state, and invalid or incomplete event output before a decision are failures, not no-trigger observations. Do not infer selection from assistant prose alone.

---

## grading.json

Output from the grader agent. Located at `<run-dir>/grading.json`.

```json
{
  "assertion_results": [
    {
      "text": "The output includes the name 'John Smith'",
      "passed": true,
      "evidence": "Found in transcript Step 3: 'Extracted names: John Smith, Sarah Johnson'"
    },
    {
      "text": "The spreadsheet has a SUM formula in cell B10",
      "passed": false,
      "evidence": "No spreadsheet was created. The output was a text file."
    }
  ],
  "summary": {
    "passed": 1,
    "failed": 1,
    "total": 2,
    "pass_rate": 0.5
  },
  "execution_metrics": {
    "tool_calls": {
      "view": 5,
      "apply_patch": 2,
      "powershell": 8
    },
    "total_tool_calls": 15,
    "total_steps": 6,
    "errors_encountered": 0,
    "transcript_chars": 3200
  },
  "timing": {
    "executor_duration_seconds": 165.0,
    "grader_duration_seconds": 26.0,
    "total_duration_seconds": 191.0
  },
  "claims": [
    {
      "claim": "The form has 12 fillable fields",
      "type": "factual",
      "verified": true,
      "evidence": "Counted 12 fields in field_info.json"
    }
  ],
  "user_notes_summary": {
    "uncertainties": ["Used 2023 data, may be stale"],
    "needs_review": [],
    "workarounds": ["Fell back to text overlay for non-fillable fields"]
  },
  "eval_feedback": {
    "suggestions": [
      {
        "assertion": "The output includes the name 'John Smith'",
        "reason": "A hallucinated document that mentions the name would also pass"
      }
    ],
    "overall": "Assertions check presence but not correctness."
  }
}
```

**Fields:**
- `assertion_results[]`: Graded objects with `text` (statement string), `passed` (boolean), and `evidence` (string), not the statement strings used in task input files. Older grading files name this array `expectations`; the aggregator and viewer still read it when `assertion_results` is absent.
- `summary`: Aggregate pass/fail counts
- `execution_metrics`: Tool usage and execution details (from executor's metrics.json)
- `timing`: Wall clock timing (from timing.json). `total_duration_seconds` here includes grader time, so the aggregator uses it only when `timing.json` and `executor_duration_seconds` are both unavailable.
- `claims`: Extracted and verified claims from the output
- `user_notes_summary`: Issues flagged by the executor
- `eval_feedback`: (optional) Improvement suggestions for the evals, only present when the grader identifies issues worth raising

---

## Executor records

When available, save `<run-dir>/transcript.md` with the original prompt under
an `## Eval Prompt` heading. This lets the reviewer recover the prompt if
`eval_metadata.json` is unavailable. Save executor uncertainties, review needs,
and workarounds to `<run-dir>/outputs/user_notes.md`; omit the file when there
are no notes.

## metrics.json

Output from the executor agent. Located at `<run-dir>/outputs/metrics.json`.

```json
{
  "tool_calls": {
    "view": 5,
    "apply_patch": 3,
    "powershell": 8,
    "glob": 2,
    "rg": 0
  },
  "total_tool_calls": 18,
  "total_steps": 6,
  "files_created": ["filled_form.pdf", "field_values.json"],
  "errors_encountered": 0,
  "transcript_chars": 3200
}
```

**Fields:**
- `tool_calls`: Count per tool name as observed in the evaluation host; the example names are illustrative, not required keys
- `total_tool_calls`: Sum of all tool calls
- `total_steps`: Number of major execution steps
- `files_created`: List of output files created
- `errors_encountered`: Number of errors during execution
- `transcript_chars`: Character count of transcript

---

## timing.json

Wall clock timing for a run. Located at `<run-dir>/timing.json`.

**How to capture:** Save usage and duration reported by the evaluation host promptly. If token counts are unavailable, leave them unreported rather than inventing values or substituting zero. Measure elapsed time when necessary and disclose missing metrics in benchmark notes; do not assume every host supplies the same task notifications.

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3,
  "executor_start": "2026-01-15T10:30:00Z",
  "executor_end": "2026-01-15T10:32:45Z",
  "executor_duration_seconds": 165.0,
  "grader_start": "2026-01-15T10:32:46Z",
  "grader_end": "2026-01-15T10:33:12Z",
  "grader_duration_seconds": 26.0
}
```

The Agent Skills minimum is `total_tokens` and `duration_ms`; the other fields are optional. The aggregator takes run time from the first available value in this order:

1. `timing.json` `total_duration_seconds`
2. `timing.json` `duration_ms` / 1000
3. `timing.json` `executor_duration_seconds`
4. `grading.json` `timing.executor_duration_seconds`
5. `grading.json` `timing.total_duration_seconds`

Tokens come from `timing.json` `total_tokens`.

---

## benchmark.json

Output from Benchmark mode. Located at `<workspace>/iteration-N/benchmark.json`.

```json
{
  "metadata": {
    "skill_name": "pdf",
    "skill_path": "C:\\project\\.github\\skills\\pdf",
    "timestamp": "2026-01-15T10:30:00Z",
    "evals_run": [1, 2, 3],
    "runs_per_configuration": 3
  },

  "runs": [
    {
      "eval_id": 1,
      "eval_name": "Ocean",
      "configuration": "with_skill",
      "run_number": 1,
      "result": {
        "pass_rate": 0.85,
        "passed": 6,
        "failed": 1,
        "total": 7,
        "time_seconds": 42.5,
        "tokens": 3800,
        "tool_calls": 18,
        "errors": 0
      },
      "assertion_results": [
        {"text": "...", "passed": true, "evidence": "..."}
      ],
      "notes": [
        "Used 2023 data, may be stale",
        "Fell back to text overlay for non-fillable fields"
      ]
    }
  ],

  "run_summary": {
    "with_skill": {
      "pass_rate": {"mean": 0.85, "stddev": 0.05, "min": 0.80, "max": 0.90},
      "time_seconds": {"mean": 45.0, "stddev": 12.0, "min": 32.0, "max": 58.0},
      "tokens": {"mean": 3800, "stddev": 400, "min": 3200, "max": 4100}
    },
    "without_skill": {
      "pass_rate": {"mean": 0.35, "stddev": 0.08, "min": 0.28, "max": 0.45},
      "time_seconds": {"mean": 32.0, "stddev": 8.0, "min": 24.0, "max": 42.0},
      "tokens": {"mean": 2100, "stddev": 300, "min": 1800, "max": 2500}
    },
    "delta": {
      "pass_rate": 0.5,
      "time_seconds": 13.0,
      "tokens": 1700
    }
  },

  "skipped_runs": [],

  "notes": [
    "Assertion 'Output is a PDF file' passes 100% in both configurations - may not differentiate skill value",
    "Eval 3 shows high variance (50% ± 40%) - may be flaky or model-dependent",
    "Without-skill runs consistently fail on table extraction expectations",
    "Skill adds 13s average execution time but improves pass rate by 50%"
  ]
}
```

**Fields:**
- `metadata`: Information about the benchmark run
  - `skill_name`: Name of the skill
  - `skill_path`: Present only when `--skill-path` is given. There is no placeholder.
  - `executor_model`, `analyzer_model`: Optional actual model identifiers reported by the execution and analysis hosts. Pass `--executor-model` and `--analyzer-model` to the aggregator when known. Omit them when unknown; do not report placeholders or assumed configured defaults.
  - `timestamp`: When the benchmark was run
  - `evals_run`: List of eval names or IDs
  - `runs_per_configuration`: Number of runs per evaluation and configuration (e.g. `3`), or an object keyed by configuration when their run counts differ. If a configuration varies across evaluations, its value is an object keyed by eval ID.
- `runs[]`: Individual run results
  - `eval_id`: Numeric eval identifier
  - `eval_name`: Human-readable eval name (used as section header in the viewer)
  - `configuration`: Configuration directory name, normally `"with_skill"` and `"without_skill"` for a new skill, or `"with_skill"` and `"old_skill"` when comparing an existing skill with its snapshot. Keep these names consistent in `runs` and `run_summary`.
  - `run_number`: Integer run number (1, 2, 3...)
  - `result`: Nested object with required `pass_rate` and optional `passed`, `failed`, `total`, `tool_calls`, `errors`, `time_seconds`, and `tokens`. Optional execution measurements remain absent when the grader or host did not supply them; absence is not reported as zero. `tokens` is included only when the host supplied an actual token count.
  - `assertion_results`: The graded objects copied from `grading.json`. The viewer also reads the legacy name `expectations`.
- `run_summary`: Statistical aggregates per configuration
  - Configuration keys (for example, `with_skill` / `without_skill`, or `with_skill` / `old_skill`): Each contains `pass_rate` and, when every run has the measurement, `time_seconds` and `tokens` objects with `mean` and `stddev` fields
  - Every graded configuration is shown in the Markdown and HTML summary.
  - `delta`: Optional numeric differences of the means: `pass_rate` as a fraction (`0.5` means +50 percentage points), `time_seconds` in seconds, and `tokens`. A metric is omitted when either configuration lacks it. It is present only when at least two configurations have graded runs and compares the first configuration with the second. The Markdown and viewer show these as `+50%`, `+13.0s`, and `+1700`. The viewer still accepts older string deltas such as `"+50%"`.
- `skipped_runs`: Always present; `[]` when every run was used. Each entry is `{eval_id, configuration, run_number, path, reason}`, where `path` is relative with forward slashes. Reasons are `"grading.json not found"`, `"invalid grading.json: ..."` and `"no usable summary and no valid assertion results"`. When the list is not empty, `benchmark.md` has a `## Skipped runs` section and the viewer's Benchmark tab shows them.
- `notes`: Freeform observations from the analyzer

The aggregator takes each run's pass counts from `grading.json`. When `summary` is missing, it computes the counts from `assertion_results` (or `expectations`). When `summary` disagrees with the assertions, it prints a warning and uses the counts computed from the assertions. A pass rate within 0.005 of the computed value counts as agreeing.

**Important:** The viewer reads these field names exactly. Using `config` instead of `configuration`, or putting `pass_rate` at the top level of a run instead of nested under `result`, will cause the viewer to show empty/zero values. Always reference this schema when generating benchmark.json manually.

---

## feedback.json

Human review feedback. Located at `<workspace>/iteration-<N>/feedback.json`. The Agent Skills format is a flat map from eval folder name to feedback text. An empty string means the reviewer had no complaint:

```json
{
  "eval-top-months-chart": "The chart is missing axis labels.",
  "eval-clean-missing-emails": ""
}
```

The review viewer saves a richer format. Each `run_id` is the run path relative to the workspace, with path separators replaced by `-` (for example, `eval-top-months-chart-with_skill`):

```json
{
  "reviews": [
    {"run_id": "eval-top-months-chart-with_skill", "feedback": "The chart is missing axis labels.", "timestamp": "2026-01-15T10:40:00Z"}
  ],
  "status": "complete"
}
```

- `reviews[]`: Objects with exactly `run_id` (nonempty string), `feedback` (string), and optional `timestamp` (string)
- `status`: Optional; `"in_progress"` or `"complete"`

The viewer server rejects other fields, wrong types, request bodies larger than 1 MB, and `run_id` values that are not runs in the workspace (IDs already saved in `feedback.json` stay accepted). Every `/api/` error is JSON, `{"error": "..."}`. With `--previous-workspace`, `generate_review` reads both formats. A flat-map key that names an eval folder applies to every configuration and run in that eval. A key that names a run ID applies to that run only.

---

## comparison.json

Output from blind comparator. Located at `<grading-dir>/comparison-N.json`.
`winner` is `"A"`, `"B"`, or `"TIE"`. A tie has no winner or loser and skips
post-hoc `analysis.json` generation. `assertion_results` (assertion checks per
output) is included only when assertions were supplied. It uses the same name
as `grading.json`.

```json
{
  "winner": "A",
  "reasoning": "Output A provides a complete solution with proper formatting and all required fields. Output B is missing the date field and has formatting inconsistencies.",
  "rubric": {
    "A": {
      "content": {"correctness": 5, "completeness": 5, "accuracy": 4},
      "structure": {"organization": 4, "formatting": 5, "usability": 4},
      "content_score": 4.7,
      "structure_score": 4.3,
      "overall_score": 9.0
    },
    "B": {
      "content": {"correctness": 3, "completeness": 2, "accuracy": 3},
      "structure": {"organization": 3, "formatting": 2, "usability": 3},
      "content_score": 2.7,
      "structure_score": 2.7,
      "overall_score": 5.4
    }
  },
  "output_quality": {
    "A": {
      "score": 9,
      "strengths": ["Complete solution", "Well-formatted", "All fields present"],
      "weaknesses": ["Minor style inconsistency in header"]
    },
    "B": {
      "score": 5,
      "strengths": ["Readable output", "Correct basic structure"],
      "weaknesses": ["Missing date field", "Formatting inconsistencies", "Partial data extraction"]
    }
  },
  "assertion_results": {
    "A": {
      "passed": 4,
      "total": 5,
      "pass_rate": 0.80,
      "details": [
        {"text": "Output includes name", "passed": true}
      ]
    },
    "B": {
      "passed": 3,
      "total": 5,
      "pass_rate": 0.60,
      "details": [
        {"text": "Output includes name", "passed": true}
      ]
    }
  }
}
```

---

## analysis.json

Output from post-hoc analyzer. Located at `<grading-dir>/analysis.json`.
This file is generated only when `comparison.json` selects `A` or `B`, not
when it selects `TIE`.

```json
{
  "comparison_summary": {
    "winner": "A",
    "winner_skill": "path/to/winner/skill",
    "loser_skill": "path/to/loser/skill",
    "comparator_reasoning": "Brief summary of why comparator chose winner"
  },
  "winner_strengths": [
    "Clear step-by-step instructions for handling multi-page documents",
    "Included validation script that caught formatting errors"
  ],
  "loser_weaknesses": [
    "Vague instruction 'process the document appropriately' led to inconsistent behavior",
    "No script for validation, agent had to improvise"
  ],
  "instruction_following": {
    "winner": {"score": 9, "issues": ["Minor: skipped optional logging step"]},
    "loser": {
      "score": 6,
      "issues": ["Did not use the skill's formatting template", "Invented own approach instead of following step 3"]
    }
  },
  "improvement_suggestions": [
    {
      "priority": "high",
      "category": "instructions",
      "suggestion": "Replace 'process the document appropriately' with explicit steps",
      "expected_impact": "Would eliminate ambiguity that caused inconsistent behavior"
    }
  ],
  "transcript_insights": {
    "winner_execution_pattern": "Read skill -> Followed 5-step process -> Used validation script",
    "loser_execution_pattern": "Read skill -> Unclear on approach -> Tried 3 different methods"
  }
}
```

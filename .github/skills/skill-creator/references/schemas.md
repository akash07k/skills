# JSON Schemas

This document defines the JSON schemas used by skill-creator.

## Contents

- [Task evals](#evalsjson) and [eval metadata](#eval_metadatajson)
- [Trigger eval set and results](#trigger-eval-set-and-results)
- [Grading](#gradingjson), [metrics](#metricsjson), and [timing](#timingjson)
- [Benchmark](#benchmarkjson), [comparison](#comparisonjson), and [analysis](#analysisjson)

Task runs use `<workspace>/iteration-<N>/eval-<ID>-<descriptive-name>/<configuration>/run-<number>/outputs/`. Keep the `eval-` prefix and use `run-1` even for a single run; the aggregator discovers these names. In the schemas below, `<run-dir>` is that `run-<number>` directory. Save `grading.json` and `timing.json` directly in `<run-dir>`, not in `outputs/`. A direct `<configuration>/outputs/` layout is not collected by the benchmark aggregator.

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
      "expectations": [
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
- `evals[].expectations`: List of verifiable statement strings; use `[]` until drafted. The field is `expectations`, not `assertions`.

---

## eval_metadata.json

Describes one task eval. Place the canonical file at `<workspace>/iteration-<N>/eval-<ID>-<descriptive-name>/eval_metadata.json`, shared by all configurations and runs. The aggregator reads this location for the task ID; the viewer finds metadata in run ancestors without traversing above its workspace root. Optional run-local copies must retain the same task ID, prompt, and expectations.

```json
{
  "eval_id": 1,
  "eval_name": "descriptive-name-here",
  "prompt": "User's example prompt",
  "expectations": [
    "The output includes X",
    "The skill used script Y"
  ]
}
```

- `eval_id`: The matching task's `evals[].id`
- `eval_name`: Human-readable name describing the test
- `prompt`: The task's prompt
- `expectations`: The same statement strings as in `evals.json`, or `[]` before drafting

These input statements are not grading results. `grading.json` uses an `expectations` array of objects with exactly `text`, `passed`, and `evidence`.

---

## Trigger eval set and results

Description optimization uses a separate, nonempty JSON list:

```json
[
  {"query": "Please do this task", "should_trigger": true},
  {"query": "Please do this other task", "should_trigger": false}
]
```

- `query`: Nonempty string given to GitHub Copilot CLI
- `should_trigger`: JSON boolean, not a string

Duplicate query text is allowed and remains separate entries, including entries with different labels. Each entry receives `runs_per_query` runs. Repeated text can appear in both train and held-out test; remove accidental duplicates if they would weaken the holdout.

`scripts.run_eval` returns the following compatible result shape:

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
- `pass`: Positive entries pass when `trigger_rate >= trigger_threshold`; negative entries pass when it is below that threshold.
- `summary`: Counts entries, not distinct query strings.
- `copilot_cli_version`: Observed CLI version for reproducibility, or `null` if
  the nonfatal version probe was unavailable.

`scripts.run_loop` keeps these IDs and original relative order in every iteration's `train_results` and `test_results`. The improver receives only train rows and history with test fields removed. Match report rows by `eval_id`, not query text.

The evaluator loads a temporary candidate through `--add-dir`, runs the query from that isolated workspace, and scores the first tool decision. When the CLI emits `session.skills_loaded`, the evaluator also validates enabled discovery and rejects a reported original-skill conflict; newer CLI versions may omit that event. The temporary name uses an `-eval-<id>` suffix, making absolute scores approximate while keeping relative comparisons consistent. Only `skill` and `view` are available, preventing unrelated orientation calls from becoming false negative trigger decisions; an exact candidate skill name or candidate file path counts as selection. This measures trigger choice, not task completion or output quality. A no-tool answer requires a successful terminal `result` before scoring negative. Timeouts, failed CLI launches/exits, authentication/model errors, explicit failed discovery, and invalid or incomplete event output before a decision are failures, not no-trigger observations. Do not infer selection from assistant prose alone.

---

## grading.json

Output from the grader agent. Located at `<run-dir>/grading.json`.

```json
{
  "expectations": [
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
- `expectations[]`: Graded objects with `text` (statement string), `passed` (boolean), and `evidence` (string), not the statement strings used in task input files
- `summary`: Aggregate pass/fail counts
- `execution_metrics`: Tool usage and execution details (from executor's metrics.json)
- `timing`: Wall clock timing (from timing.json)
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
- `tool_calls`: Count per tool name as observed in the Copilot host; the example names are illustrative, not required keys
- `total_tool_calls`: Sum of all tool calls
- `total_steps`: Number of major execution steps
- `files_created`: List of output files created
- `errors_encountered`: Number of errors during execution
- `transcript_chars`: Character count of transcript

---

## timing.json

Wall clock timing for a run. Located at `<run-dir>/timing.json`.

**How to capture:** Save usage and duration reported by the Copilot host promptly. If token counts are unavailable, leave them unreported rather than inventing values or substituting zero. Measure elapsed time when necessary and disclose missing metrics in benchmark notes; do not assume every host supplies the same task notifications.

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
      "expectations": [
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
      "pass_rate": "+50%",
      "time_seconds": "+13.0",
      "tokens": "+1700"
    }
  },

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
  - `executor_model`, `analyzer_model`: Optional actual Copilot model identifiers. Pass `--executor-model` and `--analyzer-model` to the aggregator when known. Omit them when unknown; do not report placeholders or assumed configured defaults.
  - `timestamp`: When the benchmark was run
  - `evals_run`: List of eval names or IDs
  - `runs_per_configuration`: Number of runs per evaluation and configuration (e.g. `3`), or an object keyed by configuration when their run counts differ. If a configuration varies across evaluations, its value is an object keyed by eval ID.
- `runs[]`: Individual run results
  - `eval_id`: Numeric eval identifier
  - `eval_name`: Human-readable eval name (used as section header in the viewer)
  - `configuration`: Configuration directory name, normally `"with_skill"` and `"without_skill"` for a new skill, or `"with_skill"` and `"old_skill"` when comparing an existing skill with its snapshot. Keep these names consistent in `runs` and `run_summary`.
  - `run_number`: Integer run number (1, 2, 3...)
  - `result`: Nested object with required `pass_rate` and optional `passed`, `failed`, `total`, `tool_calls`, `errors`, `time_seconds`, and `tokens`. Optional execution measurements remain absent when the grader or host did not supply them; absence is not reported as zero. `tokens` is included only when the host supplied an actual token count.
- `run_summary`: Statistical aggregates per configuration
  - Configuration keys (for example, `with_skill` / `without_skill`, or `with_skill` / `old_skill`): Each contains `pass_rate` and, when every run has the measurement, `time_seconds` and `tokens` objects with `mean` and `stddev` fields
  - Every graded configuration is shown in the Markdown and HTML summary.
  - `delta`: Optional differences such as `"+50%"` for percentage-point pass-rate change, `"+13.0"` seconds, and `"+1700"` tokens. It is present only when at least two configurations have graded runs and compares the first configuration with the second.
- `notes`: Freeform observations from the analyzer

**Important:** The viewer reads these field names exactly. Using `config` instead of `configuration`, or putting `pass_rate` at the top level of a run instead of nested under `result`, will cause the viewer to show empty/zero values. Always reference this schema when generating benchmark.json manually.

---

## comparison.json

Output from blind comparator. Located at `<grading-dir>/comparison-N.json`.
`winner` is `"A"`, `"B"`, or `"TIE"`. A tie has no winner or loser and skips
post-hoc `analysis.json` generation.

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
  "expectation_results": {
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

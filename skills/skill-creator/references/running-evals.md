# Running and reviewing task evals

Read this file when you run a skill's test prompts, grade them, build the
benchmark, or show the results to the user. Run the steps as one sequence and
do not stop partway through.

## Contents

- [Prerequisites and workspace layout](#prerequisites-and-workspace-layout)
- [Step 1: Start paired runs](#step-1-start-paired-runs)
- [Step 2: Draft assertions while runs are in progress](#step-2-draft-assertions-while-runs-are-in-progress)
- [Step 3: Capture timing data](#step-3-capture-timing-data)
- [Step 4: Grade, aggregate, and build the viewer](#step-4-grade-aggregate-and-build-the-viewer)
- [What the user sees in the viewer](#what-the-user-sees-in-the-viewer)
- [Step 5: Read the feedback](#step-5-read-the-feedback)

## Prerequisites and workspace layout

Use Python 3.13 or later. In the commands below, `scripts/` is this skill's
scripts folder. Use its full path; the scripts work from any directory.
On Windows, check `python --version`. If `python` is only a WindowsApps alias, run
`py --list-paths` to find an installed interpreter, then call it with
`& "C:\path\to\python.exe"`. In PowerShell, quote Windows paths and write each
command on one line. Do not use Bash `\` line continuations.

Do not use `/skill-test` or another testing skill for these runs. The
aggregator and viewer need the workspace layout and grading files described
here, and other tools do not make them.

Put the results in `<skill-name>-workspace/`, next to the skill directory. Use
this layout:

```text
<workspace>/iteration-<N>/
├── eval-<ID>-<descriptive-name>/
│   ├── eval_metadata.json
│   ├── with_skill/
│   │   └── run-1/
│   │       ├── outputs/
│   │       ├── transcript.md
│   │       ├── timing.json
│   │       └── grading.json
│   └── without_skill/   (or old_skill/)
│       └── run-1/ ...
├── benchmark.json
└── feedback.json
```

Add `run-2/`, `run-3/` and so on for repeated runs. The aggregator also reads
the Agent Skills specification layout, `<eval-dir>/<configuration>/outputs/`
without `run-<N>/` directories. It reads that layout as one run. When a
directory contains `eval_metadata.json`, it does not need the `eval-` prefix.
Do not name a configuration `delta`. That name is reserved for the comparison
in `benchmark.json`.

## Step 1: Start paired runs

If the host supports independent subagents, start the with-skill run and the
baseline run for each test case at the same time. Use the same prompt, inputs
and model for both runs, and keep their outputs in separate directories. Make
sure that the baseline cannot find the candidate skill through its working
directory or its installed skills. If parallel runs are not possible, run the
sessions one after another. For a host with only one agent, see
`references/host-adaptations.md`.

**With-skill run:**

```text
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>-<descriptive-name>/with_skill/run-1/outputs/
- Outputs to save: <what the user cares about, e.g. "the .docx file">
```

**Baseline run.** Use the same prompt. The baseline depends on the task:

- **New skill:** Use no skill. Save the outputs to `without_skill/run-1/outputs/`.
- **Existing skill:** Use the old version. Before you edit the skill, copy the
  full skill directory to `<workspace>/skill-snapshot/`. Point the baseline at
  that copy and save the outputs to `old_skill/run-1/outputs/`.

For each run, also keep the evidence that the grader needs:

- If the host makes a transcript available, save it as `transcript.md` next to
  `outputs/`. Start its prompt section with `## Eval Prompt` so that the viewer
  can find it.
- If the executor reports metrics, save them to `outputs/metrics.json`. Use the
  format in `references/schemas.md`. Leave out a measurement that is not
  available. Do not write zero instead.
- If the executor found uncertainties or used workarounds, write them to
  `outputs/user_notes.md`. Do not create an empty file.

Write an `eval_metadata.json` file for each test case. Give each eval a name
that describes what it tests, and keep the prefix and the ID in the directory
name, for example `eval-1-chart-labels/`. Create the file again for each new
or changed prompt in each iteration. These files are not copied from one
iteration to the next.

```json
{
  "eval_id": 1,
  "eval_name": "chart-labels",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

## Step 2: Draft assertions while runs are in progress

Use the time while the runs are in progress. Draft assertions for each test
case and explain them to the user. If `evals/evals.json` already has
assertions, review them and explain what each one checks.

A good assertion can be checked objectively, and its text says what it checks.
The text appears in the benchmark viewer, so a reader must understand it
without other context. Avoid brittle assertions that require an exact phrase,
such as "the output says exactly 'Total Revenue: X'". A correct output with
other wording would fail. Remove assertions that pass with and without the
skill, because they do not measure the skill. For subjective qualities, such as writing style or
design, use human review instead of assertions.

When the assertions are ready, put the string lists in the `assertions` field
of `eval_metadata.json` and of `evals/evals.json`. These are the inputs. The
grader writes its results to a separate `assertion_results` list in
`grading.json`. Tell the user what the viewer shows: the outputs, and the
benchmark numbers.

## Step 3: Capture timing data

When a run completes, save the token count and duration from the host to
`timing.json` in the run directory. Do this right away, because some hosts do
not keep this data for long.

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

If the host does not report time, measure the elapsed time yourself. Do not
invent token counts, and do not write zero for a value you do not have. When
you explain the benchmark, mention which values are missing. The aggregator
reads time from `timing.json` first. If that file has no time, it uses the
`executor_duration_seconds` value from `grading.json`.

## Step 4: Grade, aggregate, and build the viewer

When all the runs are complete:

1. **Grade each run.** Start a grader subagent, or grade the run yourself,
   using the instructions in `agents/grader.md`. Save the results to
   `grading.json` in the run directory. Each item in `assertion_results` must
   have the fields `text`, `passed` and `evidence`. The viewer reads only these
   field names. It still reads the older `expectations` field for old results.
   If a script can check an assertion, write and run the script. Scripts are
   faster, more reliable and you can use them again in later iterations.

2. **Aggregate the results.** Run:

   ```powershell
   python scripts/aggregate_benchmark.py "<workspace>/iteration-N" --skill-name "<name>"
   ```

   This writes `benchmark.json` and `benchmark.md`. They contain the pass rate
   for each configuration, with the mean and standard deviation. When every
   run has time and token data, they also contain those values. Delta values
   are numbers, and the aggregator calculates them only when two
   configurations have graded runs. A missing baseline is not counted as zero.
   Add `--executor-model` or `--analyzer-model` only when you know the actual
   model IDs. If no eval runs are found, the script fails with exit code 1.
   Put each with-skill configuration before its baseline. If a grading file
   has no `summary`, the counts come from its assertions. If the summary and
   the assertions disagree, the assertions win and a warning is printed.
   Runs that cannot be scored are listed under "Skipped runs" in
   `benchmark.md`; check that list before you report results.

3. **Do an analyst pass.** Read the benchmark and look for patterns that the
   averages hide. Use the "Analyzing Benchmark Results" section of
   `agents/analyzer.md`. Examples are assertions that pass with and without
   the skill, evals with high variance, and trade-offs between time and
   tokens. Save the JSON array of notes to
   `<workspace>/iteration-N/analysis_notes.json`. Then run the aggregator
   again with `--notes "<workspace>/iteration-N/analysis_notes.json"`.

4. **Build the viewer.** Use `scripts/generate_review.py`. Do not write custom
   HTML.

   ```powershell
   python scripts/generate_review.py "<workspace>/iteration-N" --skill-name "my-skill" --benchmark "<workspace>/iteration-N/benchmark.json"
   ```

   For iteration 2 and later, also add
   `--previous-workspace "<workspace>/iteration-<N-1>"`. Keep the same eval
   directory names in every iteration, because previous outputs and feedback
   are matched by directory path.

   The script starts a local server on 127.0.0.1 and prints the URL. It does
   not open a browser. Run it in the foreground, or use the host's managed
   background mode and keep the session handle. Do not use `nohup`, and do not
   hide startup errors. To write a standalone HTML file without a server, add
   `--static "<workspace>/iteration-N/review.html"`. Use this on headless or
   remote hosts.

5. **Ask before you open a browser.** Give the user the URL or file path and
   ask: "Open it in your browser now?" Open the page only if the user says
   yes. To open it, run the command again with `--open`, or use the host's
   browser tool. Then tell the user what to do, for example: "The Outputs tab
   shows each test case and has a feedback box. The Benchmark tab shows the
   numbers. When you finish, select Submit All Reviews and tell me."

## What the user sees in the viewer

The **Outputs** tab shows one test case at a time:

- **Prompt:** the task.
- **Output:** the files that the skill made. Where possible, the viewer shows
  the content in the page.
- **Previous Output** (iteration 2 and later): a collapsed section with the
  output from the last iteration.
- **Notes** (when there are any): the executor's `outputs/user_notes.md` and
  the grader's `user_notes_summary`, `claims`, `eval_feedback` and `notes`.
  `user_notes.md` is not repeated in the output file list.
- **Formal Grades** (if you graded the run): a collapsed section with the
  result of each assertion.
- **Feedback:** a text box that saves automatically.
- **Previous Feedback** (iteration 2 and later): the user's comments from the
  last iteration.

The **Benchmark** tab shows pass rates, time and token use for each
configuration. It also shows the results for each eval, any skipped runs and
the analyst notes.

Previous and Next move focus to the heading of the new run. There are no
global arrow-key shortcuts. "Submit All Reviews" saves `feedback.json`. Check
the save status. A failed save does not complete the review, and the feedback
stays in the page so the user can try again. A static page downloads
`feedback.json` instead. Copy the downloaded file into the iteration directory
before you continue.

**Accessibility limits.** Accessible controls do not make the generated
images, PDFs or other files accessible. If an output needs a text description,
a transcript or an accessible source document, supply it separately. For XLSX
files, the spreadsheet preview loads the SheetJS parser from its CDN (pinned
with SRI). It parses at most 1,001 rows and shows up to 1,000 rows and 50
columns per sheet, reporting when the preview is truncated. Without network
access, the download link still works and the page reports the preview error.
The viewer does not embed files larger than 5 MiB,
and it limits all embedded data to 10 MiB. For files above these limits, it
shows the absolute path. See `README.md` for keyboard behavior and
screen-reader notes.

## Step 5: Read the feedback

When the user tells you they are done, read `feedback.json`:

```json
{
  "reviews": [
    {"run_id": "eval-1-chart-labels-with_skill-run-1", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-2-table-layout-with_skill-run-1", "feedback": "", "timestamp": "..."}
  ],
  "status": "complete"
}
```

The flat map from the Agent Skills specification,
`{"eval-1-chart-labels": "feedback text"}`, is also accepted.

Empty feedback means that the user found no problem. Put your effort into the
test cases with specific complaints.

A backup file with `"status": "in_progress"` was not submitted. Keep its
feedback, but do not treat it as a completed review, and do not treat its
blank entries as approval.

Let the user stop the viewer, unless they ask you to stop it. Press Ctrl+C to
stop a foreground viewer. For a background viewer, stop only the session
handle that you recorded. Do not stop unrelated processes or all Python
processes.

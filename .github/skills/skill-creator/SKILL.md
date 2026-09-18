---
name: skill-creator
description: Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy.
---

# Skill Creator

A skill for creating GitHub Copilot skills and iteratively improving them.

At a high level, the process of creating a skill goes like this:

- Decide what you want the skill to do and roughly how it should do it
- Write a draft of the skill
- Create a few test prompts and run Copilot with access to the skill on them
- Help the user evaluate the results both qualitatively and quantitatively
  - While the runs happen in the background, draft some quantitative evals if there aren't any (if there are some, you can either use as is or modify if you feel something needs to change about them). Then explain them to the user (or if they already existed, explain the ones that already exist)
  - Use the `eval-viewer/generate_review.py` script to show the user the results for them to look at, and also let them look at the quantitative metrics
- Rewrite the skill based on feedback from the user's evaluation of the results (and also if there are any glaring flaws that become apparent from the quantitative benchmarks)
- Repeat until you're satisfied
- Expand the test set and try again at larger scale

Your job when using this skill is to figure out where the user is in this process and then jump in and help them progress through these stages. So for instance, maybe they're like "I want to make a skill for X". You can help narrow down what they mean, write a draft, write the test cases, figure out how they want to evaluate, run all the prompts, and repeat.

On the other hand, maybe they already have a draft of the skill. In this case you can go straight to the eval/iterate part of the loop.

Of course, you should always be flexible and if the user is like "I don't need to run a bunch of evaluations, just vibe with me", you can do that instead.

Then after the skill is done (but again, the order is flexible), you can also run the skill description improver, which we have a whole separate script for, to optimize the triggering of the skill.

## Communicating with the user

Match the user's demonstrated expertise. Explain unfamiliar evaluation terms briefly when needed; avoid generic coding or assistive-technology tutorials. For review tools, describe app-specific focus changes and save/download status rather than basic keyboard operation.

---

## Creating a skill

### Capture Intent

Start by understanding the user's intent. The current conversation might already contain a workflow the user wants to capture (e.g., they say "turn this into a skill"). If so, extract answers from the conversation history first — the tools used, the sequence of steps, corrections the user made, input/output formats observed. The user may need to fill the gaps, and should confirm before proceeding to the next step.

1. What should this skill enable Copilot to do?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?
4. Should we set up test cases to verify the skill works? Skills with objectively verifiable outputs (file transforms, data extraction, code generation, fixed workflow steps) benefit from test cases. Skills with subjective outputs (writing style, art) often don't need them. Suggest the appropriate default based on the skill type, but let the user decide.

### Interview and Research

Proactively ask questions about edge cases, input/output formats, example files, success criteria, and dependencies. Wait to write test prompts until you've got this part ironed out.

Check available MCPs - if useful for research (searching docs, finding similar skills, looking up best practices), research in parallel via subagents if available, otherwise inline. Come prepared with context to reduce burden on the user.

### Write the SKILL.md

Based on the user interview, fill in these components:

- **name**: Skill identifier
- **description**: When to trigger and what it does. Include both the task and specific contexts for using the skill. Put discovery guidance here rather than hiding it in the body. For example: "Build dashboards for company metrics. Use when the user asks for dashboards, data visualization, or internal metrics, even if they do not explicitly ask for a dashboard." Test realistic positive and near-miss queries rather than assuming more forceful wording improves selection.
- **compatibility**: Required tools, dependencies (optional, rarely needed)
- **the rest of the skill :)**

### Skill Writing Guide

#### Anatomy of a Skill

For a Copilot project skill, place the entry point at `.github/skills/<skill-name>/SKILL.md` (`.github\skills\<skill-name>\SKILL.md` on Windows). Keep bundled resources alongside it.

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description required)
│   └── Markdown instructions
└── Bundled Resources (optional)
    ├── scripts/    - Executable code for deterministic/repetitive tasks
    ├── references/ - Docs loaded into context as needed
    └── assets/     - Files used in output (templates, icons, fonts)
```

#### Progressive Disclosure

Skills use a three-level loading system:
1. **Metadata** (name + description) - Always in context (~100 words)
2. **SKILL.md body** - In context whenever skill triggers (<500 lines ideal)
3. **Bundled resources** - As needed (unlimited, scripts can execute without loading)

These word counts are approximate and you can feel free to go longer if needed.

**Key patterns:**
- Keep SKILL.md under 500 lines; if you're approaching this limit, add an additional layer of hierarchy along with clear pointers about where the model using the skill should go next to follow up.
- Reference files clearly from SKILL.md with guidance on when to read them
- For large reference files (>300 lines), include a table of contents

**Domain organization**: When a skill supports multiple domains/frameworks, organize by variant:
```
cloud-deploy/
├── SKILL.md (workflow + selection)
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```
Instruct Copilot to read only the relevant reference file.

#### Principle of Lack of Surprise

This goes without saying, but skills must not contain malware, exploit code, or any content that could compromise system security. A skill's contents should not surprise the user in their intent if described. Don't go along with requests to create misleading skills or skills designed to facilitate unauthorized access, data exfiltration, or other malicious activities. Things like a "roleplay as an XYZ" are OK though.

#### Writing Patterns

Prefer using the imperative form in instructions.

**Defining output formats** - You can do it like this:
```markdown
## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

**Examples pattern** - It's useful to include examples. You can format them like this (but if "Input" and "Output" are in the examples you might want to deviate a little):
```markdown
## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

### Writing Style

Try to explain to the model why things are important in lieu of heavy-handed musty MUSTs. Use theory of mind and try to make the skill general and not super-narrow to specific examples. Start by writing a draft and then look at it with fresh eyes and improve it.

### Test Cases

After writing the skill draft, come up with 2-3 realistic test prompts — the kind of thing a real user would actually say. Share them with the user: [you don't have to use this exact language] "Here are a few test cases I'd like to try. Do these look right, or do you want to add more?" Then run them.

Save test cases to `evals/evals.json`. Don't write assertions yet — just the prompts. You'll draft assertions in the next step while the runs are in progress.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": [],
      "expectations": []
    }
  ]
}
```

See `references/schemas.md` for the full schema. Store verifiable statements as strings in `expectations` (not `assertions`); leave the list empty until they are drafted. These task evals are different from the `query`/`should_trigger` list used for description optimization.

## Running and evaluating test cases

This section is one continuous sequence — don't stop partway through. Do NOT use `/skill-test` or any other testing skill.

**Script prerequisites:** Use Python 3.10+ and run `python -m scripts...` commands from the skill-creator directory so imports resolve. On Windows, verify `python --version`; if it is only a WindowsApps alias, use `py --list-paths` to find an installed interpreter and invoke it with `& "C:\path\to\python.exe"`. Use quoted Windows paths and one-line commands in PowerShell rather than Bash `\` continuations.

Put results in `<skill-name>-workspace/` as a sibling to the skill directory. Use `<workspace>/iteration-<N>/eval-<ID>-<descriptive-name>/<configuration>/run-1/outputs/`, even for a single run. The `eval-` prefix and `run-<number>` directory are required by aggregation; repeats use `run-2/`, etc. Put shared `eval_metadata.json` in the `eval-<ID>-<descriptive-name>/` directory and `grading.json`/`timing.json` beside each run's `outputs/`. Create directories as needed.

### Step 1: Start paired runs (with-skill AND baseline)

Where the Copilot host supports independent subagents, launch each test case's with-skill and baseline runs together. Keep the prompt, inputs, and model consistent across the pair, and isolate outputs. Ensure the baseline cannot discover the candidate skill implicitly through its working directory or installed skills. If parallel execution is unavailable or resource-limited, run independent sessions sequentially; see "Copilot host adaptations" for the single-agent fallback.

**With-skill run:**

```
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>-<descriptive-name>/with_skill/run-1/outputs/
- Outputs to save: <what the user cares about — e.g., "the .docx file", "the final CSV">
```

**Baseline run** (same prompt, but the baseline depends on context):
- **Creating a new skill**: no skill at all. Same prompt, no skill path, save to the same eval directory's `without_skill/run-1/outputs/`.
- **Improving an existing skill**: the old version. Before editing, copy the complete skill directory to the workspace's `skill-snapshot` directory using the host's file tools, then point the baseline run at that snapshot. Save to the same eval directory's `old_skill/run-1/outputs/`.

For each run, also preserve the evidence the grader consumes:

- Save `transcript.md` beside `outputs/` when the host exposes a transcript. Start its prompt section with `## Eval Prompt` so the reviewer fallback can identify it.
- Save `outputs/metrics.json` using the contract in `references/schemas.md` when actual executor metrics are available. Omit unavailable measurements rather than inventing zeroes.
- Save `outputs/user_notes.md` when the executor encountered uncertainties, review needs, or workarounds. Do not create an empty placeholder.

Write an `eval_metadata.json` for each test case (`expectations` can be empty for now). Give each eval a descriptive name based on what it's testing, and retain both prefix and ID in its directory: `eval-1-descriptive-name-here/`, not just `descriptive-name-here/`. If this iteration uses new or modified eval prompts, create these files for each new eval directory — don't assume they carry over from previous iterations.

```json
{
  "eval_id": 1,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "expectations": []
}
```

### Step 2: While runs are in progress, draft assertions

Don't just wait for the runs to finish — you can use this time productively. Draft quantitative assertions for each test case and explain them to the user. If assertions already exist in `evals/evals.json`, review them and explain what they check.

Good assertions are objectively verifiable and have descriptive names — they should read clearly in the benchmark viewer so someone glancing at the results immediately understands what each one checks. Subjective skills (writing style, design quality) are better evaluated qualitatively — don't force assertions onto things that need human judgment.

Update the `expectations` string lists in `eval_metadata.json` and `evals/evals.json` once drafted. These are the input assertions; the grader writes separate `expectations` objects with `text`, `passed`, and `evidence` in `grading.json`. Also explain to the user what they'll see in the viewer — both the qualitative outputs and the quantitative benchmark.

### Step 3: As runs complete, capture timing data

When a run completes, save any token usage and duration reported by the Copilot host to `timing.json` in the run directory. If the host provides `total_tokens` and `duration_ms`, the record looks like:

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

Capture available metrics promptly; host capabilities and retention vary. Measure elapsed time if needed, but do not invent token counts or report unavailable measurements as zero. Note missing metrics when interpreting the benchmark.

### Step 4: Grade, aggregate, and launch the viewer

Once all runs are done:

1. **Grade each run** — spawn a grader subagent (or grade inline) that reads `agents/grader.md` and evaluates each assertion against the outputs. Save results to `grading.json` in each run directory. The grading.json expectations array must use the fields `text`, `passed`, and `evidence` (not `name`/`met`/`details` or other variants) — the viewer depends on these exact field names. For assertions that can be checked programmatically, write and run a script rather than eyeballing it — scripts are faster, more reliable, and can be reused across iterations.

2. **Aggregate into benchmark** — run the aggregation script from the skill-creator directory:
   ```bash
   python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
   ```
   This produces `benchmark.json` and `benchmark.md` with pass rate and, when every run provides them, time and host-reported token usage for each configuration, with mean and standard deviation. A delta is included only when two configurations have graded runs; a missing or ungraded baseline is not treated as zero. Add `--executor-model` or `--analyzer-model` only when their actual model IDs are known. If generating benchmark.json manually, see `references/schemas.md` for the exact schema the viewer expects.
   Put each with_skill version before its baseline counterpart.

3. **Do an analyst pass** — read the benchmark data and surface patterns the aggregate stats might hide. See `agents/analyzer.md` (the "Analyzing Benchmark Results" section) for what to look for — things like assertions that always pass regardless of skill (non-discriminating), high-variance evals (possibly flaky), and time/token tradeoffs. Save the analyzer's JSON array to `<workspace>/iteration-N/analysis_notes.json`, then regenerate the benchmark with `--notes <workspace>/iteration-N/analysis_notes.json` so the observations are included in both `benchmark.json` and `benchmark.md` before launching the viewer.

4. **Launch the viewer** with both qualitative outputs and quantitative data, in the foreground:
   ```bash
   python "<skill-creator-path>/eval-viewer/generate_review.py" "<workspace>/iteration-N" --skill-name "my-skill" --benchmark "<workspace>/iteration-N/benchmark.json"
   ```
   PowerShell equivalent, from the skill-creator directory:
   ```powershell
   python .\eval-viewer\generate_review.py "C:\workspace\iteration-N" --skill-name "my-skill" --benchmark "C:\workspace\iteration-N\benchmark.json"
   ```
   For iteration 2+, also pass `--previous-workspace <workspace>/iteration-<N-1>`. Keep eval directory names identical between iterations because previous outputs and feedback are matched by directory path.

   **Headless or remote Copilot hosts:** If `webbrowser.open()` is not available or the environment has no display, use `--static` with a workspace HTML output path to write a standalone file instead of starting a server. Share the file for local review. "Submit All Reviews" downloads `feedback.json`; copy the downloaded file into the iteration directory before continuing.

   If interactive work must continue while serving, use the host tool's managed background mode and retain its session handle. Do not detach with `nohup` or hide startup errors; verify the printed local URL is responsive. Static HTML needs no running process.

Note: please use generate_review.py to create the viewer; there's no need to write custom HTML.

5. **Tell the user** something like: "I've opened the results in your browser. There are two tabs — 'Outputs' lets you click through each test case and leave feedback, 'Benchmark' shows the quantitative comparison. When you're done, come back here and let me know."

### What the user sees in the viewer

The "Outputs" tab shows one test case at a time:
- **Prompt**: the task that was given
- **Output**: the files the skill produced, rendered inline where possible
- **Previous Output** (iteration 2+): collapsed section showing last iteration's output
- **Formal Grades** (if grading was run): collapsed section showing assertion pass/fail
- **Feedback**: a textbox that auto-saves as they type
- **Previous Feedback** (iteration 2+): their comments from last time, shown below the textbox

The "Benchmark" tab shows the stats summary: pass rates, timing, and token usage for each configuration, with per-eval breakdowns and analyst observations.

Changing evaluations with Previous/Next moves focus to the new run heading. Outputs and Benchmark are separate tab panels; there are no global arrow shortcuts for evaluation navigation. When done, choose "Submit All Reviews" to save feedback to `feedback.json`. Check the save/download status: a failed save is not a completed review, and feedback should remain available to retry. A downloaded backup includes every run and uses `"status": "in_progress"` so the next agent knows submission was not confirmed; preserve it, retry the save, and do not treat it as completed review. Dismissing the completion dialog preserves the saved completion status.

**Accessibility scope:** Accessible browser controls and report structure do not make arbitrary generated images, PDFs, or embedded output files accessible. Supply useful text descriptions, transcripts, or accessible source documents separately when the output requires them. Spreadsheet previews load the SRI-pinned SheetJS parser from its external CDN only when an XLSX output is present; without network access, the download remains available and the preview reports the failure. Files larger than 5 MiB are not embedded, and the page limits all embedded output data to 10 MiB after text escaping and binary encoding. The reviewer displays the absolute path for files that exceed either limit.

### Step 5: Read the feedback

When the user tells you they're done, read `feedback.json`:

```json
{
  "reviews": [
    {"run_id": "eval-1-chart-labels-with_skill-run-1", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-2-table-layout-with_skill-run-1", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-3-export-format-with_skill-run-1", "feedback": "perfect, love this", "timestamp": "..."}
  ],
  "status": "complete"
}
```

Empty feedback means the user thought it was fine. Focus your improvements on the test cases where the user had specific complaints.

If a recovered backup has `"status": "in_progress"`, retain its feedback but do not interpret blank entries or the file itself as review completion.

Leave viewer shutdown to the user unless they request it. A foreground viewer can be stopped with Ctrl+C; for a tool-managed background viewer, stop only its recorded session handle when requested. Do not kill unrelated processes or all Python processes.

---

## Improving the skill

This is the heart of the loop. You've run the test cases, the user has reviewed the results, and now you need to make the skill better based on their feedback.

### How to think about improvements

1. **Generalize from the feedback.** The big picture thing that's happening here is that we're trying to create skills that can be used a million times (maybe literally, maybe even more who knows) across many different prompts. Here you and the user are iterating on only a few examples over and over again because it helps move faster. The user knows these examples in and out and it's quick for them to assess new outputs. But if the skill you and the user are codeveloping works only for those examples, it's useless. Rather than put in fiddly overfitty changes, or oppressively constrictive MUSTs, if there's some stubborn issue, you might try branching out and using different metaphors, or recommending different patterns of working. It's relatively cheap to try and maybe you'll land on something great.

2. **Keep the prompt lean.** Remove things that aren't pulling their weight. Make sure to read the transcripts, not just the final outputs — if it looks like the skill is making the model waste a bunch of time doing things that are unproductive, you can try getting rid of the parts of the skill that are making it do that and seeing what happens.

3. **Explain the why.** Try hard to explain the **why** behind everything you're asking the model to do. Today's LLMs are *smart*. They have good theory of mind and when given a good harness can go beyond rote instructions and really make things happen. Even if the feedback from the user is terse or frustrated, try to actually understand the task and why the user is writing what they wrote, and what they actually wrote, and then transmit this understanding into the instructions. If you find yourself writing ALWAYS or NEVER in all caps, or using super rigid structures, that's a yellow flag — if possible, reframe and explain the reasoning so that the model understands why the thing you're asking for is important. That's a more humane, powerful, and effective approach.

4. **Look for repeated work across test cases.** Read the transcripts from the test runs and notice if the subagents all independently wrote similar helper scripts or took the same multi-step approach to something. If all 3 test cases resulted in the subagent writing a `create_docx.py` or a `build_chart.py`, that's a strong signal the skill should bundle that script. Write it once, put it in `scripts/`, and tell the skill to use it. This saves every future invocation from reinventing the wheel.

### The iteration loop

After improving the skill:

1. Apply your improvements to the skill
2. Rerun all test cases into a new `iteration-<N+1>/` directory, including baseline runs. If you're creating a new skill, the baseline is always `without_skill` (no skill) — that stays the same across iterations. If you're improving an existing skill, use your judgment on what makes sense as the baseline: the original version the user came in with, or the previous iteration.
3. Launch the reviewer with `--previous-workspace` pointing at the previous iteration
4. Wait for the user to review and tell you they're done
5. Read the new feedback, improve again, repeat

Keep going until:
- The user says they're happy
- The feedback is all empty (everything looks good)
- You're not making meaningful progress

---

## Advanced: Blind comparison

For situations where you want a more rigorous comparison between two versions of a skill (e.g., the user asks "is the new version actually better?"), there's a blind comparison system. Read `agents/comparator.md` and `agents/analyzer.md` for the details. The basic idea is: give two outputs to an independent agent without telling it which is which, and let it judge quality. Then analyze why the winner won.
If the comparator declares a tie, record it and skip winner/loser analysis.

This is optional, requires subagents, and most users won't need it. The human review loop is usually sufficient.

---

## Description Optimization

The description field in SKILL.md frontmatter helps Copilot decide when to use a skill. After creating or improving a skill, offer to optimize the description for better triggering accuracy.

### Step 1: Generate trigger eval queries

Create 20 eval queries — a mix of should-trigger and should-not-trigger. Save this separate trigger eval set as a JSON list, not the task `evals.json` object:

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

Each entry needs a nonempty `query` string and a boolean `should_trigger`. Repeated query text remains separate, ordered entries, each receiving its own runs and zero-based `eval_id` in results. Duplicates can fall in both train and test sets, so review accidental duplicates to avoid weakening the holdout.

The queries must be realistic and something a Copilot user would actually type. Use concrete details such as file paths, job context, column names, company names, and URLs. Include varied lengths, casual phrasing, abbreviations, and edge cases. The user will review them before evaluation.

Bad: `"Format this data"`, `"Extract text from PDF"`, `"Create a chart"`

Good: `"ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"`

For the **should-trigger** queries (8-10), think about coverage. You want different phrasings of the same intent — some formal, some casual. Include cases where the user doesn't explicitly name the skill or file type but clearly needs it. Throw in some uncommon use cases and cases where this skill competes with another but should win.

For the **should-not-trigger** queries (8-10), the most valuable ones are the near-misses — queries that share keywords or concepts with the skill but actually need something different. Think adjacent domains, ambiguous phrasing where a naive keyword match would trigger but shouldn't, and cases where the query touches on something the skill does but in a context where another tool is more appropriate.

The key thing to avoid: don't make should-not-trigger queries obviously irrelevant. "Write a fibonacci function" as a negative test for a PDF skill is too easy — it doesn't test anything. The negative cases should be genuinely tricky.

### Step 2: Review with user

Present the eval set to the user for review using the HTML template:

1. Read the template from `assets/eval_review.html`
2. Replace the placeholders:
   - `__EVAL_DATA_PLACEHOLDER__` → the JSON array as a JavaScript expression, not a quoted string. In Python, use `json.dumps(eval_set).replace("<", "\\u003c")` so query text such as `</script>` cannot end the containing script.
   - `__SKILL_NAME_PLACEHOLDER__` → the HTML-escaped skill name; replace both occurrences (title and visible heading)
   - `__SKILL_DESCRIPTION_PLACEHOLDER__` → the HTML-escaped current description
3. Write to the workspace (e.g., `<workspace>/eval_review_<skill-name>.html`) and open it with the host's browser/file-opening tool. On Windows, use a Windows path such as `C:\workspace\eval_review_my-skill.html`; don't run macOS `open` commands in PowerShell.
4. The user can edit queries, toggle should-trigger, add/remove entries, then click "Export Eval Set"
5. The browser downloads `eval_set.json`. Use the user's chosen download location and confirm the exported file rather than assuming a fixed path.

This step matters — bad eval queries lead to bad descriptions.

### Step 3: Run the optimization loop

Explain that the optimization loop makes real GitHub Copilot calls and can take time. It requires an installed, authenticated `copilot` CLI with access to the intended model. This workflow uses Copilot only.

Save the eval set to the workspace, then run from the skill-creator directory in the foreground (or the host tool's managed background mode when appropriate):

```powershell
python -m scripts.run_loop --eval-set "C:\workspace\trigger-eval.json" --skill-path "C:\project\.github\skills\my-skill" --max-iterations 5 --verbose --report "C:\workspace\report.html"
```

Omit `--model` to use the CLI's configured default, or add `--model "<copilot-supported-model-id>"` to select a model supported by the installed CLI and account. The choice applies to evaluation and improvement. The default timeout is 60 seconds per query; increase `--timeout` for a slow or cold model. Do not assume a model identifier from another host is supported. CLI authentication/model errors, timeouts, and invalid or incomplete event output are failures, not no-trigger scores; fix the reported error before retrying. Every run writes `results.json` and, when enabled, a final report to a timestamped results directory. Use `--results-dir` to select its parent; otherwise it is created under `skill-creator-results` next to the eval set. A failure includes the completed iteration history and an error field, then exits unsuccessfully. Use `--report none` when no browser/report is wanted.

The evaluator loads a uniquely named temporary candidate through `--add-dir` and runs each query from that isolated workspace. Absolute scores are approximate because of the `-eval-<id>` suffix, while relative comparisons use the same condition. It measures the first tool decision with only `skill` and `view` available, not task completion or output quality. A no-tool answer counts as negative only after a successful terminal result. Discovery and original-skill conflicts are validated when the CLI reports loaded skills; some versions omit that event. Description rewriting has no tools. The evaluator defaults to four concurrent calls, prints planned usage, and records—but does not pin—the installed CLI version. Let the scripts manage invocation; see `README.md` for verified versions and limitations.

While it runs, periodically tail the output to give the user updates on which iteration it's on and what the scores look like.

In the HTML report, use **Refresh report** to load progress or explicitly enable auto-refresh (off initially). Auto-refresh pauses while refresh controls or the results table have focus, descriptions are expanded, or the tab is hidden. Screen-reader browse-mode reading does not create DOM focus, so leave automatic refresh off while reading in browse mode.

This handles the full optimization loop automatically. It makes a stratified split with approximately 60% train and 40% held-out test, retaining training examples for each label, evaluates the current description (running each entry 3 times to get a reliable trigger rate), then calls Copilot to propose improvements based only on train failures. A holdout requires at least two should-trigger and two should-not-trigger entries so both labels remain represented in training and test; otherwise add examples or use `--holdout 0`. It re-evaluates each new description on both train and test, iterating up to 5 times. The HTML report shows results per iteration, and JSON returns `best_description` — selected by test score when a test set exists, otherwise by train score. Because the same holdout selects the best attempt, the maximum test score is an optimistically biased model-selection estimate rather than untouched final validation. Improver logs include the full prompt, `SKILL.md` content, and evaluation queries; handle result directories as potentially sensitive project data.

### How skill triggering works

Copilot uses skill metadata, including the name and description, to decide relevance before loading instructions. Selection can vary with the model, prompt, available skills, and host context; a matching keyword does not guarantee activation.

Use substantive prompts that reflect the skill's intended workload, plus realistic near-misses. Evaluate observed selection rather than assuming that simple tasks never trigger skills or complex tasks always do.

### Step 4: Apply the result

Take `best_description` from the JSON output and update the skill's SKILL.md frontmatter. Use a YAML block scalar so punctuation cannot change the value's YAML type:

```yaml
description: |
  The optimized description text.
```

Show the user before/after and report the scores.

When an independent final score matters, create an expanded trigger query set that was not used during optimization and run it once with `python -m scripts.run_eval` against the selected description. Do not present the repeatedly reused holdout score as untouched final validation.

---

### Package and present

For Copilot project use, deliver the skill directory with its resources under `.github/skills/<skill-name>/`. If the user also wants a portable archive, run `python -m scripts.package_skill` with the quoted skill-directory path from the skill-creator directory. The archive excludes development roots such as `evals/`, `tests/`, `skill-creator-results/`, `logs/`, `test-results/`, and `playwright-report/`, plus `.log` and existing `.skill` files; retain the source directory when those artifacts are needed. Share the resulting `.skill` file using the host's available file-sharing mechanism; do not assume the CLI can install that archive directly.

When updating an existing skill, preserve its directory name and frontmatter `name`. If the source is read-only, work on a copy in a writable project workspace and clearly identify the final files.

---

## Copilot host adaptations

Keep the draft → test → review → improve loop, adapting only to capabilities actually available:

- **No parallel execution:** Run independent Copilot sessions sequentially, retaining paired baselines where possible.
- **Only one agent/context:** Follow the skill on each test prompt yourself. Label these as sanity checks, not independent comparisons. Keep verifiable grading and human feedback, but skip claims of baseline improvement and blind comparisons without independent runs.
- **Headless or remote host:** Generate the static review HTML with `generate_review.py` and share it for local review. Collect the downloaded `feedback.json` in the iteration directory. If HTML cannot be shared or opened, present prompts, outputs, and grades in the conversation and record feedback there.
- **No installed/authenticated Copilot CLI:** Continue authoring and manual review, but defer automated description optimization until the CLI is available. Do not replace it with another backend.
- **Limited filesystem or Python access:** Explain which scripts cannot run and deliver the available skill text or files. Do not claim benchmark, packaging, or viewer steps completed without their artifacts.

Generate the review artifact before revising based on test results, so the user can inspect the outputs. Use the provided viewer rather than custom HTML.

---

## Reference files

See `README.md` for keyboard behavior, output-accessibility limits, and local development checks. Manual acceptance targets NVDA with Firefox; automated browser checks are not evidence of a completed NVDA session.

The agents/ directory contains instructions for specialized subagents. Read them when you need to spawn the relevant subagent.

- `agents/grader.md` — How to evaluate assertions against outputs
- `agents/comparator.md` — How to do blind A/B comparison between two outputs
- `agents/analyzer.md` — How to analyze why one version beat another

The references/ directory has additional documentation:
- `references/schemas.md` — JSON structures for evals.json, grading.json, etc.

If the host provides task tracking, include creation of the eval JSON and review artifact so the human review step is not missed.

# Description optimization

Read this file when the user wants to improve how reliably a skill triggers,
or after you create or change a skill and offer to optimize its description.

The `description` field in `SKILL.md` is the primary trigger signal for
Agent Skills-compatible clients, though exact selection behavior differs by
host. The bundled automated runner currently measures Copilot CLI behavior;
its scores are not universal across agents. The process has four steps: write trigger
queries, review them with the user, run the optimization loop, then apply and
validate the result.

## Contents

- [How skill triggering works](#how-skill-triggering-works)
- [Step 1: Write trigger eval queries](#step-1-write-trigger-eval-queries)
- [Step 2: Review the queries with the user](#step-2-review-the-queries-with-the-user)
- [Step 3: Run the optimization loop](#step-3-run-the-optimization-loop)
- [Step 4: Apply and validate the result](#step-4-apply-and-validate-the-result)

## How skill triggering works

Compatible agents typically read the name and description before loading the
skill instructions. The choice can change with the model, the prompt, the other
skills available and the host context. A matching keyword does not guarantee
that the skill loads.

Agents usually consult a skill only when the task needs knowledge or a
workflow that they do not already have. A simple one-step request, such as
"read this PDF", may not load a PDF skill even with a perfect description,
because the agent can do it with basic tools. Such trivial should-trigger
queries are poor tests. Prefer realistic queries that really need the skill:
an unfamiliar API, a domain-specific workflow or an uncommon format. Then
measure what the chosen evaluation host actually selects.

### Write a good description

- Write it as an instruction: "Use this skill when…", not "This skill does…".
- Describe the user's intent, not the skill's internal mechanics. The agent
  matches against what the user asked for.
- Err on the side of being pushy. List the contexts where the skill applies,
  including requests that do not name the domain, for example "even if they
  do not mention 'CSV'".
- Say what the skill does not do when a nearby skill or tool is a better
  match.
- Keep it to a few sentences. The hard limit is 1024 characters.

Do not trust a wording until the trigger queries confirm it.

Some boundaries do not move with wording. A request that names the skill's
own domain often triggers it even when the description excludes that request.
For example, "write a CI workflow that runs my skill's evals" still loads a
skill-authoring skill. When two or three wordings fail on the same query
across models, record the miss as a known limit. Do not let an exclusion
grow until it weakens the rest of the description.

## Step 1: Write trigger eval queries

Write about 20 queries: 8 to 10 that must trigger the skill and 8 to 10 that
must not. Save them as a JSON list. This list is separate from the task
`evals.json` file.

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

Each entry needs a non-empty `query` string and a boolean `should_trigger`.
Each entry gets its own runs and a zero-based `eval_id`, even when two entries
have the same text. A duplicate can go into both the train set and the
held-out validation set, which makes the holdout weaker, so remove duplicates
that you did not intend.

Write queries that a real user of the target host would type. Use concrete details, such
as file paths, column names, company names and URLs. Use different lengths,
casual language, abbreviations and edge cases.

- Bad: `"Format this data"`, `"Extract text from PDF"`, `"Create a chart"`
- Good: `"ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"`

**Should-trigger queries.** Cover the same intent with different wording, some
formal and some casual. Mix short queries with long ones full of context. Vary
the complexity: include multi-step requests where the skill's task is one step
buried in a larger job. The most useful queries need the skill, but their link
to it is not obvious. If a query asks for exactly what the skill does, any
reasonable description triggers it, so it tests little. Include queries that
do not name the skill or the file type but clearly need the skill. Add some
unusual uses, and cases where this skill competes with another skill but must
win.

**Should-not-trigger queries.** Near-misses are the most useful: queries that
share words or ideas with the skill but need something different. Use related
domains, unclear wording that a simple keyword match would select, and tasks
that another tool handles better. Do not use queries that are obviously
unrelated. "Write a fibonacci function" tests nothing for a PDF skill.

## Step 2: Review the queries with the user

Bad queries give a bad description, so review them with the user. Build the
review page with the bundled script. It escapes the data safely, so do not
fill the template by hand.

```powershell
python scripts/prepare_eval_review.py --eval-set "<workspace>/trigger-eval.json" --skill-path "<path-to-skill>" --output "<workspace>/eval_review_<skill-name>.html"
```

The script prints the path of the HTML file and does not open a browser. Give
the path to the user and ask: "Open it in your browser now?" Open the page
only if the user says yes: run the command again with `--open`, or use the
host's browser tool.

On the page, the user can change queries, set or clear should-trigger, and add
or delete entries. "Export Eval Set" downloads `eval_set.json`. The export
removes spaces and line breaks at the start and end of each query. Ask the
user where the file was saved and check that it exists. Do not assume a fixed
download folder. Then copy it over the file that the loop reads, for example:

```powershell
Copy-Item "<download-folder>/eval_set.json" "<workspace>/trigger-eval.json"
```

If the user cannot use a browser, show the queries in the conversation and
apply their changes to `trigger-eval.json`.

## Step 3: Run the optimization loop

Before you start, tell the user these facts:

- The current adapter makes real GitHub Copilot calls, so it uses the
  account's quota and takes time. The script prints the number of planned
  calls before it starts.
- The bundled loop needs an installed and authenticated `copilot` CLI with
  network access. It measures Copilot CLI trigger behavior only; do not
  present its score as evidence for other agent hosts.

Run this command. `scripts/` is this skill's scripts folder; use its full path
when you run from another directory.

```powershell
python scripts/run_loop.py --eval-set "<workspace>/trigger-eval.json" --skill-path "<path-to-skill>" --max-iterations 5 --verbose
```

Important options:

- `--model "<model-id>"` selects a model for evaluation and rewriting. If you
  leave it out, the CLI's default model is used. Use only a model ID that the
  installed CLI and account support.
- `--timeout` sets the time limit for each query, in seconds (default 60).
  Increase it for a slow model.
- `--runs-per-query` (default 3) and `--num-workers` (default 4) control the
  number of calls and how many run at the same time.
- `--holdout` sets the share of queries that is kept as the held-out
  validation set (default 0.4). The script output calls this set "test". A holdout needs at least two should-trigger and two
  should-not-trigger entries. If you have fewer, add queries or use
  `--holdout 0`.
- `--results-dir` sets the parent directory of the results. By default, a
  time-stamped run directory is created in
  `<skill-parent>/<skill-name>-workspace/description-optimization/`, next to
  the skill.
- `--report` controls the HTML report. The default, `auto`, writes
  `report.html` into the results directory. `none` turns the report off. Any
  other value is a file path.
- `--open` opens the report in a browser. The report never opens by default.
  Ask the user before you use this option.
- `--verbose` writes progress and logs to stderr. `--full-json` prints the
  full iteration history instead of the short summary.

An invalid number for an option is a usage error: the script names the flag
and exits with code 2. `--help` shows every default.

The script prints a short JSON summary on stdout: `best_description`,
`best_score`, `exit_reason`, `iterations_run`, `results_path`, `report_path`
and `error`. The results directory always contains `results.json`. If a run
fails, the summary contains the error and the history up to that point, and
the script exits with a non-zero code. Press Ctrl+C to stop the loop. It saves
the partial results and exits with code 130.

Failures are not scores. Authentication errors, model errors, timeouts and
incomplete CLI output stop the run. Fix the reported error before you try
again.

While the loop runs, check its output from time to time and tell the user the
current iteration and scores. When the report path is printed, ask the user
whether to open it. In the report, **Refresh report** loads the latest
progress. Auto-refresh is off by default. Auto-refresh pauses when the refresh
controls or the results table have focus, when a description is expanded, or
when the tab is hidden. Screen-reader browse mode does not move DOM focus, so
keep auto-refresh off while you read in browse mode.

### What the loop does

1. It splits the queries into about 60% train and 40% held-out validation.
   The script output and JSON call the validation set "test" (for example
   `test_score`). Both sets keep examples of each label.
2. It runs each query several times against the current description and
   measures the trigger rate.
3. A should-trigger query passes when its trigger rate is above the threshold.
   A should-not-trigger query passes when its rate is below the threshold.
4. The Copilot-backed improver proposes a new description from the train
   failures only. Keep the description client-neutral unless the user targets
   one host explicitly. It must be shorter than 1024 characters; a longer
   description is rejected, not shortened.
5. The loop tests the new description on both sets and repeats until all train
   queries pass or the iteration limit is reached.

The loop selects `best_description` by the test score. If there is no test
set, it uses the train score. The same test set is used to select the best
attempt, so the best test score is higher than an untouched score would be. Do
not present it as a final validation score.

If the scores do not improve after several iterations, suspect the queries
before the description: they may be too easy, too hard or labeled wrongly.
If the description is stuck, try a different structure instead of small
changes. Do not copy keywords from failed queries into the description; name
the general category that they represent.

### How the evaluator works

The evaluator loads a temporary copy of the candidate skill through
`--add-dir`. The copy has a unique name with an `-eval-<id>` suffix. Each query
runs from an isolated temporary workspace with only the `skill` and `view`
tools plus the write tools `create`, `edit` and `apply_patch`, which are never
approved. Without write tools, a model asked to change code has nothing to do
but load the only skill, which inflates false positives. The workspace is its own git root and uses a throwaway
profile, so personal skills, plugins and installed copies of the skill cannot
compete; scores measure the description on its own, not against other
installed skills. The evaluator scores the first skill decision: a `skill`
call or a `view` of the candidate `SKILL.md`. Up to 8 views of other paths
count as exploration. A write-tool call before any skill decision counts as
"not triggered", except scratch writes to the CLI profile, `.git`, or
`prompt.txt`, which count as exploration. It does not measure whether the task is completed or how
good the output is. A text answer without
a tool counts as "not triggered" only after a successful final result.

The evaluator stops a run when the original skill is also loaded, or when the
candidate is disabled. Copilot CLI 1.0.99 and later do not report which
skills they loaded, so on those versions these checks cannot run. The
isolation needs `git` on `PATH`; without it, skills in parent directories of
the temporary folder can still load.

The improver logs contain the full prompt, the `SKILL.md` content and the eval
queries. Treat result directories as sensitive project data.

## Step 4: Apply and validate the result

1. Copy `best_description` into the SKILL.md frontmatter. Use a YAML block
   scalar, so that punctuation cannot change the type of the value:

   ```yaml
   description: |
     The optimized description text.
   ```

2. Validate the skill:

   ```powershell
   python scripts/quick_validate.py "<path-to-skill>"
   ```

3. Check the description with new queries. Write 5 to 10 queries that were
   not used during optimization, including near-misses. Run them once against
   the selected description:

   ```powershell
   python scripts/run_eval.py --eval-set "<workspace>/fresh-queries.json" --skill-path "<path-to-skill>"
   ```

   This gives a score that the optimization did not influence. If it is much
   lower than the loop's held-out ("test") score, the description is overfitted to the
   loop's queries.

4. Show the user the old and new descriptions, the loop scores and the score
   from the new queries.

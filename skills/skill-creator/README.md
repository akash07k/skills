# Skill Creator

For cross-client use, install this skill under
`.agents/skills/skill-creator/`. Use a client-native location such as
`.github/skills/skill-creator/` only when needed for that host. Installed
copies are separate and are not updated automatically. In this repository,
`.agents/skills/skill-creator` is a directory symlink to `skills/skill-creator`,
so there is one source copy. The validation and packaging scripts accept the
symlink path.

On Windows, Git creates the symlink only when symlink support is on. Without
it, `.agents\skills\skill-creator` becomes a small text file that contains the
target path, and clients cannot find the skill. To fix it, turn on Developer
Mode (or use an administrator shell), then run these commands from the
repository root:

```powershell
git config core.symlinks true
Remove-Item .agents\skills\skill-creator
git checkout -- .agents/skills/skill-creator
```

Requirements: Python 3.13 or later (standard library only). Each script has a
PEP 723 header (`requires-python = ">=3.13"`, no dependencies) and stops
with a clear message on an older Python. Description
optimization also needs an authenticated GitHub Copilot CLI with network
access.

## Scripts

Run a script by its path, for example
`python scripts/quick_validate.py <skill-dir>`. The path is relative to this
directory; use the full path from any other working directory.
Running a script as a module (`-m scripts.<name>`) from this directory also
works. Each script supports `--help`, which shows the defaults.
Exit code 0 means success, 1 means invalid input or a failed run, and 2 means
a usage error, such as an invalid number for an option. Errors and warnings go
to stderr.

No script opens a browser unless you pass `--open`. Without it, the scripts
print the URL or file path. The skill tells the agent to ask the user before it
opens a browser.

## Current automated evaluation adapter: Copilot CLI

The bundled description evaluation and rewriting adapter currently uses GitHub
Copilot CLI. This is only the skill-creator's evaluation backend; it does not
limit the format or host compatibility of skills it creates. Trigger scores
measure Copilot CLI behavior and do not establish how another compatible agent
will select or follow a skill. For another host, run paired evaluations with
that host's supported activation and observation tools, or report a manual
sanity check as such.

To use this adapter, install `copilot` (`copilot.exe` on Windows), make it
available on PATH, and authenticate with `copilot login`. Omit `--model` to use
your configured default, or supply a model ID supported by your CLI and
account. Optimization makes real model calls and is subject to your account's
usage limits.

Trigger evaluation defaults to four concurrent calls and three runs per query.
Both evaluation commands print the planned call count and maximum concurrency
before starting; use `--num-workers` and `--runs-per-query` to override them.
The installed CLI version is recorded in result JSON for reproducibility, but
is not pinned or used to reject newer releases.

The evaluator loads a uniquely named temporary candidate through `--add-dir`.
The candidate name has an `-eval-<id>` suffix because Copilot requires enabled
skill names to be unique. Absolute trigger scores are therefore approximate,
although relative description comparisons use the same naming condition. It
does not overwrite installed skills. Each query runs from an isolated
temporary workspace that is its own git root, with a throwaway `HOME` and
`COPILOT_HOME`, so personal skills, plugins and skills in parent directories
cannot compete with the candidate. Authentication still comes from the OS
credential store or token environment variables. Without `git` on `PATH`,
skills in parent directories of the temporary folder can still load. Its only
available tools are `skill`, `view`, and the unapproved write tools `create`,
`edit` and `apply_patch`. It measures the **first skill decision**: a `skill`
call, or a `view` of the candidate `SKILL.md`. Up to 8 views of other paths
count as exploration, because many models list the workspace before they
choose a skill. A write-tool call counts as "not triggered": the model started
the task without the skill. Scratch writes to the CLI profile, `.git`, or
`prompt.txt` count as exploration instead, because some models jot notes in
the CLI's session folder before choosing a skill. The call is never approved,
so no file changes. It does not measure whether the task is
completed successfully. An ordinary text answer without a tool is a negative
only after a successful terminal result.
Description rewriting runs without tools.

The JSONL event integration is verified with Copilot CLI 1.0.84-5, 1.0.86,
1.0.87-0, 1.0.99-2 and 1.0.100-1. Version 1.0.87 can emit empty `session.skills_loaded`
snapshots before and after the populated snapshot, so the evaluator treats
those events as incremental. When the event is present, the evaluator rejects
a run for three reasons: the candidate is explicitly disabled, another enabled
skill has the original name, or the CLI did not discover the enabled candidate
skill. Version 1.0.86 and versions 1.0.99 and later omit the event, so these checks cannot run
and selection comes only from streamed tool calls. The isolated profile and
git root keep installed copies out on every version. The
runner also avoids `--no-auto-login`, which
1.0.87 incorrectly applies before token authentication. `--no-ask-user` keeps
evaluation non-interactive. No-tool answers still require a successful terminal
`result`. Authentication/model errors, timeouts, invalid discovery state, and
invalid or incomplete streams are errors rather than negative scores.

A should-trigger query passes when its trigger rate is above the threshold; a
should-not-trigger query passes when its rate is below the threshold, as in the
Agent Skills evaluation guide. On timeout, error, or Ctrl+C the evaluator stops
the whole Copilot process tree (`taskkill /T` on Windows, the process group on
POSIX) and removes its temporary directories.

The optimization loop reuses the held-out validation set (called "test" in
the script output) to select the highest-scoring
attempt. Its reported best test score is therefore an optimistically biased
model-selection estimate, not an untouched final validation score. Improver
logs contain the complete model prompt, including `SKILL.md` content and
evaluation queries; store and share result directories accordingly.

After selecting a description, run `scripts/run_eval.py` once against a separate,
expanded query set that was not used during optimization when an independent
final validation score matters.

## Repository layout

Development tests live outside the skill, in `tests/skill-creator/` at the
repository root, so they are not installed or packaged with the skill. Keep
`node_modules/` beside `tests/skill-creator/package.json`. Python creates
`__pycache__/` beside imported modules. Both are generated and ignored, along
with Playwright output, `skill-creator-results/` (written by older versions),
`*-workspace/`, logs, and `.skill` archives. `run_loop` writes its results to
`<skill-parent>/<skill-name>-workspace/description-optimization/` by default.
`package_skill` writes the archive to the skill's parent folder by default and
lists each file that it skips, with the reason. Track source files, test files, `package.json`, and
`package-lock.json`.

`evals/trigger-eval.json` is the trigger query set used to optimize this
skill's own description. It is excluded from packaged archives.

## Agent Skills specification differences

The scripts write the specification's names: `assertions` in `evals.json`
and `eval_metadata.json`, `assertion_results` in `grading.json`, and numeric
benchmark deltas. They still read the older `expectations` field. The
aggregator and viewer accept both the `eval-*/<config>/run-<N>/` layout and
the specification's `<eval>/<config>/outputs/` layout (read as one run).
`feedback.json` written by the viewer has a richer format with a `reviews`
list and a `status`; the specification's flat `{"eval-name": "text"}` map is
also accepted when loaded. See `references/schemas.md`.

## Keyboard and screen-reader behavior

1. The interfaces expose named landmarks and headings. There are no
   document-wide arrow-key shortcuts.
2. In the output reviewer, Previous and Next move focus to the new run's
   heading. Output filenames are headings and download links include filenames.
3. When benchmarks are available, Outputs and Benchmark are separate tab panels.
   The inactive panel is hidden from keyboard and reading order.
4. Previous Output and Formal Grades are buttons exposing their expanded state.
   Expanding or collapsing them does not move focus.
5. Feedback has a label, instructions, and a save-status announcement. Server
   failures are announced as errors, not reported as successful saves. A backup
   containing every run remains available after a save failure and is marked
   `in_progress`, not `complete`.
6. Successful submission opens a native modal dialog. Escape or Return to
   reviews closes it and restores focus to Submit All Reviews, without changing
   the saved completion state. Static pages request a download rather than
   claiming the file has been saved.
7. In the query editor, every textarea, checkbox, and delete button identifies
   its query. Toggling does not reorder rows or lose focus. Adding focuses the
   new query; deleting focuses the next query, then the previous query, or Add
   Query when none remain. Sorting preserves focus on its button and announces
   the new order.
8. Benchmark and optimization tables have captions and header associations.
   Pass/fail outcomes and evidence are text, not color or hover-only information.
   Long optimization descriptions expand with native disclosure controls.
   Live-report automatic refresh is off by default and can be enabled or paused.

## Output-file limitations

These changes address the review interface, not the accessibility of arbitrary
generated files. Image filenames are not alternative descriptions. PDFs require
accessible document content and a compatible reader; their embedded previews
are optional and download links remain available. Spreadsheet previews provide
row numbers and column letters, without guessing which cells are semantic
headers. They load the SRI-pinned SheetJS library from its external CDN only
when an XLSX preview is needed; if it is unavailable, the reviewer reports the
preview error and retains the download. Previews parse at most 1,001 rows and
show at most 1,000 rows and 50 columns per sheet; truncated previews report
the worksheet dimensions. Output files larger than 5 MiB are not
embedded, and the page also limits all embedded output data to 10 MiB after
text escaping and binary encoding. The reviewer displays the absolute local
path for files that exceed either limit.

Keyboard automation and semantic checks do not replace testing with actual
screen readers. Manually check reading order, focus announcements, error/status
announcements, modal behavior, tables, and file previews in the intended
screen-reader/browser combinations before treating accessibility as complete.
Captions/transcripts for generated media and remediation of arbitrary generated
documents are outside this keyboard/screen-reader change.

## Development checks

Run Python regression checks from the test directory. From the repository
root:

```powershell
Set-Location tests\skill-creator
python -m unittest discover -s . -p "test_*.py"
```

When Copilot is installed, this suite also exercises the actual executable
against an offline, local model fixture with isolated configuration. It checks
temporary skill discovery, trigger decisions, and tool-free rewriting without
paid model calls. This integration check is skipped when Copilot is absent.

Browser checks need Node.js and test-only dependencies. Run them from the same
directory, `tests\skill-creator`:

```powershell
npm ci
npx playwright install firefox chromium
npm test
```

If `python` does not resolve to the intended interpreter, set `PYTHON` to the
executable before running `npm test`, for example:

```powershell
$env:PYTHON = "C:\path\to\python.exe"
```

WindowsApps aliases and `.cmd` shims may not work when Playwright launches the
fixture process directly.

The browser suite exercises keyboard behavior, feedback persistence, and
axe-core semantic and color-contrast checks.
Firefox is the primary browser target for manual checks with NVDA; the suite
also exercises Chromium. It uses synthetic local data and does not invoke
Copilot or send evaluation content to model services. Packaged skills exclude
the development-only root directories `evals/`, `tests/`,
`skill-creator-results/` (from older versions), `logs/`, `test-results/`, and `playwright-report/`;
`*-workspace/`, `__pycache__/`, `node_modules/`, and `.venv/` directories
(compared case-insensitively); dotfiles such as `.env`; symlinks and
junctions inside the skill; and `.log`, `.pyc`, and existing `.skill` files.

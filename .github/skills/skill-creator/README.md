# Skill Creator

Install by copying this directory to `.github/skills/skill-creator/`. Installed
copies are separate and are not updated automatically.

## Copilot CLI

Description evaluation and rewriting use GitHub Copilot CLI only. Install
`copilot` (`copilot.exe` on Windows), make it available on PATH, and authenticate
with `copilot login`. Omit `--model` to use your configured default, or supply a
model ID supported by your CLI and account. Optimization makes real model calls
and is subject to your account's usage limits.

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
temporary workspace so the project copy cannot compete with the candidate. Its
only available tools are `skill` and `view`, so unrelated orientation calls
cannot distort the trigger score. It measures whether the **first tool
decision** selects the candidate, not whether the task is completed
successfully. An ordinary text answer without a tool is a negative only after a
successful terminal result. User-level skills can still affect selection; the
evaluator stops when the CLI reports another enabled skill with the original
name. CLI versions that omit skill-discovery events cannot provide that check.
Description rewriting runs without tools.

The JSONL event integration is verified with Copilot CLI 1.0.84-5 and 1.0.86.
When `session.skills_loaded` is present, candidate discovery is validated;
1.0.86 omits that event, so selection comes from streamed tool calls. No-tool
answers still require a successful terminal `result`. Authentication/model
errors, timeouts, explicit failed discovery, and invalid or incomplete streams
are errors rather than negative scores.

The optimization loop reuses the held-out set to select the highest-scoring
attempt. Its reported best test score is therefore an optimistically biased
model-selection estimate, not an untouched final validation score. Improver
logs contain the complete model prompt, including `SKILL.md` content and
evaluation queries; store and share result directories accordingly.

After selecting a description, run `scripts.run_eval` once against a separate,
expanded query set that was not used during optimization when an independent
final validation score matters.

## Repository layout

Keep `node_modules/` beside `tests/package.json`; do not move it to the
repository root. Python creates `__pycache__/` beside imported modules. Both are
generated and ignored, along with Playwright output, `skill-creator-results/`,
logs, and `.skill` archives. Track source files, test files, `package.json`, and
`package-lock.json`.

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
preview error and retains the download. Output files larger than 5 MiB are not
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

Run Python regression checks from this skill directory:

```powershell
python -m unittest discover -s .\tests -p "test_*.py"
```

When Copilot is installed, this suite also exercises the actual executable
against an offline, local model fixture with isolated configuration. It checks
temporary skill discovery, trigger decisions, and tool-free rewriting without
paid model calls. This integration check is skipped when Copilot is absent.

Browser checks need Node.js and test-only dependencies:

```powershell
Set-Location .\tests
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
Copilot or send evaluation content to model services. The development-only
root directories `evals/`, `tests/`, `skill-creator-results/`, `logs/`,
`test-results/`, and `playwright-report/`, including eval input files, test
dependencies, and optimization logs, plus `.log` files and existing `.skill`
archives are excluded from packaged skills.

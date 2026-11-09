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

Requirements: Python 3.13 or later and ruamel.yaml 0.19.0 for bundled scripts, plus
`uvx` and network access for the required agnix validation. Each entry-point
script declares its Python dependency for `uv run`. Alternatively, install
`requirements.txt` before running the scripts with Python. Description
optimization also needs an authenticated GitHub Copilot CLI.

The [Agent Skills specification](https://agentskills.io/specification.md)
defines the format. The [official sources guide](references/official-sources.md)
links the authoring, evaluation, and client documentation. This workflow
requires ASCII skill names for agnix compatibility even though the specification
permits Unicode names.
The local validator reads YAML 1.2 core scalars. Quote values such as `yes`,
`on`, or dates when targeting clients that may use YAML 1.1.

After creating or editing a skill, run both checks from any directory:

```powershell
uv run "<absolute-path-to-quick_validate.py>" "<path-to-skill>" --target portable
uvx --refresh-package agnix agnix@latest --strict --format json "<absolute-path-to-SKILL.md>"
```

Resolve the local validator path under `skill-creator/scripts/` and `SKILL.md`
under the target skill. Confirm that agnix examined the skill and reports no
errors or warnings. Record the reported version. If a required check cannot
run, report full validation as incomplete. The local validator catches format
issues agnix can miss. For explicitly targeted clients, use the `--target`
options described in `references/writing-skills.md`. The packager runs both
checks before writing.

## Scripts

Run a script by its path, for example
`uv run scripts/quick_validate.py <skill-dir>`. The path is relative to this
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

The task suite in `evals/evals.json` retains these behavioral cases:

| IDs | Coverage |
| --- | --- |
| 1-3 | Portable drafting, a description-only edit, and first-turn eval approval |
| 4 | Mandatory comparison gates, equivalent failures, inaccessible evidence, and confirmed absent or empty artifacts |
| 5 | Live baseline-first authoring, grading, and static review |
| 6 | A saved result under simulated deadline and winner-selection pressure |
| 7 | Concrete controlled wording variants, independent criteria, and sample budgeting |
| 8 | Separate production and defect-recognition exercises |
| 9 | A runnable checker that accepts valid alternatives and rejects defective artifacts |
| 10 | A preserved no-change decision when the control already succeeds |

Saving these cases does not execute them. Approve a host/model and session
budget before model-backed runs. Case 5 includes three nested executor sessions
per outer execution. Include any independent comparator or reviewer sessions too.
Other cases use supplied illustrative inputs, not claimed historical model results.
Case 8 explicitly measures same-context sanity checks, not independent reliability.

The Python fixture checks exercise JSON consistency, input paths, and the
worked example's checker. They do not establish consuming-agent behavior.
Use `references/host-adaptations.md` for separately selected native discovery
and post-compaction checks. Forced-loading task cases cannot prove natural discovery.

`evals/confirmation.json` contains two separately approved inventory tasks.
They exercise permitted work and resistance to an unsupported result claim.
They are unrun confirmation candidates, not part of the task suite above.
Do not use them to select or rewrite the skill and still call them independent.

For an approved confirmation run, stage the selected prompts and inputs in
fresh workspaces and create `eval_metadata.json` as in `references/running-evals.md`.
Load skill snapshots without their development `evals/` folders for both
configurations. Keep assertion lists and other confirmation tasks outside the
executor contexts. The packaged `.skill` archive already excludes `evals/`.
If the skill depends on those files, use a separate inaccessible confirmation
source instead. Record any observation limits and the actual session budget.

Before case 5, make sure that the chosen host permits and records nested sessions.
Do not use a runner that prohibits delegation or separate model calls.
Two outer paired runs need six inner sessions in total, plus any model-backed
grading or review. If the selected host cannot provide fresh inner contexts
and their events, leave the case unrun.

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
(compared case-insensitively); dotfiles such as `.env`; and `.log`, `.pyc`,
and existing `.skill` files.

These tools operate on trusted local skill and eval folders. They read linked
files and folders normally; they do not enforce a filesystem sandbox.
Temporary eval profiles and workspaces isolate measurements from installed
skills and previous context, not from the filesystem.

## Adapted authoring methods

The authoring and evaluation guidance adapts methods from
[Superpowers](https://github.com/obra/superpowers/tree/22f0b46), source revision
`22f0b46` (v7.0.2). The source scope includes the `writing-skills` bundle,
its linked TDD and test-quality guidance, and host adaptation references.
The adapted instructions are self-contained. Superpowers is not a runtime
dependency, and its mandatory deletion or publishing rules do not apply.

| Source material | Adaptation in skill-creator |
| --- | --- |
| `writing-skills/SKILL.md` | Baseline-first recommendation, tests by skill type, failure-matched guidance, concise examples |
| `references/discovery.md` | Trigger-focused descriptions, searchable vocabulary, staged reading, descriptive names |
| `references/testing-skills-with-subagents.md` and `references/bulletproofing.md` | Recommended pressure tests for discipline skills, observed workaround counters, follow-up diagnosis, fresh retests |
| `references/CLAUDE_MD_TESTING.md` | No-guidance controls and comparable instruction variants, without treating predicted results as observations |
| `references/persuasion-principles.md` | Clear requirements, reasons, commitments, and sequencing, without fabricated authority or compliance guarantees |
| `references/anthropic-best-practices.md` | Expert material, independent author and executor contexts, navigation observations, artifact inspection, reusable tools |
| `references/flowcharts.md`, `references/graphviz-conventions.dot`, and `render-graphs.js` | Small decision diagrams and rendering when needed, without another bundled renderer |
| `test-driven-development/SKILL.md` and `writing-good-tests.md` | Expected failures, minimal fixes, preserved regression cases, independent expectations, real behavior and mutation checks |
| `using-superpowers/SKILL.md` and host references | Check actual activation tools, context inheritance, model availability, and lifecycle controls |
| `docs/superpowers/specs/2026-06-10-positive-instruction-redesign-design.md` | Separate composition and recognition, preserve useful detection rules, and retain tested no-change decisions |
| `docs/porting-to-a-new-harness.md` and contribution guidance | Optional installed-host and compaction checks, artifact inspection, and destination-specific human review |

Use `references/testing-skills.md` for the recommended pressure and repeated
wording tests, with user-approved scope and budget, and
`references/host-adaptations.md` for draft replacement and publishing choices.
Use `references/worked-example.md` for connected task, draft, control, variant,
checker, pressure, and decision examples. Its outputs are illustrative.
The source scenario designs and numerical reports are not raw reproducible
campaign evidence in this repository. New behavioral cases remain unrun
until their selected execution plan is approved and completed.
Sample counts and observed effects in source material do not establish
universal reliability. Evaluate the relevant behavior in the user's target
host and model before making effectiveness claims.

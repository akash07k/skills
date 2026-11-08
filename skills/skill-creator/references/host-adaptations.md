# Host adaptations and packaging

Read this file when the current agent host cannot run the full workflow, when
you need host-specific installation guidance, or when you deliver a skill.

## Keep the skill portable

Create skills in the Agent Skills format and keep their instructions,
frontmatter, scripts and output conventions client-neutral by default. Use
`.agents/skills/<skill-name>/SKILL.md` as the preferred interoperable project
location. Choose a client-native directory or add client-specific fields only
when the user targets that host or its requirements make them necessary.

The bundled trigger-evaluation and description-optimization scripts currently
use Copilot CLI. Their results measure behavior in that evaluation host only;
they do not establish portability across other compliant agents. For another
host, run the same with-skill and baseline tasks with that host's supported
activation and observation tools, and record its name, version and model. If
those tools are unavailable, use manual sanity checks and label them clearly;
do not report them as automated trigger rates or comparative benchmarks.

## Host adaptations

Keep the loop of draft, test, review and improve. Change only the parts that
the host cannot support:

- **No parallel execution.** Run the paired sessions one after another. Keep
  a paired baseline where you can.
- **Only one agent or context.** Follow the skill yourself for each test
  prompt. Call these results sanity checks, not independent comparisons. Keep
  the grading and the human feedback. Do not claim an improvement over the
  baseline, and do not run blind comparisons, without independent runs.
- **Headless or remote host.** Use `python scripts/generate_review.py` with
  `--static` and share the HTML file for local review. Put the downloaded
  `feedback.json` in the iteration directory. If the user cannot open HTML,
  show the prompts, outputs and grades in the conversation, and record the
  feedback there.
- **No installed or authenticated Copilot CLI.** Continue to write, validate
  and review the portable skill by hand. The bundled automated trigger and
  description-optimization scripts require Copilot CLI; they do not currently
  accept another provider.
- **Limited file system or Python access.** Tell the user which scripts cannot
  run, and deliver the skill text or files that you can. Do not claim that a
  benchmark, package or viewer step is complete without its output file.

Check the actual host's tool list and context inheritance before dispatching.
A child can inherit the author's conversation even when it has a separate
name. For measurement, use fresh contexts with the complete task and the
selected configuration. Use the host's lifecycle controls and supported
skill-loading mechanism. Do not copy another client's tool names, model
names, or configuration switches.

Make the review file before you change the skill based on the test results, so
that the user can examine the outputs.

## Native discovery and execution checks

Offer these checks when the user needs evidence about an installed skill.
An isolated trigger score does not test competition with installed skills.

1. Agree on the target host, model, installed skill version, tasks, and session budget.
2. Install only the selected artifact using the host's supported mechanism.
3. Start a fresh session with the normal competing skills available.
4. Send a natural task without a skill name, path, or instruction to load it.
5. Observe selection, required reference reads, and the completed artifact.
6. Repeat a near-miss that belongs to another skill and a relevant mixed task.

For a report skill, use a factual report task, a request to rewrite its reusable
workflow, and an unrelated code task. Agree on the expected owner of each task.
Do not force-load the candidate in these checks.
Save the task, installed version, tool events, artifacts, and observed host/model.
If the host does not expose skill-loading events, record that observation limit.
Do not infer successful discovery from the assistant saying that it used the skill.

If results differ from isolated probes, inspect competitors and reading cues.
If every description fails the same case, examine task labels and host behavior.
Do not keep rewriting a description to hide an execution or installation problem.

### Long sessions and context reduction

Offer a post-compaction check only when the intended workflow needs it.
Compaction is the host's reduction of earlier conversation context.
Use the host's actual mechanism, then resume a relevant task.
Make sure that the required guidance remains available and the output stays correct.
If the host cannot expose or initiate compaction, state that the check is unverified.
Do not replace real context reduction with an empty session and call it equivalent.

Record installed body size, repeated reads, model requests, and available usage.
Compare repeated runs before attributing overhead to longer instructions.
Do not impose another host's byte limit or add a bootstrap injector.
Use the existing host lifecycle instead.

## Where skills are installed

Use `.agents/skills/<skill-name>/SKILL.md` for a project skill intended to work
across Agent Skills-compatible clients. Each client can also support its own
native project or user skill locations. For example, Copilot uses
`.github/skills/<skill-name>/SKILL.md` for project skills, while other clients
may use different paths. Check the target client's current documentation
before choosing a native location. Keep bundled resources next to `SKILL.md`,
and make the directory name match the frontmatter `name`.

When you update an existing skill, keep its directory name and its `name`
value. If the source directory is read-only, work on a copy in a writable
project workspace, and tell the user clearly which files are the final ones.

A directory symlink from a client's native location to the canonical
`.agents/skills/<name>` copy avoids maintaining duplicate skills. The
validation and packaging scripts accept the symlink path.

## Package a skill

To give the user a portable archive, run:

```powershell
python scripts/package_skill.py "<path-to-skill>" "<output-directory>"
```

The output directory is optional. By default, the archive goes into the
skill's parent folder. The script validates the skill first and does not
package an invalid skill. It lists each file that it skips, with the reason.
The `.skill` archive is a zip file. The archive does not contain:

- development directories: `evals/`, `tests/`, `skill-creator-results/`
  (from older versions), `logs/`, `test-results/`, `playwright-report/`
  and `*-workspace/`
- generated files: `__pycache__/`, `node_modules/`, `.venv/`, `*.pyc`, `.log`
  files and existing `.skill` files
- dotfiles and dot-directories, such as `.env` and `.git/`

Linked files and folders are included as their contents. Use trusted local
skill folders; packaging does not enforce a filesystem sandbox.

The script compares directory names without regard to case. Keep the source
directory when you need the excluded files.

Share the `.skill` file with the host's file-sharing method. Do not assume that
the CLI can install the archive directly.

Other ways to install a skill:

- `copilot skill add <file|url|directory>` adds a skill to Copilot CLI. Check
  `copilot skill add --help` for the inputs that your version accepts.
- `gh skill` in the GitHub CLI installs and publishes skills from GitHub
  repositories.

## Delivery and publishing choices

At delivery, recommend the action that fits the user's goal. Offer local
source files, a `.skill` package, installation in the target client, or
publishing when relevant. Do not ask about publishing during every draft.

Ask for the action first. If its destination is not known, ask for that next.
A user can authorize several actions together, but do not infer a commit,
push, pull request, or release from approval of the skill or its tests.

For an approved publishing action, identify the exact skill files,
repository, destination, and requested visibility. Include only those files.
Keep unrelated local changes, private inputs, and eval outputs out of the
publication unless the user explicitly includes them.
Use the current host's available Git or publishing tools.
Do not add another publishing runner.

Before a selected upstream contribution, read the destination's current
contribution rules and pull request template. Check scope and previous proposals.
Include the requested authoring host/model details and relevant before/after evidence.
Complete the required human diff review and disclose unverified behavior.
Do not copy one repository's branch policy or review rules into every generated skill.

Complete the selected action and report its actual artifact, path, or URL.
If the host cannot perform it, explain the limitation and provide the
local files or package. Do not claim that a successful test published a skill.

## Replacing an experimental draft

If an untested draft biases a fresh approach, offer a rewrite or replacement.
Ask which draft files to replace and whether the user wants a retained copy.
Act only on that selected draft. Preserve existing user-owned work by default.
Do not make deletion a condition of authoring, testing, or delivery.

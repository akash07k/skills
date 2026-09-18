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

Make the review file before you change the skill based on the test results, so
that the user can examine the outputs.

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
- symlinks and Windows junctions inside the skill

The script compares directory names without regard to case. Keep the source
directory when you need the excluded files.

Share the `.skill` file with the host's file-sharing method. Do not assume that
the CLI can install the archive directly.

Other ways to install a skill:

- `copilot skill add <file|url|directory>` adds a skill to Copilot CLI. Check
  `copilot skill add --help` for the inputs that your version accepts.
- `gh skill` in the GitHub CLI installs and publishes skills from GitHub
  repositories.

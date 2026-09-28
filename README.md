# Skills

Personal collection of agent skills. Each top-level skill directory owns its
instructions, supporting scripts, references, and assets. Development tests
live either in the skill directory (for example `skills\code-review\evals\`)
or, when they must not be installed or packaged with the skill, under
`tests\<skill-name>\` at the repository root; `skill-creator`'s tests are in
`tests\skill-creator\`.
Generated dependencies and caches stay beside the files that create them but
are ignored; source manifests and lockfiles remain tracked.

`skill-creator/` contains the tooling used to create, evaluate, review, and
package skills in this repository.

`code-review/` provides a six-axis checklist for pull requests and whole-project
audits, with repository conventions and precise file/line findings. Its
`evals/evals.json` tests small edits, an eight-file project audit, and a
16,105-line synthetic pull request. The large fixture (`large-pr.diff` and
`approved-rates.csv`) is committed with LF line endings pinned in
`.gitattributes`. `python skills\code-review\evals\generate_large_fixture.py`
regenerates it and `python skills\code-review\evals\check_large_fixture.py`
verifies it.

Project skill symlinks live in `.agents/skills/`, the cross-client location
read by Agent Skills-compatible clients, and point to the source directories
under `skills/`. On Windows, clone with `git config core.symlinks true` and
Developer Mode or an administrator shell; otherwise Git writes each symlink as
a small text file containing its target path.

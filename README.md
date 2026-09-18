# Skills

Personal collection of agent skills. Each top-level skill directory owns its
instructions, supporting scripts, references, and assets. Development tests
live either in the skill directory or, when they must not be installed or
packaged with the skill, under `tests\<skill-name>\` at the repository root;
`skill-creator`'s tests are in `tests\skill-creator\`.
Generated dependencies and caches stay beside the files that create them but
are ignored; source manifests and lockfiles remain tracked.

`skill-creator/` contains the tooling used to create, evaluate, review, and
package skills in this repository.

Project skill symlinks live in `.agents/skills/`, the cross-client location
read by Agent Skills-compatible clients, and point to the source directories
under `skills/`. On Windows, clone with `git config core.symlinks true` and
Developer Mode or an administrator shell; otherwise Git writes each symlink as
a small text file containing its target path.
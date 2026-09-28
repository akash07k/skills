# Skills

Personal collection of agent skills. Each top-level skill directory owns its
instructions, supporting scripts, references, assets, and development tests.
Generated dependencies and caches stay beside the files that create them but
are ignored; source manifests and lockfiles remain tracked.

`skill-creator/` contains the tooling used to create, evaluate, review, and
package skills in this repository.

`code-review/` provides a six-axis checklist for pull requests and whole-project
audits, with repository conventions and precise file/line findings. Its
`evals/evals.json` tests small edits, an eight-file project audit, and a
16,105-line synthetic pull request. Regenerate and verify the large fixture with
`python skills\code-review\evals\generate_large_fixture.py` and
`python skills\code-review\evals\check_large_fixture.py`. The generated diff
and CSV are ignored; the evaluation definitions and generators are tracked.

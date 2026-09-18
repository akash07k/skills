---
name: skill-creator
description: |
  Use this skill when creating, editing, testing, evaluating, or packaging an Agent Skill (`SKILL.md`) for any compatible agent or harness. Load it before you create or change any skill folder, because it bundles the spec validator, eval and benchmark runners, description optimizer, and packager. Use it to turn workflows into reusable skills, improve instructions or trigger descriptions, add scripts or references, compare a skill against a baseline, validate against the Agent Skills standard, or package a skill. Trigger even when the user does not say "Agent Skill" but wants to package a repeatable workflow for on-demand use or asks why a skill does not activate. Do not use it for standalone prompt writing, custom instructions such as `AGENTS.md`, custom agents, or MCP servers unless the user wants the result built as a skill. Do not use it to write CI pipelines or GitHub Actions workflows, even ones that run skill evals.
license: AGPL-3.0-or-later
compatibility: Requires Python 3.13+ for bundled scripts. Automated trigger evaluation and description optimization currently use the authenticated GitHub Copilot CLI with network access; this is an optional evaluation backend, not a requirement of generated skills.
---

# Skill Creator

Use this skill to create and improve portable Agent Skills that follow the
Agent Skills format. The main loop is:

1. Find out what the skill must do and roughly how.
2. Write a draft of the skill.
3. Run the skill in the intended agent or harness on realistic test prompts.
4. Help the user review the results, both by reading the outputs and with
   benchmark numbers.
5. Change the skill based on the feedback. Repeat until the user is satisfied.
6. Optionally, optimize the description so that the skill triggers reliably.

Generated skills follow the Agent Skills format and should be client-neutral by
default. Add client-specific frontmatter, installation paths, tools or commands
only when the user targets that client or its compatibility requires them.

Find out where the user is in this loop and continue from there. If they have
only an idea, help them define it and write a draft. If they already have a
draft, go to testing. If they say they do not want formal evals, work
informally with them. The order is flexible.

Match the user's level of expertise. Briefly explain evaluation terms that may
be new to them. For the review tools, describe app-specific behavior, such as
focus changes and save status, and do not explain basic keyboard use.

## Create a skill

### Capture the intent

The conversation may already contain the workflow that the user wants to keep,
for example "turn this into a skill". If so, take the tools, steps,
corrections and input and output formats from the conversation first. Ask the
user to fill the gaps and confirm before you continue. Find out:

1. What the skill must let an agent do and which client(s) it targets. Default
   to cross-client Agent Skills compatibility unless the user says otherwise.
2. When the skill must trigger: which user phrases and contexts.
3. What output format is expected.
4. Whether to set up test cases. Skills with outputs that can be checked
   objectively (file conversions, data extraction, code generation, fixed
   workflows) benefit from test cases. Skills with subjective outputs (writing
   style, art) often do not. Suggest a default for the skill type, and let the
   user decide.

Start from real expertise, not general knowledge. A skill built only from what
the model already knows gives vague advice. Ask for project material: runbooks,
style guides, API specifications and schemas, incident reports, code review
comments and fixes in version control history. A real task done hands-on in
the conversation is also good material: keep the steps that worked, the
corrections the user made and the facts the agent did not know.

Ask about edge cases, input and output formats, example files, success
criteria and dependencies before you write test prompts. If MCP servers or
subagents are available, use them to research documentation, similar skills
and best practices, in parallel where possible. Bring this context to the
conversation so the user has less to explain.

### Write the SKILL.md

Read `references/writing-skills.md` before you write a new skill or make a
large change. It has the frontmatter field rules, YAML pitfalls, staged
loading and the writing style guide. The essentials:

- Use `.agents/skills/<skill-name>/SKILL.md` as the default project location
  for cross-client portability. Use a client's native location only when the
  user targets that client.
- `name`: 1-64 lowercase letters, digits and hyphens, the same as the
  directory name. `description`: 1-1024 characters. Add other frontmatter
  fields only when needed, and client-specific fields only when the user
  targets that client.
- **The description is the trigger.** Write it as "Use this skill when…",
  describe what the user wants to achieve, list contexts that do not name the
  domain, and add near-miss exclusions. Then test it with real queries.
- Keep the body under about 5000 tokens and 500 lines. Move details into
  `references/` and say in SKILL.md exactly when to read each file.
- Add what the agent lacks and omit what it knows. Include a **Gotchas**
  section in SKILL.md and a checklist for multi-step workflows.
- Read `references/scripts.md` before you write or change a bundled script.

After you write or change a skill, validate it and fix every error and
warning:

```powershell
python scripts/quick_validate.py "<path-to-skill>"
```

### Write test cases

Agree with the user to include task evals before adding them. A request to
draft or edit a skill does not by itself authorize test files. Show proposed
prompts in the conversation and wait for approval before saving or running
them, so the user can correct the test scope before it becomes a fixture.

Write 2 or 3 realistic test prompts: the kind of thing a real user would say.
Vary the phrasing, the level of detail and the formality. Include at least one
edge case, such as a malformed input or an unusual request.
Show them to the user, for example: "Here are a few test cases I'd like to
try. Do these look right, or do you want to add more?" After approval, save them to
`evals/evals.json`:

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": [],
      "assertions": []
    }
  ]
}
```

Leave `assertions` empty for now. You write them while the first runs are in
progress. See `references/schemas.md` for the full format. These task evals are
not the same as the trigger queries for description optimization.

## Run and review the evals

Read `references/running-evals.md` before you run the test cases. It contains
the workspace layout, the run instructions, grading, the benchmark commands
and the review viewer. In short:

1. Start a with-skill run and a baseline run for each test case.
2. While they run, write the assertions.
3. Save the time and token data for each run.
4. Grade each run with `agents/grader.md`, aggregate with
   `scripts/aggregate_benchmark.py`, do an analyst pass and build the viewer
   with `scripts/generate_review.py`.
5. Give the user the URL or file path and ask: "Open it in your browser now?"
   Open a browser only if the user says yes.
6. When the user is done, read `feedback.json`.

The bundled automated eval and trigger scripts currently use Copilot CLI.
Treat their scores as evidence about that evaluation host only, not as proof
that every compatible agent will trigger or follow the skill the same way.
For another target host, use its activation and execution tools for paired
runs and record the host and model; see `references/host-adaptations.md`.

Build the review file before you change the skill based on the test results.

## Improve the skill

1. **Make general changes.** The skill will be used on many different prompts,
   not only on these few test cases. Do not add narrow fixes or strict rules
   for one example. If a problem persists, try a different explanation or a
   different way of working.
2. **Keep the skill short.** Read the transcripts, not only the final outputs.
   Remove instructions that make the model waste time. If the pass rate stops
   improving as you add rules, try removing instructions instead.
3. **Explain the reason.** Try to understand why the user gave their feedback,
   even when it is short. Put that understanding into the instructions. When
   you had to correct the agent, add the correction to the skill's Gotchas.
4. **Bundle repeated work.** When the test runs all write a similar helper
   script or follow the same steps, put a script in `scripts/` and tell the
   skill to use it. Follow `references/scripts.md`.

Then:

1. Apply the changes and run `scripts/quick_validate.py`.
2. Run all test cases again, including the baselines, into
   `iteration-<N+1>/`. For a new skill, the baseline is always without the
   skill. For an existing skill, use either the original version or the
   previous iteration.
3. Build the viewer with `--previous-workspace` pointing to the previous
   iteration, and ask the user before you open it.
4. Wait for the user's review, read the feedback and repeat.

Stop when the user is satisfied, when all feedback is empty, or when the
changes no longer make progress.

### Blind comparison (optional)

To find out whether a new version is really better, give the outputs of two
versions to an independent agent that does not know which is which. Read
`agents/comparator.md` and `agents/analyzer.md` for the procedure. If the
comparator declares a tie, record it and skip the winner and loser analysis.
This needs subagents. The human review loop is usually enough.

## Optimize the description

After you create or improve a skill, offer to optimize its description. Read
`references/description-optimization.md` for the full procedure. In short:
write about 20 trigger queries with near-misses, review them with the user,
run `scripts/run_loop.py`, apply `best_description`, validate and check the
result with 5 to 10 new queries.

## Deliver the skill

Read `references/host-adaptations.md` when you deliver or package the skill,
or when the host cannot run part of this workflow (no subagents, no browser,
no Copilot CLI or no Python).

## Gotchas

- Script paths such as `scripts/quick_validate.py` are relative to this
  skill's directory. Use the full path to this skill's `scripts` folder; the
  scripts then work from any working directory.
- Do not use `/skill-test` or other testing skills for these evals. The
  aggregator and viewer need this workflow's workspace layout and grading
  files, and other tools do not make them.
- The scripts never open a browser by themselves. Always ask the user first,
  then use `--open` or the host's browser tool.
- Grading results go in `assertion_results`, with the fields `text`, `passed`
  and `evidence`. The aggregator and viewer also read the legacy
  `expectations` name, but ignore any other field name.
- Keep eval directory names the same in every iteration. Previous outputs and
  feedback are matched by path.
- The best test score from the optimization loop is optimistic. The "test"
  set in the script output is the held-out validation set, and the loop uses
  it to pick the best attempt. Use new queries for an independent score.
- Do not invent time or token values. Leave out values that the host does not
  report.

## Checklist

- [ ] Intent, triggers, output format and test approach agreed with the user
- [ ] SKILL.md written; `quick_validate` passes
- [ ] Test prompts saved in `evals/evals.json`
- [ ] With-skill and baseline runs complete; assertions written
- [ ] Runs graded, benchmark aggregated, analyst notes added
- [ ] Viewer built; user asked before a browser opens; feedback read
- [ ] Skill improved and tested again until the user is satisfied
- [ ] Description optimized and checked with new queries (if wanted)
- [ ] Skill delivered or packaged

## Available scripts

The paths are relative to this skill's directory. Each script needs Python
3.13+ and only the standard library, and supports `--help`.

| Script | Purpose |
| --- | --- |
| `scripts/quick_validate.py` | Check SKILL.md against the specification. `--json` for machine output, `--strict` to fail on client-specific fields. |
| `scripts/aggregate_benchmark.py` | Combine graded runs into `benchmark.json` and `benchmark.md`. |
| `scripts/generate_review.py` | Build the output and benchmark viewer. |
| `scripts/prepare_eval_review.py` | Build the trigger-query review page. |
| `scripts/run_eval.py` | Measure the trigger rate of a description once. |
| `scripts/run_loop.py` | Optimize a description over several iterations. |
| `scripts/improve_description.py` | Propose a better description from failed queries. `run_loop` uses it; it can also run on its own. |
| `scripts/generate_report.py` | Build the HTML report of an optimization run. `run_loop` uses it; it can also run on its own. |
| `scripts/package_skill.py` | Validate a skill and build a `.skill` archive. |

## Reference files

- `references/writing-skills.md`: frontmatter rules, descriptions, staged
  loading and writing style.
- `references/running-evals.md`: running, grading, benchmark and viewer.
- `references/description-optimization.md`: trigger queries and the
  optimization loop.
- `references/scripts.md`: how to design scripts bundled in a skill.
- `references/host-adaptations.md`: limited hosts, install locations and
  packaging.
- `references/schemas.md`: JSON formats for `evals.json`, `grading.json`,
  `benchmark.json` and the other files.
- `agents/grader.md`: grade assertions against outputs.
- `agents/comparator.md`: blind comparison of two outputs.
- `agents/analyzer.md`: analyze benchmarks and comparison results.
- `README.md`: CLI details, keyboard and screen-reader behavior, and
  development checks.

If the host has task tracking, add tasks for the eval JSON and the review
file, so that the human review step is not forgotten.

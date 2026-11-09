# Writing a Skill

Read this before you write a new SKILL.md or make a large change to one. It
covers the frontmatter fields, the description, staged loading, writing style
and validation. For the official sources, read
[official-sources.md](official-sources.md).

## Layout and frontmatter

Use `.agents/skills/<skill-name>/SKILL.md` as the default project location for
cross-client portability. Use a client's native location only when the user
targets that client or it requires one.

```text
skill-name/
├── SKILL.md          required: YAML frontmatter + Markdown instructions
├── scripts/          optional: code for deterministic or repeated tasks
├── references/       optional: documents that the agent reads when needed
└── assets/           optional: templates, images and other output files
```

The frontmatter supports these fields from the Agent Skills specification:

| Field | Required | Rules |
| --- | --- | --- |
| `name` | Yes | 1-64 characters. Lowercase letters, digits and hyphens. No hyphen at the start or end, and no `--`. Must be the same as the directory name. The specification permits Unicode; this workflow requires ASCII for agnix compatibility. |
| `description` | Yes | 1-1024 characters. Say what the skill does and when to use it. |
| `license` | No | A license name or the name of a bundled license file. |
| `compatibility` | No | 1-500 characters. Required tools, runtimes, network access or target client. Add it only when the skill has such requirements. |
| `metadata` | No | A map of string keys to string values, for example `author` or `version`. |
| `allowed-tools` | No | Space-separated tools that the skill may use without asking. Experimental; support differs between clients. |

Use a YAML block scalar (`description: |`) when the text contains `:`, `#`
or quotes. The local validator uses the YAML 1.2 core schema. Some clients
use YAML 1.1 and interpret `yes`, `no`, `on`, `off` or dates differently;
quote these values for portability. Quote numbers when a string is required.

Some clients add fields outside the portable specification. Add them only when
the user targets that client. Pass `--target copilot`, `--target claude-code`,
or `--target codex` to the local validator. Without an explicit target, the
local validator reports common extensions as warnings, or errors with
`--strict`; unknown fields are errors. Codex uses an optional
`agents/openai.yaml` sidecar instead of extra `SKILL.md` fields.

**The description is the trigger.** Compatible agents use the skill name and
description to decide whether to load its instructions, though exact selection
behavior differs by client. Put all "when to use" information there, not in
the body.

- Write it as an instruction to the agent: "Use this skill when…".
- Describe what the user wants to achieve, not how the skill works inside.
- Be a little pushy. List the contexts where the skill applies, including
  requests that do not name the domain, for example "even if they do not say
  'CSV'".
- Add near-miss exclusions when another skill or tool is a better match.
- Keep it to a few sentences, within 1024 characters.

Then measure: test realistic should-trigger and near-miss queries instead of
assuming that a wording works.

**Load content in stages.** A skill loads in three levels:

1. The name and description are always in context (about 100 tokens).
2. The SKILL.md body loads when the skill triggers. Keep it below about 5000
   tokens and 500 lines.
3. Bundled files load only when the agent reads them. Scripts can run without
   being read.

When the body gets near these limits, move details into `references/` and say
in SKILL.md when to read each file, for example "Read `references/<cloud>.md`
for the cloud that the user deploys to". Link each reference file directly
from SKILL.md; avoid chains where one reference file sends the agent to
another. Keep each file focused on one topic. House rule for this skill (not a specification rule):
give reference files longer than 300 lines a table of contents. When a skill
supports several domains or frameworks, use one reference file for each and
tell the agent to read only the relevant one.

If a workflow requires another skill, name it and state exactly when to load it.
Use the target host's supported skill tool. Check availability before promising that dependency.
Distinguish required background from optional related material.
Do not force-load a whole skill when a focused reference provides the needed fact.

## Writing style

- Add what the agent lacks and omit what it knows. For each line, ask: "Would
  the agent get this wrong without it?" If not, cut it. Do not explain what a
  PDF or HTTP is.
- Scope the skill as one coherent unit of work, like a well-designed function.
  Too narrow means several skills must load for one task. Too broad makes the
  skill hard to trigger precisely.
- Aim for moderate detail. Short, stepwise guidance with one working example
  usually beats a document that covers every edge case.
- Match specificity to fragility. Give freedom, with reasons, where many
  approaches work. Be exact, for example "run exactly this command", where a
  step is fragile or the order matters.
- Teach a method for a class of problems, not the answer to one instance.
- Create a skill for reusable knowledge, a method, a pattern, or a reference.
  Keep one-off stories out of the instructions. Put project-only conventions
  in the project's instructions file unless the user wants a reusable skill.
  If a constraint is mechanical, prefer an existing validator or tool.
- Use the imperative form.
- Explain why an instruction matters. A model that understands the reason
  handles new cases better than one that follows a rule. If you find yourself
  writing ALWAYS or NEVER in capitals, explain the reason instead.
- Write for the general case, not only for the test examples.
- Give a default approach, not a menu of equal options.
- Include a **Gotchas** section in SKILL.md for facts that the agent would
  otherwise get wrong. Keep it in SKILL.md, not in a reference, so that the
  agent reads it before it meets the problem. For a multi-step workflow, give
  a checklist.
- Add a validation loop where possible: do the work, run a validator, fix the
  errors and repeat until it passes. For batch or destructive work, have the
  agent write a plan, validate the plan, then run it.
- When the output must have a fixed format, show a template and say which
  parts are required and which are flexible.
- Examples help. Show input and output pairs where useful:

  ```markdown
  ## Commit message format
  **Example:**
  Input: Added user authentication with JWT tokens
  Output: feat(auth): implement JWT-based authentication
  ```

- Prefer one complete, adaptable example from a real task. Choose the most
  relevant language instead of duplicating the example across many languages.
  Use placeholders when the output contract needs variable fields, not
  as a replacement for an example that actually works.
- Keep terms consistent. Use names that describe the method and searchable
  symptoms, errors, commands, and formats. Do not rename an existing skill
  merely to adopt a different naming style.
- Avoid facts that expire without context. For version-specific behavior,
  state the applicable version and how to check it.
- Bundle a script when every run would otherwise write the same helper code.
  Read `references/scripts.md` before you write or change a bundled script.
  It covers pinned one-off commands, inline dependencies, no interactive
  prompts, `--help`, error messages, JSON output and exit codes.

## Match guidance to the failure

Choose the form from observed behavior, not from a preference for strict rules.

| Observed failure | Useful form | Example |
| --- | --- | --- |
| The agent understands a rule but skips it | Explicit requirement with a counter to the observed workaround | Require the agreed verification before reporting completion |
| The output has the wrong shape | Positive recipe or output contract | Result, evidence, then a necessary next action |
| A required element is omitted | Required field in the template or schema | An evidence field for each verdict |
| The action depends on a condition | Condition followed by the action | If the brief exists, reference it rather than repeating it |

Vague exceptions reopen the decision. Replace "unless relevant" with an
observable condition when an exception is real. If a length limit applies
only to prose, scope it to that section rather than adding an exemption
after a limit on the whole output.

If the skill also reviews its output, preserve the review's detection rules
when replacing composition prohibitions with a recipe.
Use `references/testing-skills.md` to test production and recognition separately.

Explain the reason for a requirement. Put it at the point where the agent
must act. Use short checklists for meaningful dependencies.
Use direct language for genuine requirements, not artificial authority,
false urgency, guilt, or invented claims about what everyone does.
Collaborative wording must preserve honest disagreement.

For discipline failures, build a short table from actual stated
rationalizations and the requirement each one misses. Do not transplant
another skill's excuses as hypothetical rules. For wording experiments,
read `references/testing-skills.md`.

Use `references/worked-example.md` when the user needs an adaptable skill
example, a controlled experiment, or independent checker examples.

## Use diagrams only for decisions

Use a small flowchart when a branch or stopping condition is easy to miss.
Use numbered steps for a linear process and a table for reference facts.
Give decisions question labels, actions verb labels, and branches explicit
conditions. Keep runnable code in code blocks, not diagram nodes.

If the target host renders Mermaid, use it directly. If the user needs DOT
or SVG, use an available renderer and check the diagram's branches and result.
Do not add a Graphviz dependency or a rendering script unless the task needs it.

Skills must not contain malware, exploit code or any content that could harm
system security. What a skill does must not surprise a user who reads its
description. Do not create misleading skills, or skills for unauthorized
access or data exfiltration. Role-play skills are acceptable.

After you write or change a skill, run both required validators as described
in `SKILL.md`:

```powershell
uv run "<absolute-path-to-quick_validate.py>" "<path-to-skill>" --target portable
uvx --refresh-package agnix agnix@latest --strict --format json "<absolute-path-to-SKILL.md>"
```

Resolve the local validator relative to this skill and `SKILL.md` relative to
the target skill. For a selected client, replace `portable` with its `--target`
in the local validator. For Claude Code or Codex, also add the same `--target` to agnix.
For Copilot, use agnix's generic target. If a Codex skill contains
`agents/openai.yaml`, pass it as a second path to agnix and require at least
two files checked. Agnix recognizes this sidecar in a native
`.agents/skills/<name>` location. If it does not check the sidecar, report
validation as incomplete.

Confirm that agnix examined the expected files and reports no errors or
warnings. Record its version. If either required check cannot run, report full
validation as incomplete. These checks do not prove that the target client
loads or follows the skill. Run a real client test only when the user chooses
one and the client is available.

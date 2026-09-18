# Writing a Skill

Read this before you write a new SKILL.md or make a large change to one. It
covers the frontmatter fields, the description, staged loading, writing style
and validation.

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
| `name` | Yes | 1-64 characters. Lowercase letters, digits and hyphens. No hyphen at the start or end, and no `--`. Must be the same as the directory name. |
| `description` | Yes | 1-1024 characters. Say what the skill does and when to use it. |
| `license` | No | A license name or the name of a bundled license file. |
| `compatibility` | No | 1-500 characters. Required tools, runtimes, network access or target client. Add it only when the skill has such requirements. |
| `metadata` | No | A map of string keys to string values, for example `author` or `version`. |
| `allowed-tools` | No | Space-separated tools that the skill may use without asking. Experimental; support differs between clients. |

Use a YAML block scalar (`description: |`) when the text contains `:`, `#`
or quotes. In plain YAML, `yes`, `no`, `on`, `off` and numbers are not strings,
so quote them.

Some clients add their own fields, such as `argument-hint`, `user-invocable`
and `disable-model-invocation` in VS Code. They are not in the specification.
`quick_validate` reports them as warnings, and as errors with `--strict`.
Other unknown fields are always errors. Add a client field only when the user
targets that client.

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

- Bundle a script when every run would otherwise write the same helper code.
  Read `references/scripts.md` before you write or change a bundled script.
  It covers pinned one-off commands, inline dependencies, no interactive
  prompts, `--help`, error messages, JSON output and exit codes.

Skills must not contain malware, exploit code or any content that could harm
system security. What a skill does must not surprise a user who reads its
description. Do not create misleading skills, or skills for unauthorized
access or data exfiltration. Role-play skills are acceptable.

After you write or change a skill, validate it:

```powershell
python scripts/quick_validate.py "<path-to-skill>"
```

The validator reports all errors and warnings. Exit code 0 means the skill is
valid. Fix warnings too, unless they are about a client field that the user
wants. Read the draft again later with fresh eyes and improve it.

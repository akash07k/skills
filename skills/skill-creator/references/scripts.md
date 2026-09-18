# Scripts in a skill

Read this file when a skill needs to run a command or bundle a script in
`scripts/`. It explains when to use a one-off command, when to bundle a script,
and how to design a script that an agent can use without help.

## Contents

- [One-off command or bundled script](#one-off-command-or-bundled-script)
- [Self-contained scripts](#self-contained-scripts)
- [Design the interface for an agent](#design-the-interface-for-an-agent)
- [List the scripts in SKILL.md](#list-the-scripts-in-skillmd)
- [Checklist](#checklist)

## One-off command or bundled script

**Use a one-off command** when an existing tool already does the work and the
command has only a few flags. Tools such as `uvx`, `pipx run` and `npx`
download and run a package without a separate install step. Pin the version,
so that the command behaves the same next month:

```powershell
uvx ruff@0.8.0 check .
npx eslint@9.0.0 --fix .
```

State the prerequisites in SKILL.md, for example "Requires Node.js 18+". Put
runtime requirements in the `compatibility` frontmatter field. Do not assume
that the agent's environment has a tool.

**Bundle a script** when the command gets hard to write correctly on the first
try, or when the test runs show the agent writing the same helper code again
and again. A tested script is more reliable than code the agent writes fresh
each time. Scripts also run without being read, so they cost little context.

## Self-contained scripts

Make each script declare its own dependencies, so that the agent can run it
with one command and no install step. For Python, use inline script metadata
(PEP 723) at the top of the file:

```python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "beautifulsoup4>=4.12,<5",
# ]
# ///
```

Run it with `uv run scripts/extract.py`. `uv` creates an isolated environment
and installs the declared packages. `pipx run` also reads this format. Pin
versions with ranges, and use `requires-python` to set the minimum Python
version. A script that uses only the standard library can still declare
`requires-python` and an empty dependency list.

Other runtimes have the same idea: Deno `npm:` imports, Bun versioned imports
and Ruby `bundler/inline`. Use the runtime that the skill's users already have.

## Design the interface for an agent

The agent reads stdout and stderr to decide its next step. Design for that
reader.

- **No interactive prompts.** This is a hard requirement. Agents run in
  non-interactive shells and cannot answer a prompt, a password dialog or a
  confirmation menu. A script that waits for input hangs. Take all input from
  flags, environment variables or stdin. When a required value is missing,
  stop with an error that shows the correct usage.
- **Support `--help`.** It is the main way that an agent learns the interface.
  Give a one-line purpose, the flags with their defaults and one or two
  examples. Keep it short, because it goes into the agent's context.
- **Write helpful errors.** Say what went wrong, what was expected and what to
  try. "Error: --format must be one of: json, csv, table. Received: xml" lets
  the agent fix the call. "Error: invalid input" wastes a turn.
- **Use structured output.** Print JSON, CSV or TSV instead of aligned text
  columns. Send the data to stdout. Send progress, warnings and other
  diagnostics to stderr, so that the agent can parse stdout cleanly.
- **Make it idempotent.** Agents retry commands. "Create if it does not exist"
  is safer than "create and fail on a duplicate".
- **Reject unclear input.** Do not guess. Use closed sets of values where
  possible, and fail with a clear error.
- **Add `--dry-run`** for destructive or stateful actions, so that the agent
  can preview the result first.
- **Use meaningful exit codes.** Use different codes for different failures,
  for example invalid arguments, not found and authentication failure. List
  them in `--help`.
- **Use safe defaults.** For risky actions, require an explicit flag such as
  `--force` or `--confirm`.
- **Keep the output size predictable.** Many hosts cut tool output after
  10,000 to 30,000 characters, and the agent loses the rest. Print a summary or
  a limited number of items by default, and add flags such as `--offset` or
  `--limit` for more. When the output is large and cannot be paged, require an
  `--output` flag with a file path, or `-` for stdout.

## List the scripts in SKILL.md

The agent does not know that a script exists until SKILL.md tells it. Add an
"Available scripts" section with one line for each script, and show the
command at the step where the agent must run it. Write paths relative to the
skill's root directory, not absolute paths. The same rule applies to commands
in `references/` files.

```markdown
## Available scripts

- `scripts/validate.py`: check the configuration files.
- `scripts/process.py`: turn the input data into a summary report.
```

Use a validation loop where it fits: do the work, run the validation script,
fix the reported errors and run it again until it passes. For batch or
destructive work, have the agent write a plan file first, validate the plan
with a script and only then run it.

## Checklist

- [ ] One-off tool versions are pinned.
- [ ] The script declares its dependencies and Python version inline.
- [ ] The script never waits for input.
- [ ] `--help` shows the purpose, flags, defaults, examples and exit codes.
- [ ] Errors say what was expected.
- [ ] Data goes to stdout as JSON or another structured format; diagnostics go
      to stderr.
- [ ] Destructive actions have `--dry-run` or need an explicit flag.
- [ ] Large output is limited or written to a file.
- [ ] SKILL.md lists the script with a path relative to the skill root.

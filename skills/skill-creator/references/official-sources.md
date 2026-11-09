# Official Agent Skills sources

The [Agent Skills specification](https://agentskills.io/specification.md)
defines the skill format. Read it when writing or checking frontmatter,
directory structure, relative references, or compatibility. The specification
recommends its demonstration `skills-ref` validator. This workflow instead
requires agnix and the local validator; neither establishes behavior in every
client. ASCII-only skill names are a workflow compatibility rule, not a
restriction imposed by the specification.

The [documentation index](https://agentskills.io/llms.txt) lists the current
official pages. Consult it when looking for new or changed guidance.

Use these sources as needed:

- [Overview](https://agentskills.io/home.md): How skills are discovered,
  activated, and loaded in stages.
- [Best practices](https://agentskills.io/skill-creation/best-practices.md):
  How to scope instructions, use real expertise, and organize resources.
- [Description optimization](https://agentskills.io/skill-creation/optimizing-descriptions.md):
  How to design and measure activation queries.
- [Evaluation guide](https://agentskills.io/skill-creation/evaluating-skills.md):
  How to compare executions, assess outputs, and iterate.
- [Using scripts](https://agentskills.io/skill-creation/using-scripts.md):
  How to bundle dependencies and design noninteractive script interfaces.
- [Quickstart](https://agentskills.io/skill-creation/quickstart.md):
  A client-specific example of creating and activating a skill in VS Code.
- [Client showcase](https://agentskills.io/clients.md): Clients that support
  the format. Check a target client's own documentation for current behavior.
- [Client integration](https://agentskills.io/client-implementation/adding-skills-support.md):
  Discovery and activation guidance when building a client, not a requirement
  for ordinary skill authoring.

For explicitly targeted clients, use their current documentation:

- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)
  and [VS Code Copilot](https://code.visualstudio.com/docs/copilot/customization/agent-skills):
  Locations, supported fields, and client-specific behavior.
- [Claude Code](https://code.claude.com/docs/en/skills.md): Its native
  frontmatter fields and skill execution behavior.
- [Codex](https://developers.openai.com/codex/skills/): Its skill locations and
  optional `agents/openai.yaml` metadata.

The official evaluation guide suggests adding assertions after an initial run
and removing checks that both configurations pass. This skill freezes agreed
criteria before inspecting outputs and retains common acceptance checks. Those
are deliberate evaluation choices, not Agent Skills format requirements.

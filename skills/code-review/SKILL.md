---
name: code-review
description: Use this skill when the user asks for a code review, audit, inspection, sanity check, or independent verification of existing code or changes, such as a pull request, diff, commit range, bug fix, refactor, dependency update, agent-generated change, or whole repository. Trigger for questions like "is this safe to merge?" or "is this overengineered?", including large or generated diffs and checks against supplied tests or data. Read project conventions first and deliver one consolidated review of correctness, overengineering, readability, architecture, security, and performance, with line-anchored findings, coverage, and a verdict. Do not use it for implementation or editing code, acting on review comments, creating or describing pull requests, release summaries, or dedicated threat modeling or penetration testing.
license: AGPL-3.0-or-later
---

# Code Review and Quality

## Overview

Review the entire change and the surrounding code it affects before you recommend a merge, whether the diff is one line or more than 15,000. For a whole-project audit, inspect the existing repository instead of looking for a diff. Cover six axes: correctness, overengineering, readability, architecture, security, and performance. Review only; do not edit the code under review.

**Approval standard for changes:** Approve when the change meets its requirements and no Critical or Required findings remain, even if you would have written it differently. Don't block a change on style preferences or unrelated pre-existing problems; in a whole-project audit, existing problems are in scope. State verification gaps honestly.

## When to Use

- Before merging a pull request or change, including one produced by another agent or model
- After a feature, refactor, or bug fix (review both the fix and its regression test)
- When a change adds or upgrades dependencies: also read [references/dependencies.md](references/dependencies.md)
- When a change is very large, has a weak description, or the author disputes a finding: also read [references/change-hygiene.md](references/change-hygiene.md)
- When asked to audit the entire repository, including existing source, tests, and relevant configuration: also read [references/project-audit.md](references/project-audit.md)
- When you flag a structural problem and need a concrete remedy: see [references/structural-remedies.md](references/structural-remedies.md)

## The Six-Axis Review

Evaluate each axis where it is relevant. Report concrete findings rather than filling a quota for each axis. For a change, focus on what the change causes; for a whole-project audit, cover existing issues throughout the in-scope repository.

### 1. Correctness

- Does the code match the spec or task requirements, including edge cases, boundary values, and error paths?
- Do the tests exercise the required behavior, and were they actually run?
- Are there off-by-one errors, race conditions, or state inconsistencies?

### 2. Overengineering

Does the change add more moving parts than the required behavior needs?

- Can new code, an option, or a compatibility path be omitted without losing required behavior?
- Does the codebase, standard library, or platform already solve the problem?
- Does a new abstraction remove duplication or clarify ownership, or does it only add wrappers, modes, and indirection for hypothetical uses?
- Does a refactor remove branches and concepts, or only move the same complexity elsewhere?
- For each finding, name what to delete or simplify and what replaces it. Respect real correctness, security, and performance requirements; fewer lines alone is not a reason to flag code.

### 3. Readability

- Are names descriptive and consistent with project conventions?
- Is the control flow direct, without nested ternaries, deep callbacks, or clever tricks?
- Is non-obvious intent explained, and is obvious code left uncommented?
- Did the change leave dead code or unnecessary compatibility shims?

### 4. Architecture

- Does the change follow existing patterns? Is any new pattern justified?
- Do dependencies flow in the right direction, without cycles or new coupling?
- **Does feature-specific logic leak into a shared module?** Keep logic in its owning layer and reuse the canonical helper instead of a near-duplicate.
- **Are type boundaries explicit?** Question gratuitous `any`, `unknown`, optional fields, casts, and silent fallbacks that hide an unclear invariant. An explicit boundary often removes downstream branches.
- **Is a new conditional bolted onto an unrelated flow?** Prefer a focused helper or policy when it makes ownership clearer.

### 5. Security

- Is every external input (users, APIs, files, logs, configuration) treated as untrusted and validated at the boundary before use in logic, queries, or rendering?
- Are authentication and authorization checked where needed?
- Are secrets kept out of code, logs, and version control?
- Are queries parameterized and outputs encoded?

### 6. Performance

- Are there N+1 queries, unbounded loops or fetches, or missing pagination?
- Is expensive work repeated in a hot path, such as rebuilding data on every call?
- Is blocking work done where asynchronous work is expected?

## Review Process

### Step 1: Understand the Context and Conventions

Before judging code, read the applicable repository instructions and conventions: root and nested `AGENTS.md` or equivalent files, README and contribution or architecture guidance, lint and formatter settings, test conventions, and representative existing code. Apply the guidance that covers each file. Distinguish documented rules from inferred patterns, and don't report a convention violation without evidence. Then set the scope:

- **Change review:** What requirement does the diff implement, which files and lines changed, and what surrounding code and tests do they affect?
- **Whole-project audit:** What are the entry points, components, tests, and relevant configuration, and which existing behaviors must be checked?

### Step 2: Review the Tests First

Tests show intent and coverage. Check that they exist, test behavior rather than implementation details, cover edge and error cases, have descriptive names, and would catch a regression.

### Step 3: Review the Implementation

For each changed file or in-scope component, walk through the six axes above.

### Step 4: Categorize Findings

Label every finding with its severity so the author knows what must change:

| Prefix | Meaning | Effect on the verdict |
|--------|---------|-----------------------|
| **Critical:** | Security vulnerability, data loss, or broken required behavior | Blocks approval |
| **Required:** | A change that must be made before merge | Blocks approval |
| **Consider:** | A worthwhile suggestion | Does not block |
| **Nit:** | Minor style or formatting point the author may ignore | Does not block |
| **FYI:** | Context only; no action needed | Does not block |

The verdict for a change review follows from the labels: **Request changes** when any Critical or Required finding remains; otherwise **Approve**.

**Lead with what matters.** Order findings by impact: correctness and security first, then structural regressions and missed simplifications, then the rest. A few high-conviction findings beat a long list of nits. Anchor every finding to the exact current file path and the smallest relevant line or range (a changed line for a pull request), and cite every affected location when one root cause spans files. Explain the failure or the unnecessary complexity, and give an actionable remedy. Verify line numbers from the file or diff; if a location is unavailable, say so. Don't invent impact figures or present unverified risks as facts.

### Step 5: Verify the Verification

Check the evidence supplied with the change or available in the project: which tests and build checks ran, manual testing, screenshots for UI changes, and before-and-after comparisons. Require only verification relevant to the change. When you cannot run a check or evidence is missing, say so instead of claiming it passed.

## Coverage and Consolidation

### Change reviews

Start with an inventory of every changed file and hunk against the intended base. Record added and removed lines, the change's purpose, and relevant tests or callers. A one-line edit may take one pass; above about 1,000 changed lines, plan bounded batches organized by related files or behavior. Size is never a reason to skip, sample, or reject a review; if a change also grows a file past about 1,000 lines, check whether it should extract a module. Do not substitute a diff summary, a sample, or a size-based rejection for reading the change.

### Whole-project audits

Inventory in-scope source, tests, configuration, manifests, and behavior-defining docs; inspect every in-scope file in subsystem batches; and report coverage by category with exclusions and reasons. Read [references/project-audit.md](references/project-audit.md) for the full procedure.

### Both modes

For each batch:

1. Inspect every changed hunk or in-scope project file and enough surrounding code to understand its behavior. Follow affected call sites, interfaces, tests, and data flows across files. For mechanical or generated changes, validate the generator or transformation against the full output and inspect exceptions; document the method rather than treating unexamined lines as reviewed.
2. Record which files and hunks were examined, what was verified, and candidate findings with precise file paths, line numbers or ranges, and concrete remedies. Keep a compact coverage ledger outside the final report if the review exceeds the current context; use it to resume rather than rereading or silently dropping batches.
3. Reconcile the ledger with the initial inventory and examine cross-batch interactions before writing the verdict. Combine duplicate symptoms under their shared root cause, but retain distinct actionable findings and cite each affected path.

Deliver one consolidated review after processing the full scope, not a stream of partial comments. Put all findings and their recommendations together in priority order before the checklist. For each finding, identify severity, affected lines, consequence, and the smallest sound fix. Give a concise coverage account (in-scope files reviewed versus inventoried, changed lines for PRs, exclusions, unreviewed areas, and verification not run). If any in-scope area remains unexamined, still report confirmed partial findings and uncovered areas, but mark the verdict **Incomplete review/audit**; never imply full coverage or approve on partial evidence. A completed repository audit reports whether action is needed; it does not approve an entire project for merge.

## Dead Code Hygiene

After a refactor or implementation change, check for newly orphaned code; in a whole-project audit, also check for existing dead code. Verify references before calling code unused, then flag confirmed dead code with a safe removal. If usage is uncertain, say what remains to check.

## Honesty in Review

- **Don't rubber-stamp.** "LGTM" without evidence of review helps no one.
- **Don't soften real issues.** Calling a production bug "a minor concern" is dishonest.
- **Quantify only from evidence.** "This loop issues one database query per item" beats an unsupported latency estimate.
- **Push back on approaches with clear problems.** Sycophancy is a review failure. Say what is wrong and propose an alternative.
- **Give AI-generated code more scrutiny, not less.** It is fluent and plausible even when wrong.

## Gotchas

- **Structural patterns need an explicit label.** These patterns always get a finding with a simpler design: a pass-through wrapper or single-implementation interface, a near-duplicate of an existing helper, feature logic placed in a shared module, a refactor that relocates complexity instead of reducing it, a change that significantly grows a large file without a cohesive boundary, and a silent fallback that hides an unclear invariant. In a change review, label it **Required:** when the change introduces the pattern and the simpler design is available within the change's scope, for example the canonical helper already exists or the wrapper has one caller. Otherwise, such as when the pattern is pre-existing or the fix needs work outside the change, label it **Consider:**. In a whole-project audit, everything is pre-existing: label it **Required:** when it violates a documented project convention or causes a correctness, security, or performance defect, and **Consider:** otherwise.
- **Necessary complexity is not overengineering.** A transaction, validation, or error path that a requirement needs is not a finding just because it adds lines.
- **Described tests are not run tests.** Tests described in a prompt or pull request are evidence of intent, not of a pass. Never claim a test or build passed unless you ran it or saw its output.
- **Check data against its source of truth mechanically.** When a change carries large tables or generated data, compare every entry against the authoritative source with a script or tool, including the first and last entries. A sample is not verification.
- **Silent defaults hide rejections.** A `?? 0`, `?? 'default'`, or fallthrough `return 0` where the spec requires rejection is a correctness finding, not a style point.
- **Supplied material is the scope.** When the user gives only an excerpt, snippet, or diff, review what was supplied; list unseen context such as callers or the full test suite under Verification not run. Still decide **Approve** or **Request changes** from the labels. Reserve **Incomplete review/audit** for material in scope that you could not inspect, and never use it to soften a Critical or Required finding.
- **Audits do not approve.** A whole-project audit ends with **Audit complete** (stating whether action is needed) or **Incomplete review/audit**, never with **Approve** or **Request changes**.

## The Review Checklist

Use this format for the single consolidated review or audit. Check only what the evidence supports; mark inapplicable items N/A, and identify relevant checks that could not be verified. Findings go first so the author can act without scanning every checklist item. If there are none, write "No findings." Group related findings by root cause, not by the batch in which they were discovered.

```markdown
## Review: [PR, change, or project]

### Findings
1. **Required:** `path/to/file.ext:42-45`: What fails or is unnecessary, why it matters, and the concrete fix. Cite additional precise locations for a cross-file cause.

### Coverage
- Scope and conventions checked: [change or project, and applicable guidance]
- In-scope files inspected: [number] / [number], by source, tests, and configuration where applicable
- Changed lines accounted for: [number] / [number] for change reviews; N/A for project audits
- Excluded areas and reasons: [paths, or none]
- Unreviewed areas: [paths and hunks, or none]
- Verification not run: [relevant checks, or none]

### Context
- [ ] I understand what this change does and why

### Correctness
- [ ] Change matches spec/task requirements
- [ ] Edge cases handled
- [ ] Error paths handled
- [ ] Tests cover the change adequately

### Overengineering
- [ ] Every new abstraction, option, and dependency has a concrete use
- [ ] Existing utilities or platform features are reused where simpler
- [ ] Refactors reduce moving parts rather than relocating them

### Readability
- [ ] Names are clear and consistent
- [ ] Logic is straightforward
- [ ] Non-obvious logic is explained where needed

### Architecture
- [ ] Follows existing patterns
- [ ] No unnecessary coupling
- [ ] Ownership and type boundaries are clear
- [ ] No feature logic leaks into shared modules

### Security
- [ ] No secrets in code
- [ ] Input validated at boundaries
- [ ] No injection vulnerabilities
- [ ] Auth checks in place
- [ ] External data sources treated as untrusted

### Performance
- [ ] No N+1 patterns
- [ ] No unbounded operations
- [ ] Pagination on list endpoints

### Verification
- [ ] Relevant tests pass, or unrun tests are identified
- [ ] Relevant build checks pass, or unrun checks are identified
- [ ] Manual verification done (if applicable)

### Verdict
- [ ] **Approve** — Change review only; no Critical or Required findings remain
- [ ] **Request changes** — Change review only; Critical or Required findings must be addressed
- [ ] **Audit complete** — Project audit only; state whether findings require action
- [ ] **Incomplete review/audit** — Partial findings reported; in-scope areas remain unexamined
```

## Before Delivering the Review

- [ ] Every in-scope file and hunk is reconciled with the coverage ledger, or the verdict is **Incomplete review/audit**
- [ ] Every finding has a severity label, a precise location, a consequence, and a remedy
- [ ] The verdict matches the labels: no **Approve** while a Critical or Required finding remains
- [ ] Tests and build checks are reported as run, with their result, or as not run
- [ ] If the change adds or upgrades dependencies, they were reviewed with [references/dependencies.md](references/dependencies.md)

---
name: code-review
description: Review code changes or audit an entire repository for correctness, overengineering, readability, architecture, security, and performance. Use for PRs, diffs, bug fixes, refactors, agent-generated code, and whole-project codebase audits. Read project conventions first; report consolidated findings, coverage, and a verdict.
---

# Code Review and Quality

## Overview

Multi-dimensional review with quality gates. Review the entire change and relevant surrounding code before recommending a merge, whether the diff is one line or more than 15,000. For a whole-project audit, inspect the existing repository rather than looking for a diff. Cover six axes: correctness, overengineering, readability, architecture, security, and performance.

**The approval standard for changes:** Approve when the change meets its requirements without unresolved required findings, even if it isn't how you would have written it. Don't block a PR on stylistic preferences or unrelated pre-existing problems; in a whole-project audit, those existing problems are in scope. Note verification gaps honestly.

## When to Use

- Before merging any PR or change
- After completing a feature implementation
- When another agent or model produced code you need to evaluate
- When refactoring existing code
- After any bug fix (review both the fix and the regression test)
- When asked to audit or review the entire repository, including existing source, tests, and relevant configuration

## The Six-Axis Review

Evaluate each axis where relevant. Report concrete findings rather than filling a quota for each axis; focus on change-related issues for PRs and existing issues throughout the in-scope repository for whole-project audits.

### 1. Correctness

Does the code do what it claims to do?

- Does it match the spec or task requirements?
- Are edge cases handled (null, empty, boundary values)?
- Are error paths handled (not just the happy path)?
- Were relevant tests run? Do they test the right behavior?
- Are there off-by-one errors, race conditions, or state inconsistencies?

### 2. Overengineering

Does the change introduce more moving parts than the required behavior warrants?

- Can new code, a configuration option, or a compatibility path be omitted without losing required behavior?
- Does the existing codebase, standard library, or platform already solve the problem?
- Does a new abstraction remove duplication or clarify ownership, or merely add wrappers, modes, and indirection for hypothetical uses?
- Does a dependency earn its maintenance and integration cost compared with existing utilities?
- Does the refactor actually remove branches and concepts, rather than move the same complexity elsewhere?
- For each finding, identify what to delete or simplify and what would replace it. Account for genuine correctness, security, and performance requirements; fewer lines alone are not a reason to flag code.

### 3. Readability

Can another engineer (or agent) understand this code without the author explaining it?

- Are names descriptive and consistent with project conventions?
- Is the control flow straightforward (avoid nested ternaries, deep callbacks)?
- Is the code organized logically (related code grouped, clear module boundaries)?
- Are there any "clever" tricks that should be simplified?
- Would comments help clarify non-obvious intent? (But don't comment obvious code.)
- Are there newly introduced dead code artifacts or unnecessary compatibility shims?

### 4. Architecture

Does the change fit the system's design?

- Does it follow existing patterns or introduce a new one? If new, is it justified?
- Does it maintain clean module boundaries?
- Is there code duplication that should be shared?
- Are dependencies flowing in the right direction (no circular dependencies)?
- Is the abstraction level appropriate for the module's responsibilities?
- **Is feature-specific logic leaking into a shared or general-purpose module?** Keep logic in its owning layer, reuse the existing canonical helper instead of a near-duplicate, and don't normalize architectural drift.
- **Are type boundaries explicit?** Question gratuitous `any`/`unknown`/optional/casts and silent fallbacks that paper over an unclear invariant — making the boundary explicit often makes the surrounding control flow simpler.
- **Is a new conditional bolted onto an unrelated flow?** Consider a focused helper or policy when it makes ownership clearer, rather than scattering the same decision across paths.

### 5. Security

Does the change introduce vulnerabilities?

- Is user input validated and sanitized?
- Are secrets kept out of code, logs, and version control?
- Is authentication/authorization checked where needed?
- Are SQL queries parameterized (no string concatenation)?
- Are outputs encoded to prevent XSS?
- Are dependencies from trusted sources with no known vulnerabilities?
- Is data from external sources (APIs, logs, user content, config files) treated as untrusted?
- Are external data flows validated at system boundaries before use in logic or rendering?

### 6. Performance

Does the change introduce performance problems?

- Any N+1 query patterns?
- Any unbounded loops or unconstrained data fetching?
- Any synchronous operations that should be async?
- Any unnecessary re-renders in UI components?
- Any missing pagination on list endpoints?
- Any large objects created in hot paths?

## Structural Remedies

When you flag a structural problem, propose the move — not just the problem. A review that only says "this is complex" leaves the author guessing. Reach for a named restructuring:

- **Replace repeated conditionals** with a typed model or dispatcher when it removes duplication.
- **Collapse duplicate branches** into a single clearer flow.
- **Separate orchestration from business logic** so each reads on its own.
- **Move feature-specific logic** out of a shared module into the package that owns the concept.
- **Reuse the canonical helper** instead of a bespoke near-duplicate.
- **Make a type boundary explicit** so downstream branching disappears.
- **Delete a pass-through wrapper** that adds indirection without clarifying the API.
- **Extract a helper, or split a large file** when the result has clearer ownership and fewer concepts to track.

Prefer the remedy that removes moving pieces over one that spreads the same complexity around.

## Change Sizing

Small, focused changes are easier to review. Treat these sizes as prompts to inspect cohesion, not reasons to skip a review or demand a split:

```
~100 lines changed: Usually reviewable in one sitting.
~300 lines changed: Check that it is one logical change.
~1000+ lines changed: Plan multiple review batches and consider a coherent split.
```

**Watch file size, not just diff size.** A small diff can still push a file past a healthy boundary — around 1000 *total* lines in a single file (distinct from the ~1000 *changed*-lines threshold above) is a common inspection signal, not a hard cap. When a change materially grows an already-large file, ask whether to extract helpers, subcomponents, or modules *first*, before piling more on. Decompose, then add.

**What counts as "one change":** A coherent modification with its related tests that keeps the system functional. A complete feature may be one change when it remains reviewable.

**Splitting strategies when a change is too large:**

| Strategy | How | When |
|----------|-----|------|
| **Stack** | Submit a small change, start the next one based on it | Sequential dependencies |
| **By file group** | Separate changes for groups needing different reviewers | Cross-cutting concerns |
| **Horizontal** | Create shared code/stubs first, then consumers | Layered architecture |
| **Vertical** | Break into smaller full-stack slices of the feature | Feature work |

**When large changes are acceptable:** A cohesive feature, complete file deletions, or a verifiable automated refactor may span many files. A 15,000-line diff still deserves a complete review; split it only when doing so creates independently reviewable changes.

**Separate unrelated refactoring from feature work.** Keep refactoring needed for the behavior in the same change when splitting it would obscure the implementation.

## Change Descriptions (PR Reviews)

Every change needs a description that stands alone in version control history.

**First line:** Short, imperative, standalone. "Delete the FizzBuzz RPC" not "Deleting the FizzBuzz RPC." Must be informative enough that someone searching history can understand the change without reading the diff.

**Body:** What is changing and why. Include context, decisions, and reasoning not visible in the code itself. Link to bug numbers, benchmark results, or design docs where relevant. Acknowledge approach shortcomings when they exist.

**Anti-patterns:** "Fix bug," "Fix build," "Add patch," "Moving code from A to B," "Phase 1," "Add convenience functions."

## Review Process

### Step 1: Understand the Context and Conventions

Before judging code, read applicable repository instructions and project conventions: root and nested `AGENTS.md` or equivalent, README and contribution/architecture guidance, lint and formatter settings, test conventions, and representative existing code. Follow guidance that applies to each file; distinguish documented rules from inferred patterns and don't report a convention violation without evidence. Then establish the review scope:

```
- Change review: What requirement does the diff implement, which files and lines changed, and what surrounding code or tests affect them?
- Whole-project audit: What are the project's entry points, components, tests, and relevant configuration, and which existing behaviors should be checked?
```

### Step 2: Review the Tests First

Tests reveal intent and coverage:

```
- Do tests exist for the change?
- Do they test behavior (not implementation details)?
- Are edge cases covered?
- Do tests have descriptive names?
- Would the tests catch a regression if the code changed?
```

### Step 3: Review the Implementation

Walk through the code with the six axes in mind:

```
For each changed file or in-scope project component:
1. Correctness: Does this code match its requirements and tests?
2. Overengineering: Can unnecessary parts be removed or replaced with existing code?
3. Readability: Can I understand this without help?
4. Architecture: Does this fit the system?
5. Security: Any vulnerabilities?
6. Performance: Any bottlenecks?
```

### Step 4: Categorize Findings

Label every comment with its severity so the author knows what's required vs optional:

| Prefix | Meaning | Author Action |
|--------|---------|---------------|
| **Required:** | Required change | Must address before merge |
| **Critical:** | Blocks merge | Security vulnerability, data loss, broken functionality |
| **Nit:** | Minor, optional | Author may ignore — formatting, style preferences |
| **Optional:** / **Consider:** | Suggestion | Worth considering but not required |
| **FYI** | Informational only | No action needed — context for future reference |

This prevents authors from treating all feedback as mandatory and wasting time on optional suggestions.

**Lead with what matters.** Order findings by leverage: correctness and security first, then structural regressions and missed simplifications, then everything else. Don't bury a real issue under cosmetic nits — a few high-conviction comments beat a long list. Anchor every finding to the exact current file path and smallest relevant line or line range (a changed line for PRs); cite all affected locations when a root cause spans files. Explain the failure or unnecessary complexity and an actionable remedy. Verify line numbers from the file or diff instead of guessing; if a location is unavailable, say so explicitly. Don't invent impact figures or present unverified risks as established facts.

### Step 5: Verify the Verification

Check the verification evidence supplied with a change or available in the project:

```
- What tests were run?
- Did the build pass?
- Was the change tested manually?
- Are there screenshots for UI changes?
- Is there a before/after comparison?
```

When verification cannot be run or evidence is unavailable, say so instead of claiming it passed. Only require verification relevant to the change.

## Coverage and Consolidation

### Change reviews

Start with an inventory of every changed file and hunk against the intended base. Record added and removed lines, the change's purpose, and relevant tests or callers. A one-line edit may take one pass; a large pull request needs bounded batches organized by related files or behavior. Do not substitute a diff summary, a sample, or a size-based rejection for reading the change.

### Whole-project audits

Inventory the project before assessing it: in-scope source, tests, relevant build and deployment configuration, dependency manifests, and documentation that defines behavior or conventions. Exclude generated, vendored, or cached content only with a stated reason; include any first-party generators and their outputs when correctness depends on them. Map entry points and module boundaries, then inspect every in-scope file in bounded subsystem batches. Follow calls, data flows, and test coverage across batches. Findings may concern any existing code, not just recently changed lines. Record file and line coverage by category (source, tests, configuration), plus excluded and unexamined paths; line-count coverage of a diff is not applicable.

### Both modes

For each batch:

1. Inspect every changed hunk or in-scope project file and enough surrounding code to understand its behavior. Follow affected call sites, interfaces, tests, and data flows across files. For mechanical or generated changes, validate the generator or transformation against the full output and inspect exceptions; document the method rather than treating unexamined lines as reviewed.
2. Record which files and hunks were examined, what was verified, and candidate findings with precise file paths, line numbers or ranges, and concrete remedies. Keep a compact coverage ledger outside the final report if the review exceeds the current context; use it to resume rather than rereading or silently dropping batches.
3. Reconcile the ledger with the initial inventory and examine cross-batch interactions before writing the verdict. Combine duplicate symptoms under their shared root cause, but retain distinct actionable findings and cite each affected path.

Deliver one consolidated review after processing the full scope, not a stream of partial comments. Put all findings and their recommendations together in priority order before the checklist. For each finding, identify severity, affected lines, consequence, and the smallest sound fix. Give a concise coverage account (in-scope files reviewed versus inventoried, changed lines for PRs, exclusions, unreviewed areas, and verification not run). If any in-scope area remains unexamined, still report confirmed partial findings and uncovered areas, but mark the verdict **Incomplete review/audit**; never imply full coverage or approve on partial evidence. A completed repository audit reports whether action is needed; it does not approve an entire project for merge.

## Dead Code Hygiene

After a refactoring or implementation change, check for newly orphaned code; in a whole-project audit, also check for existing dead code:

1. Identify code that is now unreachable or unused
2. Verify references before calling it unused
3. Flag confirmed dead code as a finding with a safe removal suggestion; if usage is uncertain, explain what remains to check

## Handling Disagreements

When resolving review disputes, apply this hierarchy:

1. **Technical facts and data** override opinions and preferences
2. **Style guides** are the absolute authority on style matters
3. **Software design** must be evaluated on engineering principles, not personal preference
4. **Codebase consistency** is acceptable if it doesn't degrade overall health

**Don't accept "I'll clean it up later" for required findings.** Unrelated pre-existing issues can be tracked separately rather than blocking this change.

## Honesty in Review

When reviewing code — whether written by you, another agent, or a human:

- **Don't rubber-stamp.** "LGTM" without evidence of review helps no one.
- **Don't soften real issues.** "This might be a minor concern" when it's a bug that will hit production is dishonest.
- **Quantify problems when evidence allows.** "This loop issues one database query per item" is more useful than an unsupported latency estimate.
- **Push back on approaches with clear problems.** Sycophancy is a failure mode in reviews. If the implementation has issues, say so directly and propose alternatives.
- **Accept override gracefully.** If the author has full context and disagrees, defer to their judgment. Comment on code, not people — reframe personal critiques to focus on the code itself.

## Dependency Discipline

Part of code review is dependency review:

**Before adding any dependency:**
1. Does the existing stack solve this? (Often it does.)
2. How large is the dependency? (Check bundle impact.)
3. Is it actively maintained? (Check last commit, open issues.)
4. Does it have known vulnerabilities? Use the project's existing advisory tooling where available.
5. What's the license? (Must be compatible with the project.)

**Rule:** Prefer standard library and existing utilities over new dependencies. Every dependency is a liability.

**Upgrading an existing dependency** is a code change like any other, and the riskiest upgrades are the ones merged in bulk with a message like "bump deps." Review them with the same discipline:

1. **Read the changelog, not just the version number.** Semver is a promise the maintainer may not have kept — a "patch" can carry a behavioral change. For a major bump, read the migration notes and find what breaks.
2. **Prefer isolated upgrades.** Upgrade individually or in small related groups when practical; bulk bumps hide which package introduced a break.
3. **Let the tests decide.** The upgrade is verified by a green suite before *and* after, not by "it installed." If coverage around the dependency's behavior is thin, that gap is the real finding — add a test first.
4. **Mind the transitive graph.** Most installed packages are ones nobody chose directly. Review the lockfile diff, not just `package.json`; a single direct bump can pull in dozens of indirect changes.
5. **Keep the lockfile honest.** Commit it, review its diff, and never hand-edit it. The lockfile is the thing that actually pins what ships.

For advisory or supply-chain findings, report the affected package, version, exposure path, and evidence. Do not infer exploitability from an advisory alone.

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
- [ ] **Approve** — Change review only; ready to merge
- [ ] **Request changes** — Change review only; issues must be addressed
- [ ] **Audit complete** — Project audit only; state whether findings require action
- [ ] **Incomplete review/audit** — Partial findings reported; in-scope areas remain unexamined
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It works, that's good enough" | Working code that's unreadable, insecure, or architecturally wrong creates debt that compounds. |
| "I wrote it, so I know it's correct" | Authors are blind to their own assumptions. Every change benefits from another set of eyes. |
| "We'll clean it up later" | Resolve required issues introduced by this change before merge; track unrelated pre-existing work separately. |
| "AI-generated code is probably fine" | AI code needs more scrutiny, not less. It's confident and plausible, even when wrong. |
| "The tests pass, so it's good" | Tests are necessary but not sufficient. They don't catch architecture problems, security issues, or readability concerns. |
| "The refactor makes it cleaner" | Relocating complexity isn't reducing it. If the reader still holds the same number of concepts, the structure didn't improve — look for the version where branches disappear. |
| "It's only a small addition to this file" | Small diffs still push files past a healthy size and bolt branches onto unrelated flows. Judge the resulting structure, not the diff size. |
| "It's just a version bump" | A bump is a behavior change you didn't write. Read the changelog; semver doesn't guarantee no breakage. |
| "I'll upgrade everything in one PR to save time" | A bulk bump that breaks the build hides which package did it. Prefer isolated upgrades or small related groups. |

## Red Flags

- PRs merged without any review
- Review that only checks if tests pass (ignoring other axes)
- "LGTM" without evidence of actual review
- New wrappers, modes, or dependencies without a concrete use
- Security-sensitive changes without security-focused review
- Large PRs that cannot be reviewed coherently (look for a meaningful split)
- No regression tests with bug fix PRs
- Review comments without severity labels — makes it unclear what's required vs optional
- Accepting "I'll fix it later" — it never happens
- A refactor that moves code around without reducing the number of concepts a reader must hold
- A change that significantly grows an already-large file without a cohesive boundary
- New conditionals scattered into unrelated code paths (a missing abstraction)
- A bespoke helper that duplicates an existing canonical one, or feature logic placed in a shared module
- A bulk "bump dependencies" PR with no changelog review or clear grouping
- A lockfile change that's hand-edited, uncommitted, or merged without reviewing its diff

## Verification

After review is complete:

- [ ] All Critical issues are resolved
- [ ] All Required findings are resolved before recommending merge
- [ ] Relevant tests pass, or the absence of a run is documented
- [ ] Relevant build checks pass, or the absence of a run is documented
- [ ] The verification story is documented (what changed, how it was verified)
- [ ] Dependency upgrades were reviewed against their changelog, grouped coherently, and verified with relevant tests and the lockfile diff

For a whole-project audit, report existing Critical and Required issues as findings instead of treating them as prerequisites for completing the audit. Reconcile the project inventory with the coverage ledger, and mark the audit incomplete if any in-scope files remain unexamined.

**Presumptive blockers:** surface and propose the simpler design for each of these; escalate to Required only when the change actively makes structure worse: a refactor that relocates complexity instead of reducing it; a change that significantly grows a large file without a cohesive boundary; feature logic added to a shared module; a near-duplicate of an existing canonical helper; a silent fallback that hides an unclear invariant.

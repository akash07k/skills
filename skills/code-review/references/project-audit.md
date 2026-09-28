# Whole-Project Audits

Read this when asked to audit an entire repository rather than review a change.

## Inventory and coverage

Inventory the project before assessing it: in-scope source, tests, relevant build and deployment configuration, dependency manifests, and documentation that defines behavior or conventions. Exclude generated, vendored, or cached content only with a stated reason; include any first-party generators and their outputs when correctness depends on them. Map entry points and module boundaries, then inspect every in-scope file in bounded subsystem batches. Follow calls, data flows, and test coverage across batches. Findings may concern any existing code, not just recently changed lines. Record file and line coverage by category (source, tests, configuration), plus excluded and unexamined paths; line-count coverage of a diff is not applicable.

## Labels and verdict

In an audit, every problem is pre-existing. Label a structural pattern **Required:** when it violates a documented project convention or causes a correctness, security, or performance defect, and **Consider:** otherwise. End with **Audit complete** (state whether action is needed) or **Incomplete review/audit**, never **Approve** or **Request changes**. Leave the "Changed lines accounted for" coverage line as N/A.

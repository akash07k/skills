# Change Hygiene

Read this when a change is very large or mixes unrelated work, when its
description needs review, or when the author disputes a finding.

## Change sizing

Size prompts a cohesion check; it is never a reason to skip a review or to demand a split. Review small changes in one pass when practical. For large changes, use bounded batches and reconcile them into one review. There is no upper size cutoff.

**Consider the whole file, not just the diff.** When a change materially grows a file, consider extraction only if it improves ownership or clarity; length alone does not require a split.

## Splitting a large change

Size alone is never a reason to skip or reject a review. Suggest a split only
when it produces changes that can each be reviewed and verified on their own.

| Strategy | How | When |
|----------|-----|------|
| **Stack** | Submit a small change, then base the next one on it | Sequential dependencies |
| **By file group** | Separate changes for groups needing different reviewers | Cross-cutting concerns |
| **Horizontal** | Create shared code or stubs first, then consumers | Layered architecture |
| **Vertical** | Break the feature into smaller full-stack slices | Feature work |

Large changes are acceptable when they are cohesive: one feature, complete
file deletions, or a verifiable automated refactor. Separate unrelated
refactoring from feature work, but keep refactoring the behavior needs in the
same change when splitting it would obscure the implementation.

## Change descriptions

A change description must stand alone in version-control history.

- **First line:** short, imperative, and standalone. "Delete the FizzBuzz RPC",
  not "Deleting the FizzBuzz RPC". Someone searching history should understand
  the change without reading the diff.
- **Body:** what changes and why, including context, decisions, and reasoning
  that the code does not show. Link bugs, benchmarks, or design documents.
  Acknowledge known shortcomings of the approach.
- **Weak descriptions:** "Fix bug", "Fix build", "Add patch", "Moving code from
  A to B", "Phase 1", "Add convenience functions".

## Handling disagreements

Resolve review disputes in this order:

1. Technical facts and data override opinions and preferences.
2. The project's style guide is the authority on style.
3. Judge software design by engineering principles, not personal preference.
4. Consistency with the codebase is acceptable when it does not degrade
   overall health.

Do not accept "I'll clean it up later" for a Critical or Required finding that
the change introduces. Unrelated pre-existing issues can be tracked separately.
When the author has full context and still disagrees on a non-blocking point,
defer to them. Comment on the code, not the person.

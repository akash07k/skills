# Structural Remedies

Read this when you flag a structural problem and need a concrete remedy.

When you flag a structural problem, propose the move, not just the problem:

- **Replace repeated conditionals** with a typed model or dispatcher when it removes duplication.
- **Collapse duplicate branches** into a single clearer flow.
- **Separate orchestration from business logic** so each reads on its own.
- **Move feature-specific logic** out of a shared module into the package that owns the concept.
- **Reuse the canonical helper** instead of a near-duplicate.
- **Make a type boundary explicit** so downstream branching disappears.
- **Delete a pass-through wrapper** that adds indirection without clarifying the API.
- **Extract a helper or split a large file** when the result has clearer ownership and fewer concepts.

Prefer the remedy that removes moving pieces over one that spreads the same complexity around.

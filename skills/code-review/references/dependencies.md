# Dependency Review

Read this when a change adds, removes, or upgrades a dependency, or edits a
dependency manifest or lockfile.

## Adding a dependency

1. Does the existing stack, standard library, or an installed package already
   solve this?
2. What does it cost in size, install time, and integration surface?
3. Is it actively maintained?
4. Does it have known vulnerabilities? Use the project's existing advisory
   tooling where available.
5. Is its license compatible with the project?

Prefer the standard library and existing utilities. Every dependency is a
maintenance and supply-chain liability that must earn its place.

## Upgrading a dependency

An upgrade is a behavior change the author did not write. Review it like any
other code change:

1. **Read the changelog, not just the version number.** A "patch" release can
   change behavior. For a major bump, read the migration notes and find what
   breaks.
2. **Prefer isolated upgrades.** Upgrade one package or a small related group
   at a time. A bulk "bump deps" change hides which package caused a break.
3. **Let the tests decide.** The suite must pass before and after the upgrade.
   If tests barely exercise the dependency's behavior, that gap is the finding;
   ask for a test first.
4. **Review the transitive graph.** Read the lockfile diff, not only the
   manifest. One direct bump can pull in many indirect changes.
5. **Keep the lockfile honest.** It must be committed, its diff reviewed, and
   never hand-edited.

## Findings to raise

- A new dependency that duplicates an existing utility or a few lines of code
- A bulk upgrade with no changelog review or coherent grouping
- A lockfile that is hand-edited, missing, or changed without review
- A major upgrade without migration evidence or a test run

For advisory or supply-chain findings, report the affected package, version,
exposure path, and evidence. Do not infer exploitability from an advisory
alone.

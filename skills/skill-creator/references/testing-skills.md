# Testing skill behavior

Read this file when choosing tests, studying baseline failures, or evaluating
changes to skill instructions. Use the existing workspace, grading, and
viewer tools in `references/running-evals.md`. These methods do not require
Superpowers, another runner, or a particular agent host.

## Contents

- [Choose tests](#choose-tests-for-the-skill) and [observe, draft, retest](#observe-draft-and-retest)
- [Discovery and execution](#separate-discovery-from-execution)
- [Test quality](#check-the-tests-themselves) and [production and review](#test-production-and-review-separately)
- [Wording micro-tests](#wording-micro-tests) and [pressure tests](#pressure-tests-for-discipline)
- [Follow-up diagnosis](#follow-up-diagnosis)
- [Comparisons and confirmation](#independent-comparisons-and-confirmation)
- [Experiment decisions](#retain-experiment-decisions) and [report-shape example](#example-a-report-with-the-wrong-shape)

## Choose tests for the skill

A baseline is the agent's behavior without the candidate instructions.
For an existing skill, its unchanged version can serve as the baseline.
Recommend baseline-first authoring, then honor the user's chosen evidence path.

| Skill type | Useful scenarios | Evidence of success |
| --- | --- | --- |
| Technique | Apply the method, vary inputs, omit needed information | Correct application to the task and its variations |
| Pattern | Recognize a suitable case, apply the pattern, reject a counterexample | Correct selection and use, without applying it everywhere |
| Reference | Find a fact, use it, handle a missing or ambiguous entry | Correct retrieval and application, or an explicit gap |
| Discipline | Understand the rule, execute a task, face competing incentives | Required behavior in the task, not just reciting the rule |
| Mixed | Combine the relevant scenarios | Evidence for each behavior the skill promises |

For subjective work, use agreed quality criteria and human or blind review.
Do not turn taste into an arbitrary pass/fail assertion.
Recommend pressure scenarios for discipline skills by default.
Recommend repeated wording tests for behavior-shaping guidance by default.
Pure reference skills need retrieval and application tests, not pressure or
wording tests unless they also promise those behaviors.
Explain the host, model, sessions, and known cost or quota implications.
Obtain approval for the selected tests and budget before running them.
Honor lighter paths. State which applicable tests were not run and report
the actual sample counts when they are lower than recommended.

## Observe, draft, and retest

1. Agree on representative prompts, inputs, expected behavior, and run budget.
2. Derive the criteria from requirements before examining agent outputs.
3. Run a fresh baseline. Save its outputs and available transcript.
4. Identify the exact gap. Distinguish a behavioral failure from a broken
   tool, unavailable input, or invalid test setup.
5. Write the smallest guidance or reusable tool that addresses that gap.
6. Run the candidate and baseline on the same tasks under comparable conditions.
7. Keep successful cases when revising. Add fresh tasks to test generalization.

State the selected path, required outcomes, and session budget before execution.
Use the host's task list for real prerequisites, not ritual announcements.
If a prerequisite fails, stop that dependent step and explain the missing evidence.

Record the choices the agent made, sections it read, missed references,
outputs it produced, and any stated reasons for skipping a requirement.
Quote reasons only when the transcript contains them. Do not invent the
agent's internal reasoning.

If the baseline passes, do not manufacture a failure or discard useful work.
Look for another agreed gap, or report no demonstrated gain on these tasks.
Skills can also save repeated explanations or organize references.
Those benefits are distinct from an improved task score.

Existing drafts do not need deletion to enter this loop. Keep an unchanged
copy for comparison. If the user chooses draft-only or informal review,
continue and label the limits of that evidence.

## Separate discovery from execution

Measure whether the agent selects the skill separately from whether it uses
the skill correctly. A trigger probe does not execute and grade the task.
Likewise, a task that explicitly loads a skill does not prove natural discovery.

Observe which instructions and references the executor actually reads.
If it skips a necessary file, improve its reading cue or placement.
If it repeatedly reloads one fact, consider moving that fact into SKILL.md.
If it never uses a resource, determine whether the resource is unnecessary
or its purpose is unclear.

Use fresh executor contexts that do not inherit the author's corrections,
expected answer, or earlier test results. Include the realistic task context,
tools, inputs, and instructions for each configuration. Check the host's
context inheritance and skill-loading behavior instead of assuming isolation.
This isolates measurements, not filesystem access.

Keep the host, model, tool availability, task, and input files comparable.
Save the skill version or unchanged copy used in each configuration.
For another intended host or model, repeat the relevant tests there.
Do not describe one host's results as universal compatibility.

## Check the tests themselves

Before adding a check, name the realistic break that it must catch.
Derive the expected result independently from the skill or generated output.
Use known inputs, hand-checked expected values, and the actual artifacts.

Test substance rather than a filename, a tool call, or a claimed success.
For example, a report with correct headings but incorrect totals must fail
the totals check. A reference test must distinguish a correct lookup from
an answer that merely repeats the query.

Offer a mutation check when assertions look weak. A mutation is a deliberate
wrong result used to test the checker. Try a wrong value, omitted field,
empty output, or wrong branch on a disposable example. The relevant check
must fail. An unrelated tool crash does not prove that it catches the defect.

For bundled scripts, test the real command's outputs, exit codes, and effects.
Keep expectations independent of the implementation. Use mocks only for the
necessary external operation, and preserve the side effects the test needs.
Keep test-only helpers in test utilities, not production code.

Keep acceptance checks that both configurations pass. Report them as
non-discriminating in that comparison. Do not remove them to inflate the
measured improvement. Record eval critiques separately from the frozen score.

Keep mocks below the behavior being tested. Mock an external fetch, not the
validation branch whose behavior the test promises to examine.
Use complete response fixtures when later code reads their fields.
If mock setup hides required side effects, use a focused integration check.
Use `references/worked-example.md` for good and bad checker examples.

## Test production and review separately

Some skills promise to produce an artifact and then find defects in it.
These are separate behaviors. Name both before editing the instructions.

| Behavior | Test |
| --- | --- |
| Production | Generate an artifact from known inputs and inspect its facts and structure |
| Recognition | Supply an artifact with a known defect and observe the review identify it |

If a prohibition becomes a positive recipe, retain useful detection rules at
the review step. An improved first draft does not prove that review still works.
Seed a wrong value, missing evidence, or another relevant defect in a disposable artifact.
Keep the reviewer independent when that is part of the agreed test.
A grader rejecting the defect does not prove that the skill's own reviewer detects it.

Score production and recognition separately. Include both stages in the session budget.
If the control already succeeds at both, record no demonstrated need for a rewrite.

## Wording micro-tests

A micro-test is a small experiment comparing instruction wordings.
Recommend it by default for new or changed behavior-shaping guidance,
even when no failure has yet been observed.
It does not replace complete task runs or pressure scenarios.

1. Choose an observed failure or an agreed behavior to examine.
   Use a realistic task that can expose the behavior without inventing a failure.
2. Compare a no-guidance control with a small number of wording variants.
   Change the wording, not the task, tools, or other instructions.
3. Use the realistic surrounding skill or template in each variant.
   Put the same required task information in every variant.
   When testing wording form, express equivalent requirements in each wording.
   A control omits added guidance, not the task requirements.
   For each sample, start a fresh context.
4. Recommend at least five samples per variant, including the control.
   Agree on the total sessions before running. Two variants plus a control,
   with five samples each on one task, require 15 fresh samples.
   Tool use and extra turns can require several model requests per session.
5. Score the required behavior or output shape. Read every flagged match
   manually to distinguish actual violations from quotes or template echoes.
6. Compare both success rates and variation between samples.
   Describe recurring interpretations, not just the average score.
7. Confirm a selected wording on fresh tasks and full execution runs.

If the control does not expose the suspected failure, do not claim a wording
fix or invent a baseline failure. Record the successful control.
Reconsider the test or stop that experiment within the agreed plan.
This does not prohibit creating a skill for a different demonstrated need.

Use explicit contracts and observable conditions from
`references/writing-skills.md`. Do not assume that prohibitions, stronger
language, or extra exceptions improve every kind of output.

## Pressure tests for discipline

A pressure test adds realistic incentives to skip an agreed requirement.
Recommend it by default for discipline skills, not for every technique or reference.
Include the scenario, number of sessions, host, model, and known cost or quota
implications in the proposed plan. Ask for approval before execution.
Academic questions can expose misunderstanding, but correct answers do not
prove that an agent follows the rule while executing a task.

Use an agreed scenario with concrete inputs, constraints, and observable
actions. Add relevant competing pressures, such as a deadline, completed
work that takes effort to revise, or a request to prioritize speed.
Combine pressures when that reflects the intended use. Three pressures are
a useful candidate, not a universal minimum.

Ask the executor to act, not just state the ideal answer.
Do not force an A/B choice that excludes a legitimate solution.
Clarifying missing information can be correct behavior.
Mark simulated constraints as scenario facts, not real emergencies.

Pair a shortcut scenario with a credible permitted-action scenario when useful.
Make the pressures and task context comparable.
Check that the fixtures support both outcomes before execution.
Inspect whether the executor rejects the shortcut and performs the permitted action.
This catches a rule that rejects every action.

If the agent skips a rule that it understood, capture its stated workaround.
Explain why that workaround fails the actual requirement. Add a short
counterexample, rule-skipping table, or warning cue only for the observed gap.
If the output has the wrong shape instead, use a positive recipe.

Connect an observed workaround to the governing requirement, the point of
action, and a recognition cue. Update discovery symptoms only when they
describe when the skill needs to load. Do not put workflow instructions in
the description or require every source correction layer for every failure.

Retest the original case and fresh variations. Stop at the agreed budget
or criteria. Report the scenarios and failure rates observed.
Do not claim that the skill resists every possible pressure.

## Follow-up diagnosis

After a failure, an optional follow-up can ask the executor what it read,
what information was missing, or which wording it found unclear.
Treat its answer as a hypothesis, not proof of the cause.
Do not ask it to justify a predetermined winner or prescribed rewrite.

Separate three possible problems:

- Understanding: Explain the missing concept or requirement.
- Navigation: Move the instruction or add a specific reading cue.
- Execution: Change the guidance form, example, or reusable tool.

Test proposed changes in a fresh context. A coached executor's second
attempt does not independently confirm the fix.

## Independent comparisons and confirmation

Use a reviewer that did not author the candidate or see its expected answer,
when the host and agreed budget permit. Keep the rubric fixed before showing
outputs. Use anonymous A/B labels and keep the source mapping outside the
comparator's context. Do not pass skill names or revealing source paths.

If reviewer order appears to affect the result, offer fresh comparisons
with A/B reversed. Record disagreements instead of selecting only favorable
judgments. Use `agents/comparator.md` for the result contract.
A genuine tie and insufficient evidence are different outcomes.
Check agreed mandatory requirements before preferences. A higher formatting
score cannot compensate for a failed mandatory requirement.

Separate exploration from confirmation. Scenarios used to select the best
wording are selection evidence, even if they began as a held-out set.
Use new tasks or queries for an independent estimate. Do not repeatedly
select changes on the confirmation set and keep calling it independent.

Keep confirmation tasks and criteria outside the loaded skill and executor's
workspace until the run. Supply the task and its required inputs at execution.
Keep the expected answers, other confirmation cases, and grader criteria
outside the executor context. Exclude development `evals/` from both skill
snapshots when it contains the confirmation set. Use the same exclusions for
both configurations. If the skill needs those files to perform its work,
declare that dependency and use a separate inaccessible confirmation source.
If confirmation results guide another revision, use new tasks to confirm it.

Report the number of runs, failures, missing evidence, known tradeoffs,
and which host and model produced the results. Include time and token data
only when observed. Five successful samples do not establish perfect
reliability. A single preferred output does not establish a general winner.

## Retain experiment decisions

Save the task, skill versions, exact variants, criteria, outputs, and observed
host/model information in the agreed workspace.
Record the decision in the existing analysis notes or `outputs/user_notes.md`.
Include the following facts:

- The failure or hypothesis that motivated the experiment.
- Control results, variant results, sample counts, and missing evidence.
- The accepted change or the reason for making no change.
- Fresh confirmation still needed and the remaining budget.

Preserve rejected interventions. If a clean control prevents attributing
benefit to the guidance, retain that result rather than proposing the same
untested improvement again. Predicted results are not observations.
Keep approved regression cases in `evals/evals.json`.
Do not present fixtures or checker unit tests as measured agent behavior.
Use `references/worked-example.md` for a complete illustrative record.

## Example: a report with the wrong shape

Suppose an approved baseline task asks for a concise result and its evidence.
The agent instead restates the task and buries the result.
Capture that output before editing.

Define the required shape independently: result first, supporting evidence
next, and a next action only when the evidence requires one.
Write that recipe rather than a growing list of forbidden phrases.

If the user selects a wording experiment, compare the control and candidate
recipes in fresh contexts. Inspect actual result placement, not keyword hits.
Retest the selected wording on another kind of report.
Keep checks for factual accuracy as well as the improved shape.

This adapts the observed failure without prescribing one report's answer.

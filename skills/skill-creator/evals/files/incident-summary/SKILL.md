---
name: incident-summary
description: Use this skill to turn incident records into a factual incident summary with impact, timeline, recovery, and open questions.
---

# Incident Summary

Read incident records supplied as JSON, logs, or a written timeline.

1. Identify the incident, affected service, customer impact, and time range.
2. Order supported events by timestamp. Preserve time zones.
3. Summarize the recovery and distinguish confirmed causes from hypotheses.
4. Report unknown facts and contradictory records explicitly.
5. If JSON is malformed, explain the parse problem and ask for corrected
   data. Do not invent a timeline or silently discard broken records.

Use the headings Summary, Impact, Timeline, Recovery, and Open Questions.
Do not include credentials or personal customer information in the summary.

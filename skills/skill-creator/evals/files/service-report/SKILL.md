---
name: service-report
description: Use this skill to create or check a machine-readable incident report from supplied service records.
---

# Service report

Read the supplied incident record.
Do not add introductory prose or omit the incident identifier, count, or evidence.
Do not guess facts that the record does not support.
Return one JSON object with `incident_id`, `affected_users`, and `evidence`.
If a required fact is missing or contradictory, explain the gap and ask for clarification.

## Review

Compare each report with the supplied record.
Identify unsupported affected-user counts and missing source evidence.
Report the field, the reported value, and the supported value.

# Service report brief

This is an illustrative task fixture, not a captured production incident.
Create a portable skill that writes and checks a machine-readable service report.
Use only the supplied incident facts.

Return one JSON object with `incident_id`, `affected_users`, and `evidence`.
The count must be an integer. Use a nonempty list of supplied source identifiers.
The list can repeat a supported identifier. Do not cite unsupported sources.
Correct facts and supported evidence are mandatory. Readability is a preference.
If a required fact is missing or contradictory, explain the gap and ask for clarification.

The review step must identify unsupported counts and missing evidence.
Do not publish the skill or open a browser without a selected action.

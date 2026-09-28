"""Summarize the full synthetic diff against the authoritative rate schedule."""

import csv
import json
import re
from pathlib import Path


FILES = Path(__file__).parent / "files"
DIFF = FILES / "large-pr.diff"
SCHEDULE = FILES / "approved-rates.csv"
RATE_LINE = re.compile(r"^\+\s+'(ZONE-\d{5})': (\d+),$")


def main():
    diff = DIFF.read_text(encoding="utf-8").splitlines()
    with SCHEDULE.open(encoding="utf-8", newline="") as stream:
        approved = {
            row["zone_id"]: int(row["rate"]) for row in csv.DictReader(stream)
        }

    actual = {}
    for line in diff:
        if match := RATE_LINE.match(line):
            assert match[1] not in actual, f"Duplicate zone: {match[1]}"
            actual[match[1]] = int(match[2])

    changed_files = sum(line.startswith("diff --git ") for line in diff)
    added_lines = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
    discrepancies = [
        {"zone_id": zone, "approved": rate, "actual": actual.get(zone)}
        for zone, rate in approved.items()
        if actual.get(zone) != rate
    ]
    assert set(actual) == set(approved), "Zone IDs differ from the approved schedule"
    assert changed_files == 22 and added_lines == 16105 and len(actual) == 16000
    assert len(discrepancies) == 3
    print(json.dumps({
        "changed_files": changed_files,
        "added_lines": added_lines,
        "validated_rates": len(actual),
        "discrepancies": discrepancies,
    }, indent=2))


if __name__ == "__main__":
    main()

"""Verify the committed eval-6 fixture against the authoritative rate schedule."""

import csv
import json
import re
import sys
from pathlib import Path


FILES = Path(__file__).parent / "files"
DIFF = FILES / "large-pr.diff"
SCHEDULE = FILES / "approved-rates.csv"
RATE_LINE = re.compile(r"^\+\s+'(ZONE-\d{5})': (\d+),$")


def check(condition, message):
    if not condition:
        sys.exit(f"Fixture check failed: {message}")


def main():
    for path in (DIFF, SCHEDULE):
        check(path.is_file(), f"{path} is missing; run generate_large_fixture.py")
        check(b"\r" not in path.read_bytes(), f"{path.name} must use LF line endings")

    diff = DIFF.read_text(encoding="utf-8").splitlines()
    with SCHEDULE.open(encoding="utf-8", newline="") as stream:
        approved = {
            row["zone_id"]: int(row["rate"]) for row in csv.DictReader(stream)
        }

    actual = {}
    for line in diff:
        if match := RATE_LINE.match(line):
            check(match[1] not in actual, f"duplicate zone {match[1]}")
            actual[match[1]] = int(match[2])

    changed_files = sum(line.startswith("diff --git ") for line in diff)
    added_lines = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
    discrepancies = [
        {"zone_id": zone, "approved": rate, "actual": actual.get(zone)}
        for zone, rate in approved.items()
        if actual.get(zone) != rate
    ]
    check(set(actual) == set(approved), "zone IDs differ from the approved schedule")
    check(changed_files == 22, f"expected 22 changed files, got {changed_files}")
    check(added_lines == 16105, f"expected 16105 added lines, got {added_lines}")
    check(len(actual) == 16000, f"expected 16000 rates, got {len(actual)}")
    check(len(discrepancies) == 3, f"expected 3 discrepancies, got {len(discrepancies)}")
    print(json.dumps({
        "changed_files": changed_files,
        "added_lines": added_lines,
        "validated_rates": len(actual),
        "discrepancies": discrepancies,
    }, indent=2))


if __name__ == "__main__":
    main()

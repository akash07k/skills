"""Generate a reproducible 16,000-row, multi-file code-review fixture."""

import csv
from pathlib import Path


FILES = 20
ROWS_PER_FILE = 800
CORRUPTED_ROWS = {37: 19, 8324: -9, 15999: 27}
OUTPUT = Path(__file__).parent / "files"


def approved_rate(index):
    return 1000 + (index * 37) % 997


def added_file(path, lines):
    return [
        f"diff --git a/{path} b/{path}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{path}",
        f"@@ -0,0 +1,{len(lines)} @@",
        *(f"+{line}" for line in lines),
    ]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT / "approved-rates.csv"
    diff_path = OUTPUT / "large-pr.diff"

    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("zone_id", "rate"))
        for index in range(FILES * ROWS_PER_FILE):
            writer.writerow((f"ZONE-{index:05}", approved_rate(index)))

    diff = []
    for file_index in range(FILES):
        rows = [f"export const RATES_{file_index:02}: Record<string, number> = {{"]
        for offset in range(ROWS_PER_FILE):
            index = file_index * ROWS_PER_FILE + offset
            rate = approved_rate(index) + CORRUPTED_ROWS.get(index, 0)
            rows.append(f"  'ZONE-{index:05}': {rate},")
        rows.append("};")
        diff.extend(added_file(f"src/zones/zone-{file_index:02}.ts", rows))

    lookup = [
        *(f"import {{ RATES_{index:02} }} from './zone-{index:02}';" for index in range(FILES)),
        "",
        "const tables = [",
        *(f"  RATES_{index:02}," for index in range(FILES)),
        "];",
        "",
        "export interface RateSource { get(zoneId: string): number; }",
        "",
        "export class TableRateSource implements RateSource {",
        "  get(zoneId: string): number {",
        "    const rates: Record<string, number> = Object.assign({}, ...tables);",
        "    return rates[zoneId] ?? 0;",
        "  }",
        "}",
        "",
        "export function lookupRate(zoneId: string): number {",
        "  return new TableRateSource().get(zoneId);",
        "}",
    ]
    diff.extend(added_file("src/zones/lookup.ts", lookup))

    tests = [
        "import { lookupRate } from '../src/zones/lookup';",
        "",
        "test('quotes the first zone', () => {",
        f"  expect(lookupRate('ZONE-00000')).toBe({approved_rate(0)});",
        "});",
        "",
        "test('quotes a zone in the second table', () => {",
        f"  expect(lookupRate('ZONE-00800')).toBe({approved_rate(800)});",
        "});",
    ]
    diff.extend(added_file("tests/zones.test.ts", tests))

    diff_path.write_text("\n".join(diff) + "\n", encoding="utf-8")
    additions = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
    assert additions >= 15_000
    print(f"{additions} added lines across {FILES + 2} changed files")
    print(f"Source schedule: {csv_path}")
    print(f"PR diff: {diff_path}")


if __name__ == "__main__":
    main()

# Warehouse reconciliation checklist

The warehouse team compares recorded stock with a physical count.
The input is a CSV file with `sku`, `recorded_units`, and `counted_units`.

1. Read each item without changing the source file.
2. Calculate `difference` as `counted_units - recorded_units`.
3. Flag every nonzero difference for review.
4. If a count is missing or invalid, report the row and do not invent a value.
5. Sort the results by SKU.
6. Report the item count, the number of discrepancies, and unresolved rows.

The output is a reconciliation table and a short summary.
Do not make inventory adjustments from the report.

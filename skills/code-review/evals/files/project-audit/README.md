# Customer directory

This small ESM library exposes `lookupCustomer` and `uniqueIds`.
`lookupCustomer` normalizes a raw customer ID, rejects a blank ID, and returns
`null` for a nonblank ID that is not found. `uniqueIds` normalizes IDs and
returns each ID once in first-seen order.

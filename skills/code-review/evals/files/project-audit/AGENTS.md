# Customer directory conventions

- Normalize external customer IDs with `src/ids.js`'s `normalizeId`. It rejects blank IDs after trimming.
- Do not introduce a parallel normalizer class for the same identifier.
- Use the built-in `Set` for uniqueness instead of repeated linear searches.
- Test public behavior in `test/*.test.js` using the existing `npm test` script.

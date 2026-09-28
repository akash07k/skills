export function normalizeId(raw) {
  const id = raw.trim().toLowerCase();
  if (!id) throw new TypeError('Customer ID is required');
  return id;
}

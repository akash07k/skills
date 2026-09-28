import { normalizeId } from './ids.js';

export function uniqueIds(rawIds) {
  const normalized = rawIds.map(normalizeId);
  return normalized.filter((id, index) => normalized.indexOf(id) === index);
}

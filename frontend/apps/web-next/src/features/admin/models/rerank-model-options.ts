/**
 * Bounds of a rerank model's candidate settings. Mirror the backend's
 * CANDIDATE_FACTOR_RANGE / MAX_CANDIDATES_RANGE and their database checks.
 */
export const RERANK_CANDIDATE_FACTOR = { min: 1, max: 20 } as const;
export const RERANK_MAX_CANDIDATES = { min: 1, max: 1000 } as const;

/** A whole number within the bounds, as typed in a number field. */
export function isCandidateSetting(value: string, bounds: { min: number; max: number }): boolean {
  if (!/^\d+$/.test(value.trim())) return false;
  const n = Number(value);
  return n >= bounds.min && n <= bounds.max;
}

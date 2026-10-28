/** The backend's MAX_RETENTION_DAYS (backend/src/eneo/data_retention/constants.py). */
export const RETENTION_MAX_DAYS = 2555;

/**
 * Parses a conversation retention field: empty inherits the policy above
 * (`null`), whole days within 1-{@link RETENTION_MAX_DAYS} are that number, and
 * anything else is invalid (`undefined`).
 */
export function parseRetentionDays(value: string): number | null | undefined {
  if (value === "") return null;
  if (!/^\d+$/.test(value)) return undefined;
  const days = Number(value);
  return days >= 1 && days <= RETENTION_MAX_DAYS ? days : undefined;
}

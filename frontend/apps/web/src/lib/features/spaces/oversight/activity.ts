import type { SpaceActivityBucket } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/**
 * Higher is more recent. The API only reports a bucket, never a timestamp, so
 * sorting by activity sorts by this rank.
 */
export const ACTIVITY_RANK = {
  none: 0,
  older: 1,
  past_quarter: 2,
  past_month: 3,
  past_week: 4
} as const satisfies Record<SpaceActivityBucket, number>;

/** When a space was last used, as the UI words its activity bucket. */
export function activityLabel(bucket: SpaceActivityBucket): string {
  switch (bucket) {
    case "past_week":
      return m.admin_spaces_activity_past_week();
    case "past_month":
      return m.admin_spaces_activity_past_month();
    case "past_quarter":
      return m.admin_spaces_activity_past_quarter();
    case "older":
      return m.admin_spaces_activity_older();
    case "none":
      return m.admin_spaces_activity_none();
    default:
      return bucket satisfies never;
  }
}

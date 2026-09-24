import type { WidgetStatus } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/** The widget lifecycle status as the UI names it. */
export function widgetStatusLabel(status: WidgetStatus): string {
  switch (status) {
    case "draft":
      return m.widget_admin_status_draft();
    case "active":
      return m.widget_admin_status_active();
    case "paused":
      return m.widget_admin_status_paused();
    case "archived":
      return m.widget_admin_status_archived();
    default:
      return status satisfies never;
  }
}

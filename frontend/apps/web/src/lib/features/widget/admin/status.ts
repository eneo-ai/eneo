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

/**
 * Where a widget's activation request stands. Only a draft or paused widget
 * can be requested; the request and a send-back are never both current,
 * since a new request clears the send-back.
 */
export type ActivationRequestState =
  | { kind: "not_applicable" }
  | { kind: "none" }
  | { kind: "requested"; at: string }
  | { kind: "returned"; at: string };

export function activationRequestState(widget: {
  status: WidgetStatus;
  activation_requested_at?: string | null;
  activation_declined_at?: string | null;
}): ActivationRequestState {
  if (widget.status !== "draft" && widget.status !== "paused") return { kind: "not_applicable" };
  if (widget.activation_requested_at) {
    return { kind: "requested", at: widget.activation_requested_at };
  }
  if (widget.activation_declined_at) return { kind: "returned", at: widget.activation_declined_at };
  return { kind: "none" };
}

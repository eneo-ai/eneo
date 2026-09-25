import type { components } from "@eneo/eneo-js";

type ActionType = components["schemas"]["ActionType"];

/**
 * The actions the API always logs, whatever the audit configuration: the
 * backend's `MANDATORY_AUDIT_ACTIONS`. always-logged-actions.test.ts keeps
 * the two sets equal.
 */
export const ALWAYS_LOGGED_ACTIONS: readonly ActionType[] = [
  "space_oversight_joined",
  "space_oversight_left",
  "space_oversight_member_added",
  "space_oversight_member_role_changed",
  "space_oversight_member_removed",
  "user_group_member_added",
  "user_group_member_removed",
  "widget_activation_request_declined",
  "widget_activated",
  "widget_paused",
  "widget_archived"
];

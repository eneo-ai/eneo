import * as m from "$lib/paraglide/messages";
import type { components } from "@intric/intric-js";

type ActionType = components["schemas"]["ActionType"];
type LocaleString = string;
type MessageFn = (inputs?: Record<string, never>, options?: { locale?: string }) => LocaleString;

const ACTION_KEY_PREFIX = "audit_action_";

// "audit_action_type" is the column header "Action Type", not an action label.
const NON_ACTION_KEYS = new Set(["audit_action_type"]);

const messages = m as unknown as Record<string, MessageFn>;

const actionLabelFns: Map<ActionType, MessageFn> = new Map(
  Object.keys(messages)
    .filter((key) => key.startsWith(ACTION_KEY_PREFIX) && !NON_ACTION_KEYS.has(key))
    .map((key) => [key.slice(ACTION_KEY_PREFIX.length) as ActionType, messages[key]])
);

export function getActionLabel(action: ActionType | "all"): string {
  if (action === "all") return m.audit_all_actions();
  return actionLabelFns.get(action)?.() ?? action;
}

export function getActionOptions(): Array<{ value: ActionType | "all"; label: string }> {
  const options = Array.from(actionLabelFns, ([value, fn]) => ({ value, label: fn() }));
  options.sort((a, b) => a.label.localeCompare(b.label));
  return [{ value: "all", label: m.audit_all_actions() }, ...options];
}

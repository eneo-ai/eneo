import * as m from "$lib/paraglide/messages";
import type { components } from "@eneo/eneo-js";

type ActionType = components["schemas"]["ActionType"];
type MessageFn = () => string;

const MESSAGE_CATALOG: Record<string, MessageFn | undefined> = {};

for (const [key, value] of Object.entries(m)) {
  if (typeof value === "function") {
    MESSAGE_CATALOG[key] = value as MessageFn;
  }
}

function getMessage(key: string): MessageFn | undefined {
  const message = MESSAGE_CATALOG[key];
  return typeof message === "function" ? message : undefined;
}

function actionLabelKey(action: ActionType): string {
  return `audit_action_${action}`;
}

function actionDescriptionKey(action: ActionType): string {
  return `audit_action_${action}_description`;
}

function isActionLabelMessageKey(key: string): boolean {
  return (
    key.startsWith("audit_action_") && !key.endsWith("_description") && key !== "audit_action_type"
  );
}

export function getActionLabel(action: ActionType | "all"): string {
  if (action === "all") return m.audit_all_actions();
  return getMessage(actionLabelKey(action))?.() ?? action;
}

export function getActionDescription(action: ActionType): string {
  return getMessage(actionDescriptionKey(action))?.() ?? "";
}

export function getActionOptions(): Array<{ value: ActionType | "all"; label: string }> {
  const seen = new Set<string>();
  const options = Object.keys(MESSAGE_CATALOG)
    .filter(isActionLabelMessageKey)
    .map((key) => key.replace("audit_action_", ""))
    .filter((value) => {
      if (seen.has(value)) return false;
      seen.add(value);
      return true;
    })
    .map((value) => ({
      value: value as ActionType,
      label: getActionLabel(value as ActionType)
    }));

  options.sort((a, b) => a.label.localeCompare(b.label));
  return [{ value: "all", label: m.audit_all_actions() }, ...options];
}

import type { FlowRunContractTemplateReadiness } from "@eneo/eneo-js";
import { getFlowRuntimeErrorMessageByCode } from "$lib/features/flows/flowRuntimeErrorMapping";
import type { FlowRunDialogLabels } from "./flowRunDialogLabels";

export function getTemplateStatusLabel(
  status: string | null | undefined,
  labels: FlowRunDialogLabels
): string {
  switch (status) {
    case "ready":
      return labels.templateReady;
    case "needs_action":
      return labels.templateNeedsAction;
    case "read_only":
      return labels.templateReadOnly;
    default:
      return labels.templateUnavailable;
  }
}

export function getTemplateStatusClasses(status: string | null | undefined): string {
  switch (status) {
    case "ready":
      return "border-positive-default/30 bg-positive-default/10 text-positive-stronger";
    case "read_only":
      return "border-accent-default/30 bg-accent-dimmer text-accent-stronger";
    case "needs_action":
      return "border-warning-default/30 bg-warning-dimmer text-warning-stronger";
    default:
      return "border-negative-default/30 bg-negative-dimmer text-negative-stronger";
  }
}

export function getTemplateReadinessMessage(
  item: FlowRunContractTemplateReadiness,
  labels: FlowRunDialogLabels
): string | null {
  return (
    getFlowRuntimeErrorMessageByCode(item.message_code) ??
    (item.status === "read_only"
      ? labels.templateReadOnlyMessage
      : item.status === "ready"
        ? null
        : labels.templateNeedsActionMessage)
  );
}

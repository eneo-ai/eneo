import { m } from "$lib/paraglide/messages";

export type FlowRunStatusTranslations = {
  completed: () => string;
  failed: () => string;
  queued: () => string;
  running: () => string;
  awaiting_review: () => string;
  cancelled: () => string;
  /** A status this version of the screen does not know; never the raw value. */
  unknown: () => string;
};

export function getFlowRunStatusLabel(
  status: string,
  translations: FlowRunStatusTranslations
): string {
  if (status === "pending") {
    return translations.queued();
  }

  const label = translations[status as keyof FlowRunStatusTranslations];
  return label ? label() : translations.unknown();
}

/** The one set of status words every run view uses. */
export const flowRunStatusTranslations: FlowRunStatusTranslations = {
  completed: m.flow_run_status_completed,
  failed: m.flow_run_status_failed,
  queued: m.flow_run_status_queued,
  running: m.flow_run_status_running,
  awaiting_review: m.flow_run_status_awaiting_review,
  cancelled: m.flow_run_status_cancelled,
  unknown: m.flow_run_status_unknown
};

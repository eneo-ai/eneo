export type FlowRunStatusTranslations = {
  completed: () => string;
  failed: () => string;
  queued: () => string;
  running: () => string;
  cancelled: () => string;
};

export function getFlowRunStatusLabel(
  status: string,
  translations: FlowRunStatusTranslations,
): string {
  if (status === "pending") {
    return translations.queued();
  }

  const label = translations[status as keyof FlowRunStatusTranslations];
  return label ? label() : status;
}

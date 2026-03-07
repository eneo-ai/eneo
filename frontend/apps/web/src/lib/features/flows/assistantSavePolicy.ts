const IMMEDIATE_ASSISTANT_SAVE_FIELDS = new Set([
  "completion_model",
  "completion_model_kwargs",
]);

export function shouldSaveAssistantImmediately(
  changes: Record<string, unknown>,
): boolean {
  return Object.keys(changes).some((field) => IMMEDIATE_ASSISTANT_SAVE_FIELDS.has(field));
}

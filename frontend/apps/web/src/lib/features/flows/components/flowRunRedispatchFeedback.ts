export type RedispatchFeedback = "success" | "info";

export function getRedispatchToastKind(
  redispatchedCount: number | null | undefined
): RedispatchFeedback {
  return (redispatchedCount ?? 0) > 0 ? "success" : "info";
}

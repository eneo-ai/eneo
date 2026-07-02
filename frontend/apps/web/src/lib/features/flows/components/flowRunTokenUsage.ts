import type { FlowRunTokenUsage } from "@eneo/eneo-js";

export type FlowRunTokenUsagePayload = FlowRunTokenUsage;

export interface FlowRunTokenUsageView {
  total: number;
  input: number;
  output: number;
}

export function buildFlowRunTokenUsageView(
  tokenUsage: FlowRunTokenUsagePayload | null | undefined
): FlowRunTokenUsageView | null {
  if (!tokenUsage) {
    return null;
  }

  const total = positiveInteger(tokenUsage.num_tokens_total);
  if (total <= 0) {
    return null;
  }

  return {
    total,
    input: positiveInteger(tokenUsage.num_tokens_input),
    output: positiveInteger(tokenUsage.num_tokens_output)
  };
}

export function formatFlowRunTokenCount(
  value: number,
  locale: string,
  options: { compact?: boolean } = {}
): string {
  const formatter = new Intl.NumberFormat(locale, {
    notation: options.compact ? "compact" : "standard",
    maximumFractionDigits: options.compact && value >= 1000 ? 1 : 0
  });
  return formatter.format(value);
}

function positiveInteger(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
}

import type { FlowRunTokenUsage } from "@eneo/eneo-js";

export type FlowRunTokenUsagePayload = FlowRunTokenUsage;

export interface FlowRunTokenUsageRecordedView {
  kind: "recorded";
  total: number;
  input: number;
  output: number;
  incomplete: boolean;
  inputIncomplete: boolean;
  outputIncomplete: boolean;
}

export type FlowRunTokenUsageView = FlowRunTokenUsageRecordedView | { kind: "not_recorded" };

export function buildFlowRunTokenUsageView(
  tokenUsage: FlowRunTokenUsagePayload | null | undefined
): FlowRunTokenUsageView {
  if (!tokenUsage) {
    return { kind: "not_recorded" };
  }

  const total = positiveInteger(tokenUsage.num_tokens_total);
  const inputIncomplete = tokenUsage.input_completeness === "incomplete";
  const outputIncomplete = tokenUsage.output_completeness === "incomplete";

  return {
    kind: "recorded",
    total,
    input: positiveInteger(tokenUsage.num_tokens_input),
    output: positiveInteger(tokenUsage.num_tokens_output),
    incomplete: inputIncomplete || outputIncomplete,
    inputIncomplete,
    outputIncomplete
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

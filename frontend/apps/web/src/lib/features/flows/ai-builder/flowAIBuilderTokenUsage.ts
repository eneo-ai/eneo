import type { AIBuilderTelemetrySummary } from "./protocol";

export interface AIBuilderTokenUsageView {
  total: number;
  prompt: number;
  completion: number;
  llmCalls: number;
  estimated: boolean;
  model: string | null;
}

export function buildAIBuilderTokenUsageView(
  telemetry: AIBuilderTelemetrySummary | null | undefined
): AIBuilderTokenUsageView | null {
  if (!telemetry || telemetry.total_tokens_total <= 0) {
    return null;
  }

  const model = telemetry.last_model?.trim();
  return {
    total: positiveInteger(telemetry.total_tokens_total),
    prompt: positiveInteger(telemetry.prompt_tokens_total),
    completion: positiveInteger(telemetry.completion_tokens_total),
    llmCalls: positiveInteger(telemetry.llm_calls_made_total),
    estimated: telemetry.token_usage_estimated || telemetry.last_token_usage_estimated === true,
    model: model && model.length > 0 ? model : null
  };
}

export function formatAIBuilderTokenCount(
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

function positiveInteger(value: number): number {
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
}

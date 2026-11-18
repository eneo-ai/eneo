/**
 * Pure formatting helpers shared between admin and user-facing model surfaces:
 * token K/M math and per-1M-token cost rendering. Ported from the Svelte app's
 * `formatModelStats` so chat, editors and admin all read costs the same way.
 */

/** "128000" → "128K", "1000000" → "1M", "1500000" → "1.5M". "–" for nullish/zero. */
export function formatTokens(tokens: number | undefined | null): string {
  if (!tokens) return "–";
  if (tokens >= 1_000_000) {
    const val = tokens / 1_000_000;
    return `${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)}M`;
  }
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
  return tokens.toString();
}

/** Backend Decimal columns surface as `string` in the OpenAPI schema. */
export type CostFieldValue = number | string | null | undefined;

function toNumber(value: CostFieldValue): number | null {
  if (value == null) return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * USD per 1M tokens with adaptive precision so $0.0000006 → "$0.60" and
 * $0.000003 → "$3.00". Returns null when no cost is on record so the caller
 * can hide the chip or render "–".
 */
export function formatCostPerMillionTokens(value: CostFieldValue): string | null {
  const n = toNumber(value);
  if (n == null) return null;
  const perMillion = n * 1_000_000;
  if (perMillion === 0) return "$0";
  if (perMillion >= 100) return `$${perMillion.toFixed(0)}`;
  if (perMillion >= 1) return `$${perMillion.toFixed(2)}`;
  return `$${perMillion.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")}`;
}

/** "$0.04" per generated image — used by image model rows; same precision as per minute. */
export function formatCostPerImage(value: CostFieldValue): string | null {
  return formatCostPerMinute(value);
}

/** "$0.006/min" — used by transcription rows. */
export function formatCostPerMinute(value: CostFieldValue): string | null {
  const n = toNumber(value);
  if (n == null) return null;
  if (n === 0) return "$0";
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}`;
}

function toUsdString(amount: number): string {
  if (amount === 0) return "$0";
  if (amount >= 100) return `$${amount.toFixed(0)}`;
  if (amount >= 1) return `$${amount.toFixed(2)}`;
  if (amount >= 0.01) return `$${amount.toFixed(3)}`;
  return `$${amount.toFixed(5).replace(/0+$/, "").replace(/\.$/, "")}`;
}

/** Absolute USD cost — used for aggregated per-model / per-user totals. */
export function formatCostUSD(amount: number | null | undefined): string {
  if (amount == null || !Number.isFinite(amount)) return "–";
  return toUsdString(amount);
}

/**
 * Apply current per-token rates to historical token counts. Returns null when
 * the model has no cost on record so the caller renders a neutral chip instead
 * of "$0" (which would be a lie).
 */
export function estimateCostFromTokens(
  inputTokens: number,
  outputTokens: number,
  rates: { input_cost_per_token?: CostFieldValue; output_cost_per_token?: CostFieldValue }
): number | null {
  const inputRate = toNumber(rates.input_cost_per_token);
  const outputRate = toNumber(rates.output_cost_per_token);
  if (inputRate == null && outputRate == null) return null;
  return inputTokens * (inputRate ?? 0) + outputTokens * (outputRate ?? 0);
}

export type DeprecationStatus =
  | { kind: "active"; date: null }
  | { kind: "retiring"; date: string }
  | { kind: "deprecated"; date: string };

const DEPRECATION_WARNING_MONTHS = 6;

/** The same day DEPRECATION_WARNING_MONTHS earlier, or that month's last day. */
function warningStartDate(deprecationDate: string): string | null {
  const date = new Date(`${deprecationDate}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime())) return null;
  const day = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - DEPRECATION_WARNING_MONTHS);
  const lastDay = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(day, lastDay));
  return date.toISOString().slice(0, 10);
}

/**
 * Deprecation status + date so callers render "retires on YYYY-MM-DD" directly.
 * A coming deprecation reads as retiring only from six months before it.
 */
export function getDeprecationStatus(
  model: { deprecation_date?: string | null },
  today: string = new Date().toISOString().slice(0, 10)
): DeprecationStatus {
  const date = model.deprecation_date ?? null;
  if (!date) return { kind: "active", date: null };
  if (date <= today) return { kind: "deprecated", date };
  const warningStart = warningStartDate(date);
  return warningStart && today >= warningStart
    ? { kind: "retiring", date }
    : { kind: "active", date: null };
}

export type ModelLifecycle =
  | { kind: "active" }
  | { kind: "retiring"; date: string }
  | { kind: "deprecated"; date: string | null };

/** Deprecation from the recorded date, or the admin's manual deprecation flag. */
export function modelLifecycle(
  model: { deprecation_date?: string | null; is_deprecated?: boolean },
  today?: string
): ModelLifecycle {
  const status = getDeprecationStatus(model, today);
  if (status.kind === "deprecated") return { kind: "deprecated", date: status.date };
  if (model.is_deprecated) return { kind: "deprecated", date: null };
  if (status.kind === "retiring") return { kind: "retiring", date: status.date };
  return { kind: "active" };
}

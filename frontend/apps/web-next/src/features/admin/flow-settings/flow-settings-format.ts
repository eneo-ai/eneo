import { EneoApiError, getErrorMessage } from "@/lib/api/errors";
import type { FieldProblem, NumberBounds } from "./flow-settings";

/** next-intl's translator, as far as these helpers use it. */
export type Translate = {
  (key: string, values?: Record<string, string | number>): string;
  has: (key: string) => boolean;
};

// The audio size states the running time it buys, at an assumed MP3 bitrate
// the copy names: a real recording's length depends on its own format.
const MP3_BYTES_PER_SECOND = 128_000 / 8;

export function formatNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

/** "45 s", "20 min" or "7 h 59 min": whole units, as the page says time. */
export function formatSeconds(seconds: number, t: Translate): string {
  if (seconds < 60) return t("flow_admin_duration_seconds", { seconds });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("flow_admin_duration_minutes", { minutes });
  return t("flow_admin_duration_hours", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
}

/** What an audio size limit holds, in speech an administrator recognises. */
export function audioRunningTime(bytes: number, t: Translate): string {
  const minutes = Math.round(bytes / MP3_BYTES_PER_SECOND / 60);
  if (minutes < 60) return t("flow_admin_audio_minutes", { minutes });
  return t("flow_admin_audio_hours", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
}

/** A field's problem as a sentence that says how to fix it, in the units the field shows. */
export function problemMessage(
  problem: FieldProblem,
  bounds: NumberBounds,
  t: Translate,
  locale: string
): string {
  const shown = (value: number) => formatNumber(value / bounds.scale, locale);
  switch (problem.kind) {
    case "required":
      return t("flow_admin_problem_required");
    case "integer":
      return t("flow_admin_problem_integer");
    case "range":
      return t("flow_admin_problem_range", { min: shown(problem.min), max: shown(problem.max) });
    case "min":
      return t("flow_admin_problem_min", { min: shown(problem.min) });
    case "no_capacity":
      return t("flow_admin_max_runs_no_capacity");
    case "timeout_order":
      return t("flow_admin_timeout_order");
  }
}

/**
 * A refused save as a sentence: the flow error catalog's wording for the
 * refusal's code when it has one, else the shared error message.
 */
export function refusalMessage(error: unknown, t: Translate): string {
  if (error instanceof EneoApiError && error.reason) {
    const key = `flow_error_${error.reason}`;
    if (t.has(key)) return t(key);
  }
  return getErrorMessage(error, t);
}

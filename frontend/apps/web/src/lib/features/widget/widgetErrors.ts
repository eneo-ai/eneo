import { EneoError } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/** The backend's error code for a failed widget request, or null. */
export function widgetErrorCode(error: unknown): string | null {
  if (!(error instanceof EneoError)) return null;
  const detail = (error.response as { detail?: { code?: string } } | undefined)?.detail;
  return typeof detail?.code === "string" ? detail.code : null;
}

/** Seconds from a 429's Retry-After header, or null when it carries none. */
export function retryAfterSeconds(error: unknown): number | null {
  if (!(error instanceof EneoError) || error.status !== 429) return null;
  const raw = error.headers?.get("retry-after");
  const seconds = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/** A conversation the visitor cannot see: gone, or never theirs. */
export function isSessionError(error: unknown): boolean {
  return widgetErrorCode(error) === "session_not_owned";
}

/** Longest wait the composer is willing to sit out before asking again. */
export const MAX_COOLDOWN_SECONDS = 600;

/** What the visitor is told when a request fails. Never the raw message. */
export function describeWidgetError(error: unknown): string {
  const wait = retryAfterSeconds(error);
  switch (widgetErrorCode(error)) {
    case "rate_limited_visitor":
    case "rate_limited_ip":
    case "rate_limited_mint":
    case "rate_limited_challenge":
      return wait !== null && wait <= MAX_COOLDOWN_SECONDS
        ? m.widget_error_rate_limited_wait({ seconds: String(wait) })
        : m.widget_error_rate_limited();
    case "budget_exhausted":
      return m.widget_error_budget();
    case "widget_not_active":
    case "rate_limit_unavailable":
      return m.widget_error_unavailable();
    case "challenge_invalid":
    case "challenge_expired":
    case "challenge_replayed":
    case "challenge_required":
      return m.widget_error_verification();
    default:
      return m.widget_error_generic();
  }
}

import { EneoError } from "@eneo/eneo-js";

/**
 * Turn anything thrown during a request into the shape the error page reads.
 *
 * Both `handleError` hooks report this same contract — only the logging around
 * it differs — so the mapping lives here instead of drifting between them.
 *
 * Nothing in here may throw: it runs while an error is already being reported,
 * and a failure would replace that error with a confusing one of its own.
 *
 * The message stays as the backend phrased it. Localization happens on the
 * error page via {@link getErrorCodeMessage}, where the request locale is known.
 */
export function toAppError(
  error: unknown,
  fallback: { status: number; message: string }
): App.Error {
  if (error instanceof EneoError) {
    return {
      status: error.status,
      message: error.getReadableMessage(),
      code: error.code,
      traceId: error.getTraceId()
    };
  }

  return { status: fallback.status, message: fallback.message, code: 0 };
}

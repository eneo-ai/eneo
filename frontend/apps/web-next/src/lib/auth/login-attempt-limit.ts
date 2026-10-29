/**
 * The attempt limit's standing after a refused password login, when the
 * backend reported it (it counts failed attempts per account). `null` when
 * the response did not say.
 */
export interface LoginAttemptLimit {
  /** Failed attempts left before the account is blocked for a while. */
  attemptsRemaining: number | null;
  /** How long the account stays blocked, in seconds. */
  retryAfterSeconds: number | null;
}

function readNonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/** The limit fields the backend puts at the top of a 401 or 429 body. */
export async function readAttemptLimit(response: Response): Promise<LoginAttemptLimit> {
  try {
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null) {
      return { attemptsRemaining: null, retryAfterSeconds: null };
    }
    const fields = body as Record<string, unknown>;
    return {
      attemptsRemaining: readNonNegativeInteger(fields.attempts_remaining),
      retryAfterSeconds: readNonNegativeInteger(fields.retry_after_seconds)
    };
  } catch {
    return { attemptsRemaining: null, retryAfterSeconds: null };
  }
}

// Automatic retries of a recorded part whose upload failed for a reason that
// passes: the network, a timeout, a busy or failing server. A refusal (too
// large, not accepted, no slot) waits for the user instead.

import { EneoError } from "@eneo/eneo-js";

// The waits before each automatic retry; after the last the part waits for Retry.
export const RECORDED_UPLOAD_RETRY_MS = [5_000, 15_000, 30_000, 60_000, 120_000] as const;

// The dialog's own upload timeout: no progress for too long.
export class UploadTimeoutError extends Error {}

// Only failures known to pass: the upload's timeout, a failed fetch (TypeError),
// a connection error and a busy or failing server. Anything else waits for Retry.
export function isTransientUploadFailure(error: unknown): boolean {
  if (error instanceof UploadTimeoutError || error instanceof TypeError) return true;
  if (!(error instanceof EneoError)) return false;
  return (
    error.stage === "CONNECTION" ||
    error.status === 0 ||
    error.status === 408 ||
    error.status === 429 ||
    error.status >= 500
  );
}

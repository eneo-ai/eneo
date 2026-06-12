"use client";

import { toast } from "sonner";
import { EneoApiError, getErrorMessage } from "./errors";

/**
 * Standard error toast: localized message plus the trace id (when the error
 * came from the backend) so users can quote it to support and operators can
 * grep the backend logs.
 */
export function toastApiError(error: unknown, t: (key: string) => string): void {
  const traceId = error instanceof EneoApiError ? error.traceId : undefined;
  toast.error(getErrorMessage(error, t), {
    description: traceId ? `Trace ID: ${traceId}` : undefined
  });
}

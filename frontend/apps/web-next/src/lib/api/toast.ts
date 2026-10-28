"use client";

import { toast } from "@/lib/toast";
import { errorReferenceLines, getErrorMessage } from "./errors";

/**
 * Standard error toast: localized message plus the support references (error
 * id and trace id, when the error came from the backend) so users can quote
 * them to support and operators can grep the backend logs.
 */
export function toastApiError(error: unknown, t: (key: string) => string): void {
  const references = errorReferenceLines(error, t);
  toast.error(getErrorMessage(error, t), {
    description: references.length > 0 ? references.join(" · ") : undefined
  });
}

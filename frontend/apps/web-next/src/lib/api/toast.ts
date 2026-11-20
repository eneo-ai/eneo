import { toast } from "@/lib/toast";
import { errorReferenceLines, getErrorMessage } from "./errors";

type ToastAction = NonNullable<Parameters<typeof toast.error>[1]>["action"];

/**
 * Standard error toast: localized message plus the support references (error
 * id and trace id, when the error came from the backend) so users can quote
 * them to support and operators can grep the backend logs. An `action` offers
 * the way out the error names (a refused delete's "Migrera"). A `fileName`
 * names the file an upload error is about: the server's message never does.
 */
export function toastApiError(
  error: unknown,
  t: (key: string) => string,
  { action, fileName }: { action?: ToastAction; fileName?: string } = {}
): void {
  const references = errorReferenceLines(error, t);
  const message = getErrorMessage(error, t);
  toast.error(fileName ? `${fileName}: ${message}` : message, {
    description: references.length > 0 ? references.join(" · ") : undefined,
    action
  });
}

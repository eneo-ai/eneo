import { toast } from "@/lib/toast";
import { errorReferenceLines, getErrorMessage } from "./errors";

type ToastAction = NonNullable<Parameters<typeof toast.error>[1]>["action"];

/** A feature's own words for an error toast; `toastApiError` says how each is used. */
export type ApiErrorToastCopy = {
  /** What failed ("Körningen avbröts inte"): heads the toast, with the message under it. */
  title?: string;
  /** Replaces the catalog's message (`getErrorMessage`), such as a feature's refusal texts. */
  message?: string;
};

/**
 * Standard error toast: localized message plus the support references (error
 * id and trace id, when the error came from the backend) so users can quote
 * them to support and operators can grep the backend logs. A feature with
 * words of its own passes them (`copy`); the references always follow. An
 * `action` offers the way out the error names (a refused delete's "Migrera").
 * A `fileName` names the file an upload error is about: the server's message
 * never does.
 */
export function toastApiError(
  error: unknown,
  t: (key: string) => string,
  {
    title,
    message = getErrorMessage(error, t),
    action,
    fileName
  }: ApiErrorToastCopy & { action?: ToastAction; fileName?: string } = {}
): void {
  const headline = fileName ? `${fileName}: ${message}` : message;
  const details = [...(title ? [headline] : []), ...errorReferenceLines(error, t)];
  toast.error(title ?? headline, {
    description: details.length > 0 ? details.join(" · ") : undefined,
    action
  });
}

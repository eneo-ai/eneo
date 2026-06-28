import { EneoError } from "@eneo/eneo-js";
import { formatBytes } from "$lib/core/formatting/formatBytes";
import { m } from "$lib/paraglide/messages";

/**
 * Extract a human-readable reason from an upload error, without a file-name
 * prefix — callers add the file name themselves so it is never duplicated.
 * Handles structured FileTooLarge (code 9015) details from the backend, turning
 * them into a clear "what went wrong and what is allowed" message.
 *
 * @param error  The caught error
 */
export function getUploadErrorMessage(error: unknown): string {
  if (error instanceof EneoError && error.code === 9015) {
    const details = error.response?.details;
    if (details && typeof details === "object") {
      const fileSize = Number(details.file_size_bytes);
      const maxSize = Number(details.max_size_bytes);
      if (Number.isFinite(fileSize) && Number.isFinite(maxSize)) {
        return m.file_too_large_reason({
          currentSize: formatBytes(fileSize),
          maxSize: formatBytes(maxSize)
        });
      }
    }
    return error.getReadableMessage();
  }

  if (error instanceof EneoError) {
    return error.getReadableMessage();
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return m.file_upload_error();
}

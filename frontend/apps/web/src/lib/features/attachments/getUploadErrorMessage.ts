import { IntricError } from "@intric/intric-js";
import { formatBytes } from "$lib/core/formatting/formatBytes";
import { m } from "$lib/paraglide/messages";

/**
 * Extract a human-readable error message from an upload error.
 * Handles structured FileTooLarge (code 9015) details from the backend.
 *
 * @param error  The caught error
 * @param fileName  Optional file name to include in size-limit messages
 */
export function getUploadErrorMessage(error: unknown, fileName?: string): string {
  if (error instanceof IntricError && error.code === 9015) {
    const details = error.response?.details;
    if (details && typeof details === "object") {
      const fileSize = Number(details.file_size_bytes);
      const maxSize = Number(details.max_size_bytes);
      if (Number.isFinite(fileSize) && Number.isFinite(maxSize)) {
        const sizeInfo = `${formatBytes(fileSize)} / max ${formatBytes(maxSize)}`;
        return fileName ? `${fileName}: ${sizeInfo}` : sizeInfo;
      }
    }
    return error.getReadableMessage();
  }

  if (error instanceof IntricError) {
    return error.getReadableMessage();
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return m.file_upload_error();
}

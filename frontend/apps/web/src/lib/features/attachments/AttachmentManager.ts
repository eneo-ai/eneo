import { derived, get, readable, writable, type Readable } from "svelte/store";
import { type Eneo, type UploadedFile } from "@eneo/eneo-js";
import { createContext } from "$lib/core/context";
import { ATTACHMENTS } from "$lib/core/constants";
import { formatBytes } from "$lib/core/formatting/formatBytes";
import { getUploadErrorMessage } from "$lib/features/attachments/getUploadErrorMessage";
import { toast } from "$lib/components/toast";
import { m } from "$lib/paraglide/messages";

export type Attachment = {
  id: string;
  file: File;
  status: "queued" | "uploading" | "completed";
  progress: number;
  fileRef?: UploadedFile;
  /** The file was already in the conversation and is attached again without an upload. */
  reused?: boolean;
  /** Remove/Cancel this upload; if `Attachment.status` is
   * - `queued`: will remove it from the queue
   * - `uploading`: will cancel the upload
   * - `completed`: will try to delete the file on the server
   */
  remove: () => void;
};

export type AcceptedFormat = {
  mimetype: string;
  maxSize: number;
  /** Lowercase extensions including the leading dot, e.g. `[".pdf"]`. */
  extensions: string[];
};

export type AttachmentRules = {
  maxTotalCount?: number;
  maxTotalSize?: number;
  acceptString?: string;
  acceptedFormats?: AcceptedFormat[];
};

/**
 * Thrown by `awaitUploads` when the awaited attachments will never all be
 * ready: one of them failed (the manager has already reported that through
 * `uploadError`) or the caller gave up before they finished.
 */
export class UploadsNotReadyError extends Error {
  reason: "failed" | "aborted";

  constructor(reason: "failed" | "aborted", message: string) {
    super(message);
    this.name = "UploadsNotReadyError";
    this.reason = reason;
  }
}

export type AttachmentValidationError = {
  kind: "max_total_count" | "unsupported_type" | "file_size" | "max_total_size" | "duplicate";
  message: string;
  fileName?: string;
  fileSizeBytes?: number;
  maxSizeBytes?: number;
};

/** Whether two picked files are the same file: same name, size, type and modification time. */
function isSameFile(a: File, b: File): boolean {
  return (
    a.name === b.name && a.size === b.size && a.type === b.type && a.lastModified === b.lastModified
  );
}

/**
 * Whether a picked file is a file already uploaded: same name and type, and
 * the same number of bytes as the stored original. A document's `size` counts
 * its extracted text, so it only stands in where no original size is known.
 */
export function matchesUpload(file: File, uploaded: UploadedFile): boolean {
  const mimetype = file.type.split(";")[0];
  const bytes = uploaded.original_size ?? uploaded.size;
  return uploaded.name === file.name && uploaded.mimetype === mimetype && bytes === file.size;
}

export function unsupportedTypeError(file: File): AttachmentValidationError {
  // Some files have a codec in the type, separated by a `;`
  const mimetype = file.type.split(";")[0];
  return {
    kind: "unsupported_type",
    fileName: file.name,
    message: m.attachment_error_unsupported_type({
      fileName: file.name,
      fileType: mimetype || m.unknown()
    })
  };
}

const [getAttachmentManager, setAttachmentManager] =
  createContext<ReturnType<typeof createAttachmentManager>>();

type AttachmentManagerParams = {
  eneo: Eneo;
  options?: {
    /**  */
    rules?: AttachmentRules | Readable<AttachmentRules>;
    /** Callback to run once a file has been uploaded to eneo */
    onFileUploaded?: (file: UploadedFile) => void;
    /** When true, upload/validation errors are exposed via the `uploadError`
     * store for the consumer to render inline (e.g. next to the chat input)
     * instead of being shown as a toast. */
    inlineErrors?: boolean;
    /** A file already on the server that a picked file is a copy of, e.g. one
     * sent earlier in the conversation. It is attached again without an upload. */
    findExisting?: (file: File) => UploadedFile | undefined;
  };
};

function initAttachmentManager(data: AttachmentManagerParams) {
  const manager = createAttachmentManager(data);
  setAttachmentManager(manager);
  return manager;
}

export { initAttachmentManager, getAttachmentManager };

export function createAttachmentManager(data: AttachmentManagerParams) {
  const { eneo } = data;
  const inlineErrors = data.options?.inlineErrors ?? false;
  const attachmentRules = (() => {
    const rules = data.options?.rules ?? {};
    if (
      typeof rules === "object" &&
      "subscribe" in rules &&
      typeof rules.subscribe === "function"
    ) {
      return rules as Readable<AttachmentRules>;
    }
    return readable(rules as AttachmentRules);
  })();

  // Handling uploads ----------------------------------------
  const attachments = writable<Attachment[]>([]);
  // The most recent upload/validation problem, held until the user fixes the
  // input or dismisses it. Consumers that pass `inlineErrors` render this next
  // to their input instead of relying on a transient toast.
  const uploadError = writable<string | null>(null);

  const waitingUploads: string[] = [];
  const runningUploads: string[] = [];

  /** Attaches a file the server already has; removing it only drops it from the list. */
  function reuseUpload(file: File, fileRef: UploadedFile) {
    const id = crypto.randomUUID();
    const attachment: Attachment = {
      id,
      file,
      status: "completed",
      progress: 100,
      fileRef,
      reused: true,
      remove: () => {
        attachments.update(($attachments) => $attachments.filter((item) => item.id !== id));
      }
    };
    attachments.update(($attachments) => {
      $attachments.push(attachment);
      return $attachments;
    });
    data.options?.onFileUploaded?.(fileRef);
  }

  function queueUploads(files: File[]) {
    files.forEach((file) => {
      const id = crypto.randomUUID();
      const upload: Attachment = {
        id,
        file,
        status: "queued",
        progress: 0,
        remove: () => {
          const index = waitingUploads.indexOf(id);
          if (index !== -1) waitingUploads.splice(index, 1);
          attachments.update(($attachments) => $attachments.filter((item) => item.id !== id));
        }
      };
      attachments.update(($attachments) => {
        $attachments.push(upload);
        return $attachments;
      });
      waitingUploads.push(upload.id);
    });

    continueUploadQueue();
  }

  /**
   * Helper function to reduce boilerplate of having to find a specific attachment.
   * Simplifies updating of e.g. upload progress.
   */
  function updateAttachment(id: string, update: (attachment: Attachment) => Attachment) {
    attachments.update(($attachments) => {
      const idx = $attachments.findIndex((item) => item.id === id);
      if (idx > -1) {
        $attachments[idx] = update($attachments[idx]);
      }
      return $attachments;
    });
  }

  async function continueUploadQueue() {
    while (
      runningUploads.length < ATTACHMENTS.MAX_CONCURRENT_UPLOADS &&
      waitingUploads.length > 0
    ) {
      const currentUpload = waitingUploads.shift();
      if (!currentUpload) continue;
      runningUploads.push(currentUpload);

      const { file } = get(attachments).find((attachment) => attachment.id === currentUpload)!;

      try {
        const controller = new AbortController();

        updateAttachment(currentUpload, (attachment) => {
          attachment.status = "uploading";
          attachment.remove = () => {
            controller.abort("User cancelled upload");
          };
          return attachment;
        });

        const fileRef = await eneo.files.upload({
          file,
          onProgress: (ev) => {
            updateAttachment(currentUpload, (attachment) => {
              attachment.progress = Math.floor((ev.loaded / ev.total) * 100);
              return attachment;
            });
          },
          abortController: controller
        });

        data.options?.onFileUploaded?.(fileRef);

        updateAttachment(currentUpload, (attachment) => {
          attachment.fileRef = fileRef;
          attachment.status = "completed";
          attachment.remove = async () => {
            // This can fail, but that's ok
            try {
              await eneo.files.delete({ fileId: fileRef.id });
            } finally {
              // We always remove from our list, so it is not included in the question
              attachments.update(($attachments) =>
                $attachments.filter((attachment) => attachment.fileRef?.id !== fileRef.id)
              );
            }
          };
          return attachment;
        });
      } catch (error) {
        if (error instanceof Error && error.message.includes("Cancelled")) {
          console.warn(`Cancelled upload for ${file.name}`);
        } else {
          const reason = getUploadErrorMessage(error);
          const message = m.attachment_upload_failed({ fileName: file.name, reason });
          uploadError.set(message);
          if (!inlineErrors) toast.error(message);
        }
        attachments.update(($attachments) => $attachments.filter((u) => u.id !== currentUpload));
      } finally {
        const idx = runningUploads.findIndex((id) => id === currentUpload);
        if (idx !== -1) runningUploads.splice(idx, 1);
        continueUploadQueue();
      }
    }
  }

  function clearUploads() {
    attachments.set([]);
    uploadError.set(null);
  }

  /** Drop the given attachments from the list, e.g. once they have been sent. */
  function removeUploads(ids: string[]) {
    const sent = new Set(ids);
    attachments.update(($attachments) => $attachments.filter((item) => !sent.has(item.id)));
    uploadError.set(null);
  }

  /**
   * Resolves with the uploaded files once every listed attachment has
   * completed. Rejects with `UploadsNotReadyError` when one of them leaves the
   * list first (its upload failed or it was removed) or when `signal` aborts.
   * The uploads themselves are never cancelled by this.
   */
  function awaitUploads(ids: string[], signal?: AbortSignal): Promise<UploadedFile[]> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new UploadsNotReadyError("aborted", "Cancelled before the uploads finished"));
        return;
      }

      let settled = false;
      let unsubscribe: (() => void) | undefined = undefined;
      const settle = (outcome: () => void) => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener("abort", onAbort);
        unsubscribe?.();
        outcome();
      };
      const onAbort = () =>
        settle(() =>
          reject(new UploadsNotReadyError("aborted", "Cancelled before the uploads finished"))
        );
      signal?.addEventListener("abort", onAbort, { once: true });

      unsubscribe = attachments.subscribe(($attachments) => {
        const files: UploadedFile[] = [];
        for (const id of ids) {
          const attachment = $attachments.find((item) => item.id === id);
          if (!attachment) {
            settle(() =>
              reject(new UploadsNotReadyError("failed", "An attachment did not finish uploading"))
            );
            return;
          }
          if (attachment.status !== "completed" || !attachment.fileRef) return;
          files.push(attachment.fileRef);
        }
        settle(() => resolve(files));
      });
      // The store calls back synchronously, so the subscription may already
      // have settled before it could be released above.
      if (settled) unsubscribe();
    });
  }

  function clearUploadError() {
    uploadError.set(null);
  }

  function queueValidUploadsDetailed(files: File[], rules?: AttachmentRules) {
    const errors: AttachmentValidationError[] = [];
    const selectedRules = rules ?? get(attachmentRules);

    // A fresh attempt clears any stale problem (e.g. the user retries with a
    // smaller file) before we re-evaluate this batch.
    uploadError.set(null);

    for (const file of files) {
      const $attachments = get(attachments);

      if (selectedRules.maxTotalCount && $attachments.length >= selectedRules.maxTotalCount) {
        errors.push({
          kind: "max_total_count",
          message: m.attachment_error_max_count({ count: selectedRules.maxTotalCount })
        });
        break;
      }

      // A file picked again (the same folder dropped twice, say) is already
      // on its way or in the list; it is not uploaded a second time.
      if ($attachments.some((attachment) => isSameFile(attachment.file, file))) {
        errors.push({
          kind: "duplicate",
          fileName: file.name,
          message: m.attachment_error_duplicate({ fileName: file.name })
        });
        continue;
      }

      if (selectedRules.acceptedFormats) {
        // Some files have a codec in the type, separated by a `;`
        const mimetype = file.type.split(";")[0];
        const format = selectedRules.acceptedFormats.find((format) => format.mimetype === mimetype);

        if (!format) {
          errors.push(unsupportedTypeError(file));
          continue;
        }

        if (file.size > format.maxSize) {
          errors.push({
            kind: "file_size",
            fileName: file.name,
            fileSizeBytes: file.size,
            maxSizeBytes: format.maxSize,
            message: m.file_too_large_detail({
              fileName: file.name,
              currentSize: formatBytes(file.size),
              maxSize: formatBytes(format.maxSize)
            })
          });
          continue;
        }
      }

      const currentTotalSize = $attachments.reduce((totalSize, current) => {
        return (totalSize += current.file.size);
      }, 0);
      if (
        selectedRules.maxTotalSize &&
        currentTotalSize + file.size >= selectedRules.maxTotalSize
      ) {
        errors.push({
          kind: "max_total_size",
          fileName: file.name,
          fileSizeBytes: file.size,
          maxSizeBytes: selectedRules.maxTotalSize,
          message: m.attachment_error_max_total_size({
            fileName: file.name,
            maxSize: formatBytes(selectedRules.maxTotalSize)
          })
        });
        continue;
      }

      const existing = data.options?.findExisting?.(file);
      if (existing) {
        reuseUpload(file, existing);
        continue;
      }

      queueUploads([file]);
    }

    if (errors.length > 0) {
      // Many skipped duplicates are one line, not a wall of them.
      const duplicates = errors.filter((error) => error.kind === "duplicate");
      const shown =
        duplicates.length > 1
          ? [
              ...errors.filter((error) => error.kind !== "duplicate").map((e) => e.message),
              m.attachment_error_duplicates({ count: duplicates.length })
            ]
          : errors.map((error) => error.message);
      uploadError.set(shown.join("\n"));
      return errors;
    }
    return null;
  }

  function queueValidUploads(files: File[], rules?: AttachmentRules) {
    const errors = queueValidUploadsDetailed(files, rules);
    return errors ? errors.map((error) => error.message) : null;
  }

  // Return -------------------------------------------------------
  return Object.freeze({
    state: {
      attachments: { subscribe: attachments.subscribe },
      isUploading: derived(attachments, ($attachments) =>
        $attachments.some((upload) => upload.status !== "completed")
      ),
      attachmentRules,
      /** Latest upload/validation problem (or null); rendered inline by consumers
       * that opt in via `options.inlineErrors`. */
      uploadError: { subscribe: uploadError.subscribe }
    },
    /**
     * Will test the supplied files and upload the files passing the rule set.
     * By default the AttachmentManager's ruleset will be used, if it was supplied during creation.
     * Supply your own ruleset if you want to override this behaviour.
     */
    queueValidUploads,
    queueValidUploadsDetailed,
    /** Will reset the current attachment list */
    clearUploads,
    /** Drop specific attachments from the list without deleting their files */
    removeUploads,
    /** Wait for the listed attachments to finish uploading */
    awaitUploads,
    /** Dismiss the current inline upload error */
    clearUploadError
  });
}

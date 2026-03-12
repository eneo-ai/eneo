import { derived, get, readable, writable, type Readable } from "svelte/store";
import type { Intric, UploadedFile } from "@intric/intric-js";
import { createContext } from "$lib/core/context";
import { ATTACHMENTS } from "$lib/core/constants";
import { toast } from "$lib/components/toast";

export type Attachment = {
  id: string;
  file: File;
  status: "queued" | "uploading" | "completed";
  progress: number;
  fileRef?: UploadedFile;
  /** Remove/Cancel this upload; if `Attachment.status` is
   * - `queued`: will remove it from the queue
   * - `uploading`: will cancel the upload
   * - `completed`: will try to delete the file on the server
   */
  remove: () => void;
};

export type AttachmentRules = {
  maxTotalCount?: number;
  maxTotalSize?: number;
  acceptString?: string;
  acceptedFormats?: {
    mimetype: string;
    maxSize: number;
  }[];
};

const [getAttachmentManager, setAttachmentManager] =
  createContext<ReturnType<typeof createAttachmentManager>>();

type AttachmentManagerParams = {
  intric: Intric;
  options?: {
    /**  */
    rules?: AttachmentRules | Readable<AttachmentRules>;
    /** Callback to run once a file has been uploaded to intric */
    onFileUploaded?: (file: UploadedFile) => void;
  };
};

function initAttachmentManager(data: AttachmentManagerParams) {
  const manager = createAttachmentManager(data);
  setAttachmentManager(manager);
  return manager;
}

export { initAttachmentManager, getAttachmentManager };

function createAttachmentManager(data: AttachmentManagerParams) {
  const { intric } = data;
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

  const waitingUploads: string[] = [];
  const runningUploads: string[] = [];

  function queueUploads(files: File[]) {
    files.forEach((file) => {
      const id = crypto.randomUUID();
      const upload: Attachment = {
        id,
        file,
        status: "queued",
        progress: 0,
        remove: () => {
          waitingUploads.splice(waitingUploads.findIndex((item) => item === id));
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

        const fileRef = await intric.files.upload({
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
              await intric.files.delete({ fileId: fileRef.id });
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
          console.warn(`Cancelled uppload for ${file.name}`);
        } else {
          toast.error(`We encountered an error uploading the file ${file.name}: ${error}`);
        }
        attachments.update(($attachments) => $attachments.filter((u) => u.id !== currentUpload));
      } finally {
        const idx = runningUploads.findIndex((id) => id === currentUpload);
        if (idx) runningUploads.splice(idx, 1);
        continueUploadQueue();
      }
    }
  }

  function clearUploads() {
    attachments.set([]);
  }

  function queueValidUploads(files: File[], rules?: AttachmentRules) {
    const errors: string[] = [];
    const selectedRules = rules ?? get(attachmentRules);

    for (const file of files) {
      const $attachments = get(attachments);

      if (selectedRules.maxTotalCount && $attachments.length >= selectedRules.maxTotalCount) {
        errors.push(
          `You can only attach a maximum number of ${selectedRules.maxTotalCount} files at a time.`
        );
        break;
      }

      if (selectedRules.acceptedFormats) {
        // Some files have a codec in the type, separated by a `;`
        const mimetype = file.type.split(";")[0];
        const format = selectedRules.acceptedFormats.find((format) => format.mimetype === mimetype);

        if (!format) {
          errors.push(`${file.name}: File type ${mimetype} is not supported for this operation.`);
          continue;
        }

        if (file.size > format.maxSize) {
          errors.push(
            `${file.name}: File is too large. Maximum size is ${format.maxSize} bytes while ${file.name} is ${file.size} bytes.`
          );
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
        errors.push(
          `${file.name}: Skipping file. Can only upload a total of ${selectedRules.maxTotalSize} bytes at a time.`
        );
        continue;
      }

      queueUploads([file]);
    }

    return errors.length > 0 ? errors : null;
  }

  // Return -------------------------------------------------------
  return Object.freeze({
    state: {
      attachments: { subscribe: attachments.subscribe },
      isUploading: derived(attachments, ($attachments) =>
        $attachments.some((upload) => upload.status !== "completed")
      ),
      attachmentRules
    },
    /**
     * Will test the supplied files and upload the files passing the rule set.
     * By default the AttachmentManager's ruleset will be used, if it was supplied during creation.
     * Supply your own ruleset if you want to override this behaviour.
     */
    queueValidUploads,
    /** Will reset the current attachment list */
    clearUploads
  });
}

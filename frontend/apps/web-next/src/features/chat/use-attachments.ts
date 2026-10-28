"use client";

import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { useFileUploads, type FileUpload } from "@/features/files/use-file-uploads";
export { releasePreviews } from "@/features/files/use-file-uploads";
import type { ChatPartner } from "@/lib/chat/types";
import { toast } from "@/lib/toast";
import { chatCapabilities } from "./chat-capabilities";
import {
  type ChatAttachmentRejection,
  type ChatAttachmentUploaded,
  planChatAttachmentUploads
} from "./chat-attachment-plan";

export type Attachment = FileUpload;

export type UseAttachmentsOptions = {
  /**
   * A file already on the server that a picked file is a copy of, e.g. one
   * sent earlier in the conversation. It is attached again without an upload.
   */
  findExisting?: (file: File) => ChatAttachmentUploaded | undefined;
};

function toastRejections(
  rejections: ChatAttachmentRejection<File>[],
  t: (key: string, values?: Record<string, string | number | Date>) => string
) {
  let maxFilesShown = false;
  // Many skipped duplicates are one line, not a wall of them.
  const duplicates = rejections.filter((rejection) => rejection.reason === "duplicate");
  if (duplicates.length > 1) {
    toast.info(t("attachment_error_duplicates", { count: duplicates.length }));
  }
  for (const rejection of rejections) {
    switch (rejection.reason) {
      case "unsupported-type":
        toast.error(`${rejection.file.name}: ${t("file_type_not_supported")}`);
        break;
      case "too-large":
        toast.error(`${rejection.file.name}: ${t("file_too_large")}`);
        break;
      case "max-files":
        if (!maxFilesShown) {
          toast.error(t("attachment_error_max_count", { count: rejection.limit ?? 0 }));
          maxFilesShown = true;
        }
        break;
      case "duplicate":
        if (duplicates.length === 1) {
          toast.info(t("attachment_error_duplicate", { fileName: rejection.file.name }));
        }
        break;
    }
  }
}

/**
 * Upload queue for chat attachments: validates against the tenant's limits
 * (vision formats only when the partner's model has vision), skips a file the
 * composer already holds, attaches a file the conversation already has
 * without another upload, uploads the rest through the proxy and exposes the
 * uploaded file ids for the conversation request.
 */
export function useAttachments(partner: ChatPartner, { findExisting }: UseAttachmentsOptions = {}) {
  const t = useTranslations();
  const { limits, can } = useAppContext();
  const uploads = useFileUploads({ previews: true });
  const attachments = uploads.files;

  const vision =
    (partner.completionModel?.vision ?? false) ||
    chatCapabilities(partner, can).some(
      (capability) => capability.purpose === "image_generation" && capability.available
    );
  const formats = limits.attachments.formats.filter((format) => !format.vision || vision);
  const acceptString = formats.map((format) => format.mimetype).join(",");
  const maxFiles = partner.allowedAttachments?.limit.max_files ?? Infinity;
  const canAddMore = maxFiles === Infinity || attachments.length < maxFiles;

  async function addFiles(files: File[]) {
    const plan = planChatAttachmentUploads(
      files,
      uploads.current(),
      formats,
      maxFiles,
      findExisting
    );
    toastRejections(plan.rejected, t);
    for (const { file, uploaded } of plan.reused) uploads.reuse(file, uploaded);
    await uploads.add(plan.accepted);
  }

  return {
    attachments,
    acceptString,
    canAddMore,
    addFiles,
    removeAttachment: uploads.remove,
    /** Wait for the listed attachments to finish uploading */
    awaitUploads: uploads.awaitUploads,
    detach: uploads.detach,
    restore: uploads.restore,
    maxFiles,
    uploading: attachments.some((attachment) => attachment.uploading),
    fileIds: attachments.flatMap((attachment) => (attachment.fileId ? [attachment.fileId] : []))
  };
}

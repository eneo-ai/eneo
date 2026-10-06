"use client";

import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { useFileUploads, type FileUpload } from "@/features/files/use-file-uploads";
export { releasePreviews } from "@/features/files/use-file-uploads";
import type { ChatPartner } from "@/lib/chat/types";
import { toast } from "@/lib/toast";
import { chatCapabilities } from "./chat-capabilities";
import { type ChatAttachmentRejection, planChatAttachmentUploads } from "./chat-attachment-plan";

export type Attachment = FileUpload;

function toastRejection(
  rejection: ChatAttachmentRejection<File>,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
  shown: { maxFiles: boolean }
) {
  switch (rejection.reason) {
    case "unsupported-type":
      toast.error(`${rejection.file.name}: ${t("file_type_not_supported")}`);
      break;
    case "too-large":
      toast.error(`${rejection.file.name}: ${t("file_too_large")}`);
      break;
    case "max-files":
      if (!shown.maxFiles) {
        toast.error(t("attachment_error_max_count", { count: rejection.limit ?? 0 }));
        shown.maxFiles = true;
      }
      break;
  }
}

/**
 * Upload queue for chat attachments: validates against the tenant's limits
 * (vision formats only when the partner's model has vision), uploads through
 * the proxy, exposes the uploaded file ids for the conversation request.
 */
export function useAttachments(partner: ChatPartner) {
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
    const plan = planChatAttachmentUploads(files, attachments.length, formats, maxFiles);
    const shown = { maxFiles: false };
    for (const rejection of plan.rejected) toastRejection(rejection, t, shown);

    await uploads.add(plan.accepted);
  }

  return {
    attachments,
    acceptString,
    canAddMore,
    addFiles,
    removeAttachment: uploads.remove,
    detach: uploads.detach,
    restore: uploads.restore,
    maxFiles,
    uploading: attachments.some((attachment) => attachment.uploading),
    fileIds: attachments.flatMap((attachment) => (attachment.fileId ? [attachment.fileId] : []))
  };
}

"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useAppContext } from "@/components/providers/app-context";
import { unwrap } from "@/lib/api/errors";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";
import { chatCapabilities } from "./chat-capabilities";
import { type ChatAttachmentRejection, planChatAttachmentUploads } from "./chat-attachment-plan";

export type Attachment = {
  /** Local key while uploading; backend file id once uploaded. */
  key: string;
  fileId?: string;
  name: string;
  size: number;
  mimetype: string;
  uploading: boolean;
  /** Object URL for previewing the file in the composer (revoked on removal). */
  previewUrl?: string;
};

/** Frees the composer preview URLs of attachments that have left the composer. */
export function releasePreviews(attachments: Attachment[]) {
  for (const attachment of attachments) {
    if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
  }
}

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
  const [attachments, setAttachments] = useState<Attachment[]>([]);

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

    for (const file of plan.accepted) {
      const key = crypto.randomUUID();
      const previewUrl = URL.createObjectURL(file);
      setAttachments((current) => [
        ...current,
        { key, name: file.name, size: file.size, mimetype: file.type, uploading: true, previewUrl }
      ]);

      try {
        const body = new FormData();
        body.append("upload_file", file);
        const uploaded = await unwrap(
          browserApi.POST("/api/v1/files/", {
            // The schema types multipart bodies as the parsed shape; hand the
            // serializer a FormData instance instead.
            body: body as unknown as { upload_file: string },
            bodySerializer: (formData: unknown) => formData as FormData
          })
        );
        setAttachments((current) =>
          current.map((attachment) =>
            attachment.key === key
              ? { ...attachment, fileId: uploaded.id, uploading: false }
              : attachment
          )
        );
      } catch (error) {
        toastApiError(error, t);
        setAttachments((current) => current.filter((attachment) => attachment.key !== key));
      }
    }
  }

  async function removeAttachment(key: string) {
    const attachment = attachments.find((candidate) => candidate.key === key);
    if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
    setAttachments((current) => current.filter((candidate) => candidate.key !== key));
    if (attachment?.fileId) {
      browserApi
        .DELETE("/api/v1/files/{id}/", { params: { path: { id: attachment.fileId } } })
        .catch(() => undefined);
    }
  }

  /**
   * Takes the attachments with these file ids out of the composer when their
   * question is sent. Their previews stay valid: the caller puts them back with
   * `restore` (the question failed before it was sent) or frees them with
   * `releasePreviews`.
   */
  function detach(fileIds: ReadonlySet<string>): Attachment[] {
    const taken = attachments.filter(
      (attachment) => attachment.fileId !== undefined && fileIds.has(attachment.fileId)
    );
    const keys = new Set(taken.map((attachment) => attachment.key));
    setAttachments((current) => current.filter((attachment) => !keys.has(attachment.key)));
    return taken;
  }

  /** Puts detached attachments back, before any added since. */
  function restore(taken: Attachment[]) {
    const keys = new Set(taken.map((attachment) => attachment.key));
    setAttachments((current) => [
      ...taken,
      ...current.filter((attachment) => !keys.has(attachment.key))
    ]);
  }

  return {
    attachments,
    acceptString,
    canAddMore,
    addFiles,
    removeAttachment,
    detach,
    restore,
    maxFiles,
    uploading: attachments.some((attachment) => attachment.uploading),
    fileIds: attachments.flatMap((attachment) => (attachment.fileId ? [attachment.fileId] : []))
  };
}

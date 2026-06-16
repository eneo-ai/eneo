"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useAppContext } from "@/components/providers/app-context";
import { unwrap } from "@/lib/api/errors";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";

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

/**
 * Upload queue for chat attachments: validates against the tenant's limits
 * (vision formats only when the partner's model has vision), uploads through
 * the proxy, exposes the uploaded file ids for the conversation request.
 */
export function useAttachments(partner: ChatPartner) {
  const t = useTranslations();
  const { limits } = useAppContext();
  const [attachments, setAttachments] = useState<Attachment[]>([]);

  const vision = partner.completionModel?.vision ?? false;
  const formats = limits.attachments.formats.filter((format) => !format.vision || vision);
  const acceptString = formats.map((format) => format.mimetype).join(",");

  async function addFiles(files: File[]) {
    for (const file of files) {
      const format = formats.find((candidate) => candidate.mimetype === file.type);
      if (!format) {
        toast.error(`${file.name}: ${t("file_type_not_supported")}`);
        continue;
      }
      if (file.size > format.size) {
        toast.error(`${file.name}: ${t("file_too_large")}`);
        continue;
      }

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

  function clear() {
    setAttachments((current) => {
      for (const attachment of current) {
        if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      }
      return [];
    });
  }

  return {
    attachments,
    acceptString,
    addFiles,
    removeAttachment,
    clear,
    uploading: attachments.some((attachment) => attachment.uploading),
    fileIds: attachments.flatMap((attachment) => (attachment.fileId ? [attachment.fileId] : []))
  };
}

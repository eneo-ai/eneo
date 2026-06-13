"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import type { InputFieldRules } from "../apps";

export type RunFile = {
  /** Local key while uploading; backend file id once uploaded. */
  key: string;
  fileId?: string;
  name: string;
  size: number;
  mimetype: string;
  uploading: boolean;
};

async function uploadRunFile(file: File): Promise<{ id: string }> {
  const body = new FormData();
  body.append("upload_file", file);
  return unwrap(
    browserApi.POST("/api/v1/files/", {
      // The schema types multipart bodies as the parsed shape; hand the
      // serializer a FormData instance instead (same as chat attachments).
      body: body as unknown as { upload_file: string },
      bodySerializer: (formData: unknown) => formData as FormData
    })
  );
}

/**
 * Run inputs (text + uploaded files) for one app, validated against an input
 * field's rules. Files upload to /api/v1/files/ on add; the run create call
 * only references the resulting ids.
 */
export function useAppRunInputs() {
  const t = useTranslations();
  const [text, setText] = useState<string>("");
  const [files, setFiles] = useState<RunFile[]>([]);

  const addFiles = useCallback(
    async (incoming: File[], rules: InputFieldRules) => {
      const accepted = new Set(rules.perTypeLimits.map((limit) => limit.mimetype));
      for (const file of incoming) {
        if (accepted.size > 0 && !accepted.has(file.type)) {
          toast.error(`${file.name}: ${t("file_type_not_supported")}`);
          continue;
        }
        const cap =
          rules.perTypeLimits.find((limit) => limit.mimetype === file.type)?.sizeLimit ??
          rules.maxSize;
        if (Number.isFinite(cap) && file.size > cap) {
          toast.error(`${file.name}: ${t("file_too_large")} (${formatBytes(cap)})`);
          continue;
        }

        const key = crypto.randomUUID();
        setFiles((current) => [
          ...current,
          { key, name: file.name, size: file.size, mimetype: file.type, uploading: true }
        ]);
        try {
          const uploaded = await uploadRunFile(file);
          setFiles((current) =>
            current.map((entry) =>
              entry.key === key ? { ...entry, fileId: uploaded.id, uploading: false } : entry
            )
          );
        } catch (error) {
          toastApiError(error, t);
          setFiles((current) => current.filter((entry) => entry.key !== key));
        }
      }
    },
    [t]
  );

  const removeFile = useCallback((key: string) => {
    setFiles((current) => {
      const target = current.find((entry) => entry.key === key);
      if (target?.fileId) {
        browserApi
          .DELETE("/api/v1/files/{id}/", { params: { path: { id: target.fileId } } })
          .catch(() => undefined);
      }
      return current.filter((entry) => entry.key !== key);
    });
  }, []);

  const clear = useCallback(() => {
    setText("");
    setFiles([]);
  }, []);

  return {
    text,
    setText,
    files,
    addFiles,
    removeFile,
    clear,
    uploading: files.some((file) => file.uploading),
    fileIds: files.flatMap((file) => (file.fileId ? [file.fileId] : [])),
    hasInput: text.trim().length > 0 || files.length > 0
  };
}

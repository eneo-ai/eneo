"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { toastUploadRejection } from "@/features/files/upload-rejection-toast";
import { planFileUploads, type FileUploadRules } from "@/features/files/upload-plan";
import {
  useFileUploads,
  releasePreviews,
  type FileUpload
} from "@/features/files/use-file-uploads";

export type RunFile = FileUpload;

/**
 * Run inputs (text + uploaded files) for one app, validated against an input
 * field's rules. Files upload to /api/v1/files/ on add; the run create call
 * only references the resulting ids.
 */
export function useAppRunInputs() {
  const t = useTranslations();
  const locale = useLocale();
  const [text, setText] = useState<string>("");
  const uploads = useFileUploads();
  const files = uploads.files;

  async function addFiles(incoming: File[], rules: FileUploadRules) {
    const plan = planFileUploads(incoming, files, rules);
    const shown = { maxFiles: false };
    for (const rejection of plan.rejected) toastUploadRejection(rejection, t, locale, shown);
    await uploads.add(plan.accepted);
  }

  function clear() {
    setText("");
    releasePreviews(uploads.detach());
  }

  return {
    text,
    setText,
    files,
    addFiles,
    removeFile: uploads.remove,
    clear,
    detachFiles: uploads.detach,
    restoreFiles: uploads.restore,
    uploading: files.some((file) => file.uploading),
    fileIds: files.flatMap((file) => (file.fileId ? [file.fileId] : [])),
    hasInput: text.trim().length > 0 || files.length > 0
  };
}

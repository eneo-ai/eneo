"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/** A file owned by an unsent form. detach transfers ownership to its consumer. */
export type FileUpload = {
  key: string;
  fileId?: string;
  name: string;
  size: number;
  mimetype: string;
  uploading: boolean;
  previewUrl?: string;
};

export function releasePreviews(files: readonly FileUpload[]) {
  for (const file of files) {
    if (file.previewUrl) URL.revokeObjectURL(file.previewUrl);
  }
}

async function deleteUploadedFile(id: string) {
  await unwrap(browserApi.DELETE("/api/v1/files/{id}/", { params: { path: { id } } }));
}

/** Shared upload ownership for chat, app runs and template creation. */
export function useFileUploads({ previews = false } = {}) {
  const t = useTranslations();
  const [files, setFiles] = useState<FileUpload[]>([]);
  const owned = useRef<FileUpload[]>([]);
  const mounted = useRef(true);

  function replace(next: FileUpload[]) {
    owned.current = next;
    if (mounted.current) setFiles(next);
  }

  async function deleteFile(id: string) {
    try {
      await deleteUploadedFile(id);
    } catch (error) {
      toastApiError(error, t);
    }
  }

  // Pending requests finish so their returned IDs can be deleted. Aborting
  // transport alone could lose an ID after the backend has stored the file.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const abandoned = owned.current;
      owned.current = [];
      releasePreviews(abandoned);
      for (const file of abandoned) {
        if (file.fileId)
          void deleteUploadedFile(file.fileId).catch(() => {
            console.error("Could not delete an abandoned temporary upload");
          });
      }
    };
  }, []);

  async function add(accepted: File[]) {
    if (!mounted.current) return;
    const queued = accepted.map((file) => ({
      file,
      entry: {
        key: crypto.randomUUID(),
        name: file.name,
        size: file.size,
        mimetype: file.type,
        uploading: true,
        ...(previews ? { previewUrl: URL.createObjectURL(file) } : {})
      } satisfies FileUpload
    }));
    replace([...owned.current, ...queued.map(({ entry }) => entry)]);
    for (const { file, entry } of queued) {
      if (!owned.current.some((current) => current.key === entry.key)) continue;
      try {
        const body = new FormData();
        body.append("upload_file", file);
        const uploaded = await unwrap(
          browserApi.POST("/api/v1/files/", {
            body: body as unknown as { upload_file: string },
            bodySerializer: (formData: unknown) => formData as FormData
          })
        );
        if (!owned.current.some((current) => current.key === entry.key)) {
          await deleteFile(uploaded.id);
          continue;
        }
        replace(
          owned.current.map((current) =>
            current.key === entry.key
              ? { ...current, fileId: uploaded.id, uploading: false }
              : current
          )
        );
      } catch (error) {
        if (!owned.current.some((current) => current.key === entry.key)) continue;
        releasePreviews([entry]);
        replace(owned.current.filter((current) => current.key !== entry.key));
        toastApiError(error, t);
      }
    }
  }

  function remove(key: string) {
    const removed = owned.current.filter((file) => file.key === key);
    replace(owned.current.filter((file) => file.key !== key));
    releasePreviews(removed);
    for (const file of removed) {
      if (file.fileId) void deleteFile(file.fileId);
    }
  }

  function discard() {
    for (const file of [...owned.current]) remove(file.key);
  }

  /** Retain uploaded files on the server; the caller now owns their previews. */
  function detach(fileIds?: ReadonlySet<string>): FileUpload[] {
    const taken = owned.current.filter(
      (file) => !fileIds || (file.fileId && fileIds.has(file.fileId))
    );
    const keys = new Set(taken.map((file) => file.key));
    replace(owned.current.filter((file) => !keys.has(file.key)));
    return taken;
  }

  function restore(taken: FileUpload[]) {
    if (!mounted.current) {
      releasePreviews(taken);
      for (const file of taken) if (file.fileId) void deleteFile(file.fileId);
      return;
    }
    const keys = new Set(taken.map((file) => file.key));
    replace([...taken, ...owned.current.filter((file) => !keys.has(file.key))]);
  }

  return { files, add, remove, discard, detach, restore };
}

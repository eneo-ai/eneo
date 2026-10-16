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
  /** When the picked file was last changed; tells a re-pick of the same file apart. */
  lastModified?: number;
  uploading: boolean;
  previewUrl?: string;
  /**
   * The file was already on the server (sent earlier in the conversation) and
   * is attached again without an upload. Removing it only leaves the list;
   * the stored file stays.
   */
  reused?: boolean;
};

/** A file on the server that a picked file is attached as, instead of being uploaded again. */
export type ExistingUpload = { id: string };

/**
 * Thrown by `awaitUploads` when the awaited files will never all be ready:
 * one of them left the list (its upload failed, which has been reported, or
 * it was removed) or the caller gave up before they finished.
 */
export class UploadsNotReadyError extends Error {
  reason: "failed" | "aborted";

  constructor(reason: "failed" | "aborted") {
    super(
      reason === "failed"
        ? "An attachment did not finish uploading"
        : "Cancelled before the uploads finished"
    );
    this.name = "UploadsNotReadyError";
    this.reason = reason;
  }
}

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
  // Told of every change to the list, so a caller can wait for uploads to finish.
  const watchers = useRef(new Set<() => void>());

  function replace(next: FileUpload[]) {
    owned.current = next;
    if (mounted.current) setFiles(next);
    for (const watcher of [...watchers.current]) watcher();
  }

  async function deleteFile(id: string) {
    try {
      await deleteUploadedFile(id);
    } catch (error) {
      toastApiError(error, t);
    }
  }

  /** Lets go of a file this form owned; one it only reused stays on the server. */
  function forget(file: FileUpload) {
    if (file.fileId && !file.reused) void deleteFile(file.fileId);
  }

  // Pending requests finish so their returned IDs can be deleted. Aborting
  // transport alone could lose an ID after the backend has stored the file.
  useEffect(() => {
    mounted.current = true;
    const waiting = watchers.current;
    return () => {
      mounted.current = false;
      const abandoned = owned.current;
      owned.current = [];
      for (const watcher of [...waiting]) watcher();
      releasePreviews(abandoned);
      for (const file of abandoned) {
        if (file.fileId && !file.reused)
          void deleteUploadedFile(file.fileId).catch(() => {
            console.error("Could not delete an abandoned temporary upload");
          });
      }
    };
  }, []);

  function entryFor(file: File): FileUpload {
    return {
      key: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      mimetype: file.type,
      lastModified: file.lastModified,
      uploading: true,
      ...(previews ? { previewUrl: URL.createObjectURL(file) } : {})
    };
  }

  async function add(accepted: File[]) {
    if (!mounted.current) return;
    const queued = accepted.map((file) => ({ file, entry: entryFor(file) }));
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

  /** Attaches a file the server already has, as a finished upload that is never deleted from here. */
  function reuse(file: File, existing: ExistingUpload) {
    if (!mounted.current) return;
    const entry: FileUpload = {
      ...entryFor(file),
      fileId: existing.id,
      uploading: false,
      reused: true
    };
    replace([...owned.current, entry]);
  }

  /**
   * Resolves with the listed files once every one of them has finished
   * uploading. Rejects with `UploadsNotReadyError` when one of them leaves the
   * list first or when `signal` aborts. The uploads themselves go on.
   */
  function awaitUploads(keys: readonly string[], signal?: AbortSignal): Promise<FileUpload[]> {
    return new Promise((resolve, reject) => {
      const stop = () => {
        watchers.current.delete(check);
        signal?.removeEventListener("abort", onAbort);
      };
      const onAbort = () => {
        stop();
        reject(new UploadsNotReadyError("aborted"));
      };
      const check = () => {
        const batch = keys.map((key) => owned.current.find((file) => file.key === key));
        if (batch.some((file) => file === undefined)) {
          stop();
          reject(new UploadsNotReadyError("failed"));
          return;
        }
        const ready = batch.filter((file) => file !== undefined);
        if (ready.some((file) => file.uploading)) return;
        stop();
        resolve(ready);
      };
      if (signal?.aborted) {
        onAbort();
        return;
      }
      signal?.addEventListener("abort", onAbort, { once: true });
      watchers.current.add(check);
      check();
    });
  }

  function remove(key: string) {
    const removed = owned.current.filter((file) => file.key === key);
    replace(owned.current.filter((file) => file.key !== key));
    releasePreviews(removed);
    for (const file of removed) forget(file);
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
      for (const file of taken) forget(file);
      return;
    }
    const keys = new Set(taken.map((file) => file.key));
    replace([...taken, ...owned.current.filter((file) => !keys.has(file.key))]);
  }

  return { files, add, reuse, awaitUploads, remove, discard, detach, restore };
}

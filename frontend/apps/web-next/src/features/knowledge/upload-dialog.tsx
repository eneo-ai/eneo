"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { useJobs } from "@/features/jobs/use-jobs";
import type { InfoBlob } from "./knowledge";

type ValidationError = { fileName?: string; message: string };

/**
 * Upload documents into a collection: validates type/size against the tenant
 * limits and remaining quota, warns about duplicate titles, then hands the
 * files to the jobs upload queue (progress shows in the header indicator).
 */
export function UploadBlobsDialog({
  collectionId,
  currentBlobs,
  disabled
}: {
  collectionId: string;
  currentBlobs: InfoBlob[];
  disabled?: boolean;
}) {
  const t = useTranslations();
  const { limits, user } = useAppContext();
  const { queueUploads } = useJobs();
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);

  const acceptedMimeTypes = limits.info_blobs.formats.map((format) => format.mimetype);
  const sizeLimitByType = new Map(
    limits.info_blobs.formats.map((format) => [format.mimetype, format.size])
  );

  const { data: storage } = useQuery({
    queryKey: ["storage"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/storage/")),
    enabled: open
  });

  const errors = useMemo<ValidationError[]>(() => {
    const found: ValidationError[] = [];
    for (const file of files) {
      if (!acceptedMimeTypes.includes(file.type)) {
        found.push({
          fileName: file.name,
          message: `${file.name}: ${t("file_type_not_supported")}`
        });
        continue;
      }
      const limit = sizeLimitByType.get(file.type);
      if (limit !== undefined && file.size > limit) {
        found.push({
          fileName: file.name,
          message: `${file.name}: ${t("file_too_large")} (${formatBytes(file.size)} / max ${formatBytes(limit)})`
        });
      }
    }

    const remainingCandidates: number[] = [];
    if (user.quota_limit != null)
      remainingCandidates.push(user.quota_limit - (user.quota_used ?? 0));
    if (storage?.limit != null) remainingCandidates.push(storage.limit - storage.total_used);
    if (remainingCandidates.length > 0) {
      const remaining = Math.min(...remainingCandidates);
      const totalUploadSize = files.reduce((total, file) => total + file.size, 0);
      if (remaining <= 0 || totalUploadSize > remaining) {
        found.push({ message: t("quota_limit_reached") });
      }
    }
    return found;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, storage, user.quota_limit, user.quota_used, t]);

  function startUpload() {
    if (errors.length > 0 || files.length === 0) return;

    const existingTitles = new Set(currentBlobs.map((blob) => blob.metadata.title));
    const duplicates = files.filter((file) => existingTitles.has(file.name));
    if (duplicates.length > 0) {
      const proceed = window.confirm(
        t("duplicate_files_warning", { fileList: duplicates.map((file) => file.name).join("\n- ") })
      );
      if (!proceed) return;
    }

    queueUploads(collectionId, files);
    setOpen(false);
    setFiles([]);
  }

  return (
    <>
      <Button disabled={disabled} onClick={() => setOpen(true)}>
        {t("upload_files")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setFiles([]);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("upload_files")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <Input
              type="file"
              multiple
              accept={acceptedMimeTypes.join(",")}
              onChange={(event) => setFiles([...(event.target.files ?? [])])}
            />
            {files.length > 0 && (
              <ul className="max-h-48 overflow-y-auto rounded-md border p-2 text-sm">
                {files.map((file) => (
                  <li key={file.name} className="flex justify-between gap-4 truncate py-0.5">
                    <span className="truncate">{file.name}</span>
                    <span className="text-muted-foreground shrink-0">{formatBytes(file.size)}</span>
                  </li>
                ))}
              </ul>
            )}
            {errors.length > 0 && (
              <div className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
                {errors.map((error) => (
                  <p key={`${error.fileName}-${error.message}`}>{error.message}</p>
                ))}
              </div>
            )}
          </div>
          <DialogFooter>
            {files.length > 0 && (
              <Button variant="ghost" className="mr-auto" onClick={() => setFiles([])}>
                {t("clear_list")}
              </Button>
            )}
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={files.length === 0 || errors.length > 0} onClick={startUpload}>
              {t("upload_files")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

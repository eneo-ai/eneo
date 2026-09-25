"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { collectDroppedFiles } from "@/features/files/collect-dropped-files";
import { FileFormatDetails } from "@/features/files/file-format-details";
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
  collectionName,
  currentBlobs,
  disabled
}: {
  collectionId: string;
  collectionName: string;
  currentBlobs: InfoBlob[];
  disabled?: boolean;
}) {
  const t = useTranslations();
  const { limits, user, tenant, can } = useAppContext();
  const { queueUploads } = useJobs();
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [skippedFiles, setSkippedFiles] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [duplicateFileNames, setDuplicateFileNames] = useState<string[]>([]);

  const acceptedMimeTypes = limits.info_blobs.formats.map((format) => format.mimetype);
  const sizeLimitByType = new Map(
    limits.info_blobs.formats.map((format) => [format.mimetype, format.size])
  );

  const { data: storage } = useQuery({
    queryKey: ["storage", tenant.id],
    queryFn: () => unwrap(browserApi.GET("/api/v1/storage/")),
    enabled: open && can("admin")
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
      setDuplicateFileNames(duplicates.map((file) => file.name));
      return;
    }
    queueSelectedFiles();
  }

  function queueSelectedFiles() {
    queueUploads(collectionId, files);
    setDuplicateFileNames([]);
    setOpen(false);
    setFiles([]);
    setSkippedFiles([]);
  }

  function addSelectedFiles(selected: File[]) {
    const accepted = selected.filter((file) => acceptedMimeTypes.includes(file.type));
    const skipped = selected.filter((file) => !acceptedMimeTypes.includes(file.type));
    if (skipped.length > 0) {
      setSkippedFiles((current) => [...current, ...skipped.map((file) => file.name)]);
    }
    setFiles((current) => {
      const seen = new Set(current.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
      return [
        ...current,
        ...accepted.filter((file) => {
          const key = `${file.name}:${file.size}:${file.lastModified}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
      ];
    });
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
          if (!next) {
            setFiles([]);
            setSkippedFiles([]);
            setDragging(false);
            setDuplicateFileNames([]);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("upload_files")}</DialogTitle>
            <DialogDescription>
              {t("upload_files_to_collection_description", { name: collectionName })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div
              className={cn(
                "rounded-lg border-2 border-dashed p-4",
                dragging && "border-primary bg-primary/5"
              )}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                void collectDroppedFiles(event.dataTransfer)
                  .then(addSelectedFiles)
                  .catch(() => toast.error(t("file_upload_error")));
              }}
            >
              <p className="text-muted-foreground mb-2 text-sm">{t("upload_dropzone_prompt")}</p>
              <Input
                type="file"
                multiple
                accept={acceptedMimeTypes.join(",")}
                onChange={(event) => {
                  addSelectedFiles(Array.from(event.target.files ?? []));
                  event.target.value = "";
                }}
              />
            </div>
            <FileFormatDetails
              formats={limits.info_blobs.formats.map((format) => ({
                mimetype: format.mimetype,
                extensions: format.extensions,
                maxSize: format.size
              }))}
            />
            {skippedFiles.length > 0 && (
              <p className="text-muted-foreground rounded-md border px-3 py-2 text-sm">
                {t("upload_skipped_unsupported_files", { fileList: skippedFiles.join(", ") })}
              </p>
            )}
            {files.length > 0 && (
              <ul className="max-h-48 overflow-y-auto rounded-md border p-2 text-sm">
                {files.map((file, index) => (
                  <li
                    key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
                    className="flex justify-between gap-4 truncate py-0.5"
                  >
                    <span className="truncate">{file.name}</span>
                    <span className="text-muted-foreground shrink-0">{formatBytes(file.size)}</span>
                  </li>
                ))}
              </ul>
            )}
            {errors.length > 0 && (
              <div className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
                {errors.map((error, index) => (
                  <p key={`${error.fileName}-${error.message}-${index}`}>{error.message}</p>
                ))}
              </div>
            )}
          </div>
          <DialogFooter>
            {files.length > 0 && (
              <Button
                variant="ghost"
                className="mr-auto"
                onClick={() => {
                  setFiles([]);
                  setSkippedFiles([]);
                }}
              >
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
      <ConfirmDialogControlled
        open={duplicateFileNames.length > 0}
        onOpenChange={(next) => {
          if (!next) setDuplicateFileNames([]);
        }}
        title={t("duplicate_files_dialog_title")}
        description={`${t("duplicate_files_dialog_description")} ${duplicateFileNames.join(", ")}`}
        confirmLabel={t("replace_files")}
        variant="default"
        onConfirm={queueSelectedFiles}
      />
    </>
  );
}

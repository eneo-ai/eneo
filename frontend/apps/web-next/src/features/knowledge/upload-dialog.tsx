"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "use-intl";
import { useMemo, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { storageQueryOptions } from "@/features/storage/storage";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { sessionQueries } from "@/lib/api/session";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useFileDrop } from "@/features/files/use-file-drop";
import { FileFormatDetails } from "@/features/files/file-format-details";
import { useJobs } from "@/features/jobs/use-jobs";
import { collectionBlobsQueryOptions } from "./knowledge";

type ValidationError = { fileName?: string; message: string };

const FILES_ID = "knowledge-upload-files";
const FILE_ERRORS_ID = `${FILES_ID}-errors`;
const session = sessionQueries(browserApi);

/** "Ladda upp filer" on a collection's page: the button and its upload dialog. */
export function UploadBlobsButton({
  collectionId,
  collectionName,
  disabled
}: {
  collectionId: string;
  collectionName: string;
  disabled?: boolean;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button disabled={disabled} onClick={() => setOpen(true)}>
        {t("upload_files")}
      </Button>
      <UploadBlobsDialog
        collectionId={collectionId}
        collectionName={collectionName}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

/**
 * The one upload flow for a collection (its page and the space overview's
 * "Ladda upp"): shows the accepted formats and size limits, validates type
 * and size against them and the remaining quota, warns about duplicate titles,
 * then hands the files to the jobs upload queue (progress shows in the header
 * indicator). Controlled; the caller renders the trigger.
 */
export function UploadBlobsDialog({
  collectionId,
  collectionName,
  open,
  onOpenChange
}: {
  collectionId: string;
  collectionName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const { queueUploads } = useJobs();
  // Files whose titles the collection already has, waiting for "replace".
  const [replacing, setReplacing] = useState<{ files: File[]; names: string[] } | null>(null);

  function queue(files: File[]) {
    queueUploads(collectionId, files);
    setReplacing(null);
    onOpenChange(false);
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("upload_files")}</DialogTitle>
            <DialogDescription>
              {t("upload_files_to_collection_description", { name: collectionName })}
            </DialogDescription>
          </DialogHeader>
          <UploadBlobsForm
            collectionId={collectionId}
            onCancel={() => onOpenChange(false)}
            onUpload={(files, duplicateNames) => {
              if (duplicateNames.length > 0) setReplacing({ files, names: duplicateNames });
              else queue(files);
            }}
          />
        </DialogContent>
      </Dialog>
      <ConfirmDialogControlled
        open={replacing !== null}
        onOpenChange={(next) => {
          if (!next) setReplacing(null);
        }}
        title={t("duplicate_files_dialog_title")}
        description={`${t("duplicate_files_dialog_description")} ${replacing?.names.join(", ") ?? ""}`}
        confirmLabel={t("replace_files")}
        variant="default"
        onConfirm={() => {
          if (replacing) queue(replacing.files);
        }}
      />
    </>
  );
}

/**
 * The dialog's draft: the picked files and their problems. DialogContent
 * mounts it afresh on each opening, so a closed dialog's files never return.
 * Upload hands the files, with the titles the collection already has, to the
 * dialog, which owns the queueing.
 */
function UploadBlobsForm({
  collectionId,
  onCancel,
  onUpload
}: {
  collectionId: string;
  onCancel: () => void;
  onUpload: (files: File[], duplicateNames: string[]) => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const { limits, user, can } = useAppContext();
  const queryClient = useQueryClient();
  // The collection's files, for the duplicate-title warning (cached on its
  // page); loaded when the dialog opens, so Upload rarely waits for them.
  useQuery(collectionBlobsQueryOptions(browserApi, collectionId));
  const [checking, setChecking] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [skippedFiles, setSkippedFiles] = useState<string[]>([]);
  const { dragging, handlers } = useFileDrop(addSelectedFiles);

  const acceptedMimeTypes = limits.info_blobs.formats.map((format) => format.mimetype);
  const sizeLimitByType = new Map(
    limits.info_blobs.formats.map((format) => [format.mimetype, format.size])
  );

  const { data: storage } = useQuery({
    ...storageQueryOptions(browserApi),
    enabled: can("admin")
  });
  // The quota needs a fresh answer: the backend computes it live, and deleted
  // files or uploads in another tab move it without touching this tab's cache.
  // Each opening refetches the session's user (the one ["users", "me"]
  // entry, which the app context shows too).
  const { data: me = user } = useQuery({ ...session.me, staleTime: 0 });
  const quotaLimit = me.quota_limit;
  const quotaUsed = me.quota_used;

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
          message: `${file.name}: ${t("file_too_large")} (${formatBytes(file.size, locale)} / max ${formatBytes(limit, locale)})`
        });
      }
    }

    const remainingCandidates: number[] = [];
    if (quotaLimit != null) remainingCandidates.push(quotaLimit - (quotaUsed ?? 0));
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
  }, [files, storage, quotaLimit, quotaUsed, t]);

  const noFilesProblem = submitted && files.length === 0 ? t("form_problem_choose_files") : null;

  // Upload is never disabled: with no files, or files it cannot take, the
  // problem shows at the file field, which takes focus.
  async function startUpload() {
    if (files.length === 0 || errors.length > 0) {
      revealProblems(() => setSubmitted(true), FILES_ID);
      return;
    }

    // Wait for the collection's files, so the duplicate warning can run.
    setChecking(true);
    const currentBlobs = await queryClient
      .query({ ...collectionBlobsQueryOptions(browserApi, collectionId), staleTime: "static" })
      .catch(() => []);
    setChecking(false);
    const existingTitles = new Set(currentBlobs.map((blob) => blob.metadata.title));
    onUpload(
      files,
      files.filter((file) => existingTitles.has(file.name)).map((file) => file.name)
    );
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
      <div className="flex flex-col gap-3">
        <div
          className={cn(
            "rounded-lg border-2 border-dashed p-4",
            dragging && "border-primary bg-primary/5"
          )}
          {...handlers}
        >
          <Label htmlFor={FILES_ID} className="text-muted-foreground mb-2 text-sm font-normal">
            {t("upload_dropzone_prompt")}
          </Label>
          <Input
            id={FILES_ID}
            type="file"
            multiple
            accept={acceptedMimeTypes.join(",")}
            onChange={(event) => {
              addSelectedFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
            {...fieldProblemProps(
              FILES_ID,
              noFilesProblem,
              errors.length > 0 ? FILE_ERRORS_ID : undefined
            )}
            // Files it cannot take make the choice invalid as soon as they are added.
            aria-invalid={noFilesProblem !== null || errors.length > 0 || undefined}
          />
          <FieldProblem id={FILES_ID} problem={noFilesProblem} />
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
                <span className="text-muted-foreground shrink-0">
                  {formatBytes(file.size, locale)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {errors.length > 0 && (
          <div
            id={FILE_ERRORS_ID}
            className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm"
          >
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
        <Button variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button aria-busy={checking || undefined} onClick={() => void startUpload()}>
          {t("upload_files")}
        </Button>
      </DialogFooter>
    </>
  );
}

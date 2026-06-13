"use client";

import { Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { SaveRow } from "./general-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

type FileRef = { id: string; name: string };

/**
 * Assistant attachments: guideline files added to the assistant's context.
 * Files upload through the proxy (POST /files/) and their ids are saved on the
 * assistant; removing one here detaches it on save (the blob is not deleted).
 */
export function AttachmentsSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const fileInput = useRef<HTMLInputElement>(null);

  const saved: FileRef[] = (assistant.attachments ?? []).map((file) => ({
    id: file.id,
    name: file.name
  }));
  const [files, setFiles] = useState<FileRef[]>(saved);
  const [uploading, setUploading] = useState(false);

  const dirty =
    JSON.stringify(files.map((file) => file.id).sort()) !==
    JSON.stringify(saved.map((file) => file.id).sort());

  async function uploadFiles(selected: File[]) {
    setUploading(true);
    try {
      for (const file of selected) {
        const body = new FormData();
        body.append("upload_file", file);
        const uploaded = await unwrap(
          browserApi.POST("/api/v1/files/", {
            body: body as unknown as { upload_file: string },
            bodySerializer: (formData: unknown) => formData as FormData
          })
        );
        setFiles((current) => [...current, { id: uploaded.id, name: uploaded.name ?? file.name }]);
      }
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setUploading(false);
    }
  }

  return (
    <SettingsGroup title={t("attachments")}>
      <SettingsRow title={t("attachments")} description={t("attachments_description")}>
        <div className="flex flex-col gap-3">
          {files.length > 0 && (
            <ul className="flex flex-col gap-2">
              {files.map((file) => (
                <li
                  key={file.id}
                  className="border-border flex items-center justify-between gap-3 rounded-lg border p-2.5"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <Paperclip
                      aria-hidden="true"
                      className="text-muted-foreground size-4 shrink-0"
                    />
                    <span className="truncate text-sm">{file.name}</span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`${t("remove")} ${file.name}`}
                    onClick={() => setFiles((current) => current.filter((f) => f.id !== file.id))}
                  >
                    <X className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}

          <div>
            <Button
              type="button"
              variant="outline"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
            >
              {uploading ? <Spinner className="size-4" /> : <Paperclip className="size-4" />}
              {t("attach_files")}
            </Button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                void uploadFiles(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
          </div>
        </div>
      </SettingsRow>
      <SaveRow
        dirty={dirty}
        pending={update.isPending}
        onSave={() => update.mutate({ attachments: files.map((file) => ({ id: file.id })) })}
        onRevert={() => setFiles(saved)}
      />
    </SettingsGroup>
  );
}

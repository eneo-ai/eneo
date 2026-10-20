"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { useAppContext } from "@/components/providers/app-context";
import { FileChip } from "@/features/apps/run/upload-input";
import { useFileUploads, type FileUpload } from "@/features/files/use-file-uploads";
import { toastApiError } from "@/lib/api/toast";
import { createFlowRun, flowKeys } from "./flows";
import { formFieldsOf, type FlowPublic, type FormField, type FlowRunPublic } from "./types";

const FILE_TYPES = new Set(["file", "audio"]);

/** What a file field hands the dialog at submit time: its uploads and their ownership. */
type FileFieldHandle = {
  files: () => FileUpload[];
  awaitUploads: (keys: readonly string[]) => Promise<FileUpload[]>;
  /** The run owns the files now; they are not deleted when the field goes. */
  detach: () => void;
};

/**
 * One file or audio input of the run form. It owns its uploads (the shared
 * upload queue, one per field): picked files upload at once, a removed one is
 * deleted again, and files left behind when the dialog closes go too. The
 * dialog reads the field through its handle when the form is submitted.
 */
function FileField({
  field,
  accept,
  problem,
  register
}: {
  field: FormField;
  accept: string | undefined;
  problem: string | null;
  register: (key: string, handle: FileFieldHandle | null) => void;
}) {
  const t = useTranslations();
  const uploads = useFileUploads();
  const input = useRef<HTMLInputElement>(null);
  const { files, awaitUploads, detach } = uploads;

  // Re-registered every render, so the dialog always reads the current list.
  useEffect(() => {
    register(field.key, { files: () => files, awaitUploads, detach });
    return () => register(field.key, null);
  });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">
          {field.label}
          {field.required !== false && (
            <span className="text-ax-text-secondary"> ({t("required")})</span>
          )}
        </span>
        {field.description && (
          <span className="text-ax-text-secondary text-xs">{field.description}</span>
        )}
      </div>
      {files.map((file) => (
        <FileChip key={file.key} file={file} onRemove={() => uploads.remove(file.key)} />
      ))}
      <Button label={t("select_files")} size="sm" onClick={() => input.current?.click()} />
      <input
        ref={input}
        type="file"
        hidden
        multiple
        accept={field.type === "audio" ? "audio/*" : accept}
        onChange={(event) => {
          void uploads.add(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      {problem && (
        <p role="alert" className="text-ax-error m-0 text-xs">
          {problem}
        </p>
      )}
    </div>
  );
}

/**
 * Starts a run of the published version: one control per form field, files
 * uploaded as they are picked and sent as ids. A missing required value is
 * said at its field. Attachments belong to the dialog until the run is
 * created; closing it without starting deletes them again.
 */
export function FlowRunDialog({
  flow,
  open,
  onOpenChange,
  onStarted
}: {
  flow: FlowPublic;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (run: FlowRunPublic) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { limits } = useAppContext();
  const formId = useId();
  const fileFields = useRef(new Map<string, FileFieldHandle>());
  const [values, setValues] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({});
  const fields = formFieldsOf(flow.definition);
  const accept = limits.attachments.formats.map((format) => format.mimetype).join(",") || undefined;

  const register = useCallback((key: string, handle: FileFieldHandle | null) => {
    if (handle) fileFields.current.set(key, handle);
    else fileFields.current.delete(key);
  }, []);

  const start = useMutation({
    mutationFn: async () => {
      const files: Record<string, string[]> = {};
      for (const [key, handle] of fileFields.current) {
        const picked = handle.files();
        // Files still on their way: the run waits for them.
        const ready = picked.some((file) => file.uploading)
          ? await handle.awaitUploads(picked.map((file) => file.key))
          : picked;
        files[key] = ready.flatMap((file) => (file.fileId ? [file.fileId] : []));
      }
      const payload: Record<string, unknown> = {};
      for (const field of fields) {
        if (FILE_TYPES.has(field.type)) continue;
        const raw = values[field.key] ?? "";
        if (raw === "") continue;
        payload[field.key] = field.type === "number" ? Number(raw) : raw;
      }
      const run = await createFlowRun(flow.id, {
        values: payload,
        files,
        run_label: label.trim() || null,
        expected_flow_version: flow.published_version ?? null
      });
      // The run owns the files now; the fields must not delete them.
      for (const handle of fileFields.current.values()) handle.detach();
      return run;
    },
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: flowKeys.runs(flow.id) });
      reset();
      onOpenChange(false);
      onStarted(run);
    },
    onError: (error) => toastApiError(error, t)
  });

  function reset() {
    setValues({});
    setLabel("");
    setProblems({});
  }

  function requestOpenChange(next: boolean) {
    if (next) onOpenChange(true);
    else if (!start.isPending) {
      reset();
      onOpenChange(false);
    }
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (start.isPending) return;
    const found: Record<string, string> = {};
    for (const field of fields) {
      const value = values[field.key] ?? "";
      if (field.type === "number" && value.trim() !== "" && Number.isNaN(Number(value))) {
        found[field.key] = t("flow_run_field_number", { label: field.label });
        continue;
      }
      if (field.required === false) continue;
      const empty = FILE_TYPES.has(field.type)
        ? (fileFields.current.get(field.key)?.files().length ?? 0) === 0
        : value.trim() === "";
      if (empty) found[field.key] = t("flow_run_field_required", { label: field.label });
    }
    setProblems(found);
    if (Object.keys(found).length > 0) return;
    start.mutate();
  }

  const status = (field: FormField) =>
    problems[field.key] ? { type: "error" as const, message: problems[field.key] } : undefined;

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={480}>
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("flow_run_dialog_title", { name: flow.name })}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
                {fields.map((field) => {
                  const common = {
                    label: field.label,
                    description: field.description ?? undefined,
                    isRequired: field.required !== false,
                    status: status(field)
                  };
                  if (FILE_TYPES.has(field.type)) {
                    return (
                      <FileField
                        key={field.key}
                        field={field}
                        accept={accept}
                        problem={problems[field.key] ?? null}
                        register={register}
                      />
                    );
                  }
                  if (field.type === "select") {
                    return (
                      <Selector
                        key={field.key}
                        {...common}
                        options={field.options ?? []}
                        value={values[field.key] ?? ""}
                        placeholder={t("flow_run_select_placeholder")}
                        onChange={(value) =>
                          setValues((current) => ({ ...current, [field.key]: value ?? "" }))
                        }
                      />
                    );
                  }
                  if (field.type === "number") {
                    return (
                      <TextInput
                        key={field.key}
                        {...common}
                        value={values[field.key] ?? ""}
                        autoComplete="off"
                        onChange={(value) =>
                          setValues((current) => ({ ...current, [field.key]: value }))
                        }
                      />
                    );
                  }
                  return (
                    <TextArea
                      key={field.key}
                      {...common}
                      value={values[field.key] ?? ""}
                      rows={3}
                      onChange={(value) =>
                        setValues((current) => ({ ...current, [field.key]: value }))
                      }
                    />
                  );
                })}
                <TextInput
                  label={t("flow_run_label")}
                  description={t("flow_run_label_hint")}
                  value={label}
                  isOptional
                  autoComplete="off"
                  onChange={setLabel}
                />
              </form>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={start.isPending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("flow_run_start")}
                  isLoading={start.isPending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}

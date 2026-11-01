import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FileInput } from "@astryxdesign/core/FileInput";
import { HStack, Layout, LayoutContent, LayoutFooter, VStack } from "@astryxdesign/core/Layout";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { useTranslations } from "use-intl";
import { revealProblems } from "@/components/composites/field-problem";
import { ListError } from "@/components/composites/query-state";
import {
  uploadDocumentTemplate,
  updateDocumentTemplate,
  replaceDocumentTemplate,
  type DocumentTemplate
} from "@/features/document-templates/document-templates";
import { browserApi } from "@/lib/api/browser";

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_NAME_LENGTH = 120;

export type DocumentTemplateAction =
  | { kind: "upload"; isDefault: boolean }
  | { kind: "rename" | "replace"; template: DocumentTemplate };

export function DocumentTemplateDialog({
  action,
  onClose,
  onSaved
}: {
  action: DocumentTemplateAction;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const t = useTranslations();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState(action.kind === "rename" ? action.template.name : "");
  const [isDefault, setDefault] = useState(action.kind === "upload" && action.isDefault);
  const [attempted, setAttempted] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      if (action.kind === "rename")
        return updateDocumentTemplate(browserApi, action.template.id, { name: effectiveName });
      if (!file) throw new Error(t("required_field"));
      if (action.kind === "replace")
        return replaceDocumentTemplate(browserApi, action.template.id, file);
      return uploadDocumentTemplate(browserApi, file, effectiveName, isDefault);
    },
    onSuccess: onSaved
  });
  const effectiveName =
    name.trim() || (action.kind === "upload" ? file?.name.replace(/\.docx$/i, "") : "") || "";
  const nameError = !effectiveName
    ? t("required_field")
    : effectiveName.length > MAX_NAME_LENGTH
      ? t("document_template_name_too_long", { max: MAX_NAME_LENGTH })
      : null;

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (save.isPending || (action.kind !== "rename" && !file)) return;
    if (action.kind !== "replace" && nameError) {
      const input = event.currentTarget.querySelector<HTMLInputElement>('input[type="text"]');
      revealProblems(() => setAttempted(true), input?.id ?? "");
      return;
    }
    save.mutate();
  }

  return (
    <Dialog
      isOpen
      purpose="form"
      width={480}
      padding={0}
      onOpenChange={(open) => {
        if (!open && !save.isPending) onClose();
      }}
    >
      <form onSubmit={submit} noValidate>
        <Layout
          padding={4}
          header={
            <DialogHeader
              title={t(
                action.kind === "upload"
                  ? "document_template_upload"
                  : action.kind === "rename"
                    ? "document_template_rename"
                    : "document_template_replace_file"
              )}
              subtitle={action.kind !== "upload" ? action.template.name : undefined}
              onOpenChange={() => {
                if (!save.isPending) onClose();
              }}
            />
          }
          content={
            <LayoutContent>
              <VStack gap={4}>
                {action.kind !== "rename" && (
                  <FileInput
                    label={t("document_template_file")}
                    value={file}
                    mode="dropzone"
                    accept=".docx"
                    maxSize={MAX_FILE_BYTES}
                    isRequired
                    isLoading={save.isPending}
                    onChange={(value) => {
                      if (save.isPending) return;
                      const chosen = Array.isArray(value) ? (value[0] ?? null) : value;
                      setFile(chosen);
                      if (chosen && !name.trim()) setName(chosen.name.replace(/\.docx$/i, ""));
                    }}
                  />
                )}
                {action.kind !== "replace" && (
                  <TextInput
                    label={t("document_template_name")}
                    value={name}
                    onChange={setName}
                    maxLength={MAX_NAME_LENGTH}
                    isReadOnly={save.isPending}
                    status={
                      attempted && nameError ? { type: "error", message: nameError } : undefined
                    }
                  />
                )}
                {action.kind === "upload" && (
                  <CheckboxInput
                    label={t("document_template_make_default_switch")}
                    value={isDefault}
                    onChange={setDefault}
                    isReadOnly={save.isPending}
                  />
                )}
                {save.error && (
                  <ListError error={save.error} title={t("document_template_could_not_save")} />
                )}
              </VStack>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <HStack gap={2} hAlign="end">
                <Button
                  label={t("cancel")}
                  variant="secondary"
                  isDisabled={save.isPending}
                  onClick={onClose}
                />
                <Button
                  label={t(save.isPending ? "document_template_saving" : "document_template_save")}
                  type="submit"
                  isDisabled={action.kind !== "rename" && !file}
                  isLoading={save.isPending}
                  isInterruptible
                />
              </HStack>
            </LayoutFooter>
          }
        />
      </form>
    </Dialog>
  );
}

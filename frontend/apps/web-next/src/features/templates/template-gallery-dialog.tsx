"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, FileUp, Loader2, Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
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
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { FileKindIcon } from "@/features/chat/attachments";
import { toastUploadRejection } from "@/features/files/upload-rejection-toast";
import { planFileUploads, type FileUploadRules } from "@/features/files/upload-plan";
import { KnowledgePicker } from "@/features/knowledge/select/knowledge-picker";
import type { KnowledgeSelections } from "@/features/knowledge/select/logic";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import type { Schema } from "@/lib/api/models";
import {
  buildTemplateCreate,
  templateHasWizard,
  validateTemplateWizardSubmission
} from "./template-create";

type TemplateKind = "assistant" | "app";
type TemplateOption = Schema<"AssistantTemplatePublic"> | Schema<"AppTemplatePublic">;
type TemplateCreate = Schema<"TemplateCreate">;

type TemplateAttachment = {
  key: string;
  fileId?: string;
  name: string;
  size: number;
  mimetype: string;
  uploading: boolean;
};

const EMPTY_KNOWLEDGE_SELECTIONS: KnowledgeSelections = {
  collections: [],
  websites: [],
  integrationKnowledge: []
};

function templateAttachmentRules(formats: Schema<"AttachmentLimits">["formats"]): FileUploadRules {
  const supported = formats.filter((format) => !format.vision);
  return {
    acceptString: supported.map((format) => format.mimetype).join(","),
    maxFiles: Infinity,
    maxSize: Infinity,
    perTypeLimits: supported.map((format) => ({
      mimetype: format.mimetype,
      sizeLimit: format.size
    }))
  };
}

async function uploadTemplateFile(file: File): Promise<Schema<"FilePublic">> {
  const body = new FormData();
  body.append("upload_file", file);
  return unwrap(
    browserApi.POST("/api/v1/files/", {
      body: body as unknown as { upload_file: string },
      bodySerializer: (formData: unknown) => formData as FormData
    })
  );
}

function deleteUploadedFile(id: string): void {
  browserApi.DELETE("/api/v1/files/{id}/", { params: { path: { id } } }).catch(() => undefined);
}

function WizardSection({
  icon,
  title,
  description,
  badge,
  children
}: {
  icon: React.ReactNode;
  title: string;
  description?: string | null;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-start gap-3">
        <span className="text-muted-foreground mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-medium">{title}</h3>
            {badge ? (
              <span className="text-muted-foreground text-sm font-normal">({badge})</span>
            ) : null}
          </div>
          {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}
        </div>
      </div>
      <div className="pl-8">{children}</div>
    </section>
  );
}

function TemplateAttachmentList({
  attachments,
  onRemove
}: {
  attachments: TemplateAttachment[];
  onRemove: (key: string) => void;
}) {
  const t = useTranslations();

  if (attachments.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("no_attachments")}</p>;
  }

  return (
    <ul className="flex max-h-48 flex-col gap-2 overflow-y-auto pr-1">
      {attachments.map((attachment) => (
        <li
          key={attachment.key}
          className="bg-card flex min-h-12 items-center gap-3 rounded-lg border px-3 py-2"
        >
          <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
            {attachment.uploading ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <FileKindIcon mimetype={attachment.mimetype} className="size-4" />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{attachment.name}</p>
            <p className="text-muted-foreground truncate text-xs">{formatBytes(attachment.size)}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("remove_this_attachment")}
            onClick={() => onRemove(attachment.key)}
          >
            <X className="size-4" />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function TemplateWizard({
  template,
  knowledgeSelections,
  onKnowledgeChange,
  attachments,
  uploadRules,
  uploading,
  onAddFiles,
  onRemoveAttachment
}: {
  template: TemplateOption;
  knowledgeSelections: KnowledgeSelections;
  onKnowledgeChange: (next: KnowledgeSelections) => void;
  attachments: TemplateAttachment[];
  uploadRules: FileUploadRules;
  uploading: boolean;
  onAddFiles: (files: File[]) => void;
  onRemoveAttachment: (key: string) => void;
}) {
  const t = useTranslations();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const wizard = template.wizard;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="font-mono text-xs font-normal uppercase">{t("template_setup")}</p>
        <h2 className="text-xl font-semibold">{template.name}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{t("configure_template_settings")}</p>
      </div>

      {wizard.collections ? (
        <WizardSection
          icon={<BookOpen className="size-5" />}
          title={wizard.collections.title || t("wizard_collections_section")}
          description={wizard.collections.description}
          badge={wizard.collections.required ? t("recommended") : undefined}
        >
          {wizard.collections.required ? (
            <div className="flex flex-col gap-3">
              <KnowledgePicker
                origin="personal"
                selections={knowledgeSelections}
                onChange={onKnowledgeChange}
                resourceKinds={{ collections: true, websites: false, integrationKnowledge: false }}
              />
              <KnowledgePicker
                origin="organization"
                selections={knowledgeSelections}
                onChange={onKnowledgeChange}
                resourceKinds={{ collections: true, websites: false, integrationKnowledge: false }}
              />
            </div>
          ) : (
            <p className="text-muted-foreground text-sm italic">{t("knowledge_add_later_hint")}</p>
          )}
        </WizardSection>
      ) : null}

      {wizard.attachments ? (
        <WizardSection
          icon={<FileUp className="size-5" />}
          title={wizard.attachments.title || t("wizard_attachments_section")}
          description={wizard.attachments.description}
          badge={wizard.attachments.required ? t("required") : undefined}
        >
          {wizard.attachments.required ? (
            <div className="flex flex-col gap-3">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                accept={uploadRules.acceptString}
                onChange={(event) => {
                  onAddFiles(Array.from(event.target.files ?? []));
                  event.currentTarget.value = "";
                }}
              />
              <TemplateAttachmentList attachments={attachments} onRemove={onRemoveAttachment} />
              <Button
                type="button"
                variant="outline"
                className="w-fit"
                disabled={uploading}
                onClick={() => fileInputRef.current?.click()}
              >
                {uploading ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Paperclip className="size-4" />
                )}
                {t("upload_files")}
              </Button>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm italic">
              {t("attachments_add_later_hint")}
            </p>
          )}
        </WizardSection>
      ) : null}
    </div>
  );
}

async function fetchTemplates(kind: TemplateKind): Promise<TemplateOption[]> {
  if (kind === "assistant") {
    return (await unwrap(browserApi.GET("/api/v1/templates/assistants/"))).items;
  }
  return (await unwrap(browserApi.GET("/api/v1/templates/apps/"))).items;
}

/** Pick a template, collect its wizard data, and create from_template. */
export function TemplateGalleryDialog({
  templateKind,
  createLabel,
  open,
  onOpenChange,
  pending,
  onCreate
}: {
  templateKind: TemplateKind;
  createLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pending: boolean;
  onCreate: (fromTemplate: TemplateCreate, name: string) => Promise<void> | void;
}) {
  const t = useTranslations();
  const { limits } = useAppContext();
  const [selected, setSelected] = useState<TemplateOption | null>(null);
  const [name, setName] = useState("");
  const [step, setStep] = useState<"gallery" | "wizard">("gallery");
  const [knowledgeSelections, setKnowledgeSelections] = useState<KnowledgeSelections>(
    EMPTY_KNOWLEDGE_SELECTIONS
  );
  const [attachments, setAttachments] = useState<TemplateAttachment[]>([]);

  const uploadRules = useMemo(
    () => templateAttachmentRules(limits.attachments.formats),
    [limits.attachments.formats]
  );

  const templates = useQuery({
    queryKey: [templateKind, "templates-gallery"],
    enabled: open,
    queryFn: () => fetchTemplates(templateKind)
  });

  const uploading = attachments.some((attachment) => attachment.uploading);

  const reset = ({ deleteUploaded }: { deleteUploaded: boolean }) => {
    if (deleteUploaded) {
      for (const attachment of attachments) {
        if (attachment.fileId) deleteUploadedFile(attachment.fileId);
      }
    }
    setSelected(null);
    setName("");
    setStep("gallery");
    setKnowledgeSelections({ ...EMPTY_KNOWLEDGE_SELECTIONS });
    setAttachments([]);
  };

  async function addFiles(files: File[]) {
    if (files.length === 0) return;
    const plan = planFileUploads(files, attachments, uploadRules);
    const shown = { maxFiles: false };
    for (const rejection of plan.rejected) toastUploadRejection(rejection, t, shown);

    for (const file of plan.accepted) {
      const key = crypto.randomUUID();
      setAttachments((current) => [
        ...current,
        { key, name: file.name, size: file.size, mimetype: file.type, uploading: true }
      ]);

      try {
        const uploaded = await uploadTemplateFile(file);
        setAttachments((current) =>
          current.map((attachment) =>
            attachment.key === key
              ? {
                  ...attachment,
                  fileId: uploaded.id,
                  name: uploaded.name ?? attachment.name,
                  mimetype: uploaded.mimetype ?? attachment.mimetype,
                  size: uploaded.size ?? attachment.size,
                  uploading: false
                }
              : attachment
          )
        );
      } catch (error) {
        toastApiError(error, t);
        setAttachments((current) => current.filter((attachment) => attachment.key !== key));
      }
    }
  }

  function removeAttachment(key: string) {
    const attachment = attachments.find((candidate) => candidate.key === key);
    if (attachment?.fileId) deleteUploadedFile(attachment.fileId);
    setAttachments((current) => current.filter((candidate) => candidate.key !== key));
  }

  async function submit() {
    if (!selected || !name.trim() || pending) return;

    if (templateHasWizard(selected) && step === "gallery") {
      setStep("wizard");
      return;
    }

    const submission = validateTemplateWizardSubmission({
      wizard: selected.wizard,
      collectionIds: knowledgeSelections.collections.map((collection) => collection.id),
      attachments
    });

    if (!submission.ok) {
      toast.warning(
        submission.reason === "uploads-in-progress"
          ? t("template_uploads_in_progress")
          : t("template_attachments_required")
      );
      return;
    }

    if (submission.notices.includes("knowledge-recommended")) {
      toast.info(t("template_knowledge_recommendation"));
    }

    await onCreate(buildTemplateCreate(selected.id, submission.additionalFields), name.trim());
    reset({ deleteUploaded: false });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset({ deleteUploaded: true });
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("select_a_template")}</DialogTitle>
        </DialogHeader>

        {step === "gallery" ? (
          <>
            {templates.isPending ? (
              <Skeleton className="h-48 w-full" />
            ) : (templates.data ?? []).length === 0 ? (
              <p className="text-muted-foreground py-6 text-center text-sm">{t("no_results")}</p>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {(templates.data ?? []).map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    onClick={() => {
                      setSelected(template);
                      setName((current) => current || template.name);
                    }}
                    className={`flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors ${
                      selected?.id === template.id
                        ? "border-primary bg-accent"
                        : "hover:bg-muted/50"
                    }`}
                  >
                    <span className="font-medium">{template.name}</span>
                    {template.description && (
                      <span className="text-muted-foreground line-clamp-2 text-xs">
                        {template.description}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {selected ? (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="template-create-name">{t("name")}</Label>
                <Input
                  id="template-create-name"
                  value={name}
                  autoFocus
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            ) : null}
          </>
        ) : selected ? (
          <TemplateWizard
            template={selected}
            knowledgeSelections={knowledgeSelections}
            onKnowledgeChange={setKnowledgeSelections}
            attachments={attachments}
            uploadRules={uploadRules}
            uploading={uploading}
            onAddFiles={(files) => void addFiles(files)}
            onRemoveAttachment={removeAttachment}
          />
        ) : null}

        <DialogFooter>
          {step === "wizard" ? (
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => setStep("gallery")}
            >
              <ArrowLeft className="size-4" />
              {t("back")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button
            type="button"
            disabled={!selected || !name.trim() || pending}
            onClick={() => void submit()}
          >
            {pending
              ? t("loading")
              : selected && templateHasWizard(selected) && step === "gallery"
                ? t("next")
                : createLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

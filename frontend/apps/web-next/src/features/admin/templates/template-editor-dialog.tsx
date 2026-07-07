"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import type { ModelKwargs } from "@/features/assistants/editor/model-kwargs";
import {
  APP_KEY,
  ASSISTANT_KEY,
  type AppTemplate,
  type AssistantTemplate,
  createAppTemplate,
  createAssistantTemplate,
  updateAppTemplate,
  updateAssistantTemplate
} from "./templates";

type TemplateKind = "assistants" | "apps";
type EditableTemplate = AssistantTemplate | AppTemplate;

const NO_MODEL = "__none__";

export function TemplateEditorDialog({
  kind,
  template,
  open,
  onOpenChange
}: {
  kind: TemplateKind;
  template?: EditableTemplate | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const isApp = kind === "apps";
  const editing = Boolean(template);

  const { data: models } = useQuery({ ...adminModelsQueryOptions(browserApi), enabled: open });

  const [name, setName] = useState(template?.name ?? "");
  const [category, setCategory] = useState(template?.category ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [prompt, setPrompt] = useState(template?.prompt_text ?? "");
  const [modelId, setModelId] = useState(template?.completion_model_id ?? NO_MODEL);
  const [iconName, setIconName] = useState(template?.icon_name ?? "");
  const [inputType, setInputType] = useState(
    template && "input_type" in template ? (template.input_type ?? "text") : "text"
  );
  const [inputDescription, setInputDescription] = useState(
    template && "input_description" in template ? (template.input_description ?? "") : ""
  );

  const initialKwargs = (template?.completion_model_kwargs as ModelKwargs | undefined) ?? {};
  const [temperature, setTemperature] = useState(
    initialKwargs.temperature != null ? String(initialKwargs.temperature) : ""
  );

  const wizard = template?.wizard ?? null;
  const [attachmentsEnabled, setAttachmentsEnabled] = useState(Boolean(wizard?.attachments));
  const [attachmentsRequired, setAttachmentsRequired] = useState(
    wizard?.attachments?.required ?? false
  );
  const [attachmentsTitle, setAttachmentsTitle] = useState(wizard?.attachments?.title ?? "");
  const [attachmentsDescription, setAttachmentsDescription] = useState(
    wizard?.attachments?.description ?? ""
  );
  const [collectionsEnabled, setCollectionsEnabled] = useState(Boolean(wizard?.collections));
  const [collectionsRequired, setCollectionsRequired] = useState(
    wizard?.collections?.required ?? false
  );
  const [collectionsTitle, setCollectionsTitle] = useState(wizard?.collections?.title ?? "");
  const [collectionsDescription, setCollectionsDescription] = useState(
    wizard?.collections?.description ?? ""
  );

  const save = useMutation({
    mutationFn: () => {
      const completionModelId = modelId === NO_MODEL ? null : modelId;
      const wizardBody = {
        attachments: attachmentsEnabled
          ? {
              required: attachmentsRequired,
              title: attachmentsTitle.trim() || null,
              description: attachmentsDescription.trim() || null
            }
          : null,
        // App templates never carry a collections step (backend enforces null).
        collections:
          isApp || !collectionsEnabled
            ? null
            : {
                required: collectionsRequired,
                title: collectionsTitle.trim() || null,
                description: collectionsDescription.trim() || null
              }
      };
      const kwargsBody: ModelKwargs = { ...initialKwargs };
      if (temperature.trim() === "") delete kwargsBody.temperature;
      else kwargsBody.temperature = Number(temperature);
      const base = {
        name: name.trim(),
        category: category.trim(),
        description: description.trim() || null,
        prompt: prompt.trim() || null,
        completion_model_id: completionModelId,
        completion_model_kwargs: kwargsBody,
        wizard: wizardBody,
        icon_name: iconName.trim() || null
      };
      if (isApp) {
        const appBody = {
          ...base,
          input_type: inputType.trim() || "text",
          input_description: inputDescription.trim() || null
        };
        return editing
          ? updateAppTemplate(browserApi, template!.id, appBody)
          : createAppTemplate(browserApi, appBody);
      }
      return editing
        ? updateAssistantTemplate(browserApi, template!.id, base)
        : createAssistantTemplate(browserApi, base);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: isApp ? APP_KEY : ASSISTANT_KEY });
      toast.success(editing ? t("template_updated") : t("template_created"));
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t("edit_template") : t("new_template")}</DialogTitle>
          <DialogDescription>
            {isApp ? t("create_app_template") : t("create_assistant_template")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-name">{t("template_name")}</Label>
            <Input
              id="template-name"
              value={name}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-category">{t("category")}</Label>
            <Input
              id="template-category"
              value={category}
              required
              onChange={(event) => setCategory(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-description">{t("description")}</Label>
            <Textarea
              id="template-description"
              value={description}
              rows={2}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-prompt">{t("prompt")}</Label>
            <Textarea
              id="template-prompt"
              value={prompt}
              rows={4}
              onChange={(event) => setPrompt(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-model">{t("completion_model")}</Label>
            <Select value={modelId} onValueChange={setModelId}>
              <SelectTrigger id="template-model" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_MODEL}>{t("none")}</SelectItem>
                {(models?.completion_models ?? []).map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.nickname ?? model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-temperature">
              {t("temperature")} <span className="text-muted-foreground">({t("optional")})</span>
            </Label>
            <Input
              id="template-temperature"
              type="number"
              min={0}
              max={2}
              step={0.1}
              className="w-32"
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
            />
          </div>
          {isApp && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="template-input-type">{t("input_type")}</Label>
                <Input
                  id="template-input-type"
                  value={inputType}
                  onChange={(event) => setInputType(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="template-input-description">{t("input_description")}</Label>
                <Textarea
                  id="template-input-description"
                  value={inputDescription}
                  rows={2}
                  onChange={(event) => setInputDescription(event.target.value)}
                />
              </div>
            </>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-icon">
              {t("icon_name")} <span className="text-muted-foreground">({t("optional")})</span>
            </Label>
            <Input
              id="template-icon"
              value={iconName}
              onChange={(event) => setIconName(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-3 rounded-lg border p-3">
            <span className="text-sm font-medium">{t("wizard_configuration")}</span>
            <WizardStep
              titleLabel={t("wizard_attachments_section")}
              description={t("wizard_attachments_description")}
              requiredDescription={t("wizard_attachments_required_description")}
              titlePlaceholder={t("wizard_attachments_title_placeholder")}
              descriptionPlaceholder={t("wizard_attachments_description_placeholder")}
              idPrefix="tpl-att"
              enabled={attachmentsEnabled}
              setEnabled={setAttachmentsEnabled}
              required={attachmentsRequired}
              setRequired={setAttachmentsRequired}
              title={attachmentsTitle}
              setTitle={setAttachmentsTitle}
              stepDescription={attachmentsDescription}
              setStepDescription={setAttachmentsDescription}
              t={t}
            />
            {!isApp && (
              <WizardStep
                titleLabel={t("wizard_collections_section")}
                description={t("wizard_collections_description")}
                requiredDescription={t("wizard_collections_required_description")}
                titlePlaceholder={t("wizard_collections_title_placeholder")}
                descriptionPlaceholder={t("wizard_collections_description_placeholder")}
                idPrefix="tpl-col"
                enabled={collectionsEnabled}
                setEnabled={setCollectionsEnabled}
                required={collectionsRequired}
                setRequired={setCollectionsRequired}
                title={collectionsTitle}
                setTitle={setCollectionsTitle}
                stepDescription={collectionsDescription}
                setStepDescription={setCollectionsDescription}
                t={t}
              />
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || !category.trim() || save.isPending}>
              {save.isPending ? t("saving") : editing ? t("save") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function WizardStep({
  titleLabel,
  description,
  requiredDescription,
  titlePlaceholder,
  descriptionPlaceholder,
  idPrefix,
  enabled,
  setEnabled,
  required,
  setRequired,
  title,
  setTitle,
  stepDescription,
  setStepDescription,
  t
}: {
  titleLabel: string;
  description: string;
  requiredDescription: string;
  titlePlaceholder: string;
  descriptionPlaceholder: string;
  idPrefix: string;
  enabled: boolean;
  setEnabled: (value: boolean) => void;
  required: boolean;
  setRequired: (value: boolean) => void;
  title: string;
  setTitle: (value: string) => void;
  stepDescription: string;
  setStepDescription: (value: string) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <span className="text-sm font-medium">{titleLabel}</span>
          <span className="text-muted-foreground text-xs">{description}</span>
        </div>
        <Switch checked={enabled} onCheckedChange={setEnabled} aria-label={titleLabel} />
      </div>
      {enabled && (
        <div className="flex flex-col gap-2 pl-1">
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={required}
              onCheckedChange={(checked) => setRequired(checked === true)}
            />
            {requiredDescription}
          </label>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`${idPrefix}-title`}>{t("title")}</Label>
            <Input
              id={`${idPrefix}-title`}
              value={title}
              placeholder={titlePlaceholder}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`${idPrefix}-desc`}>{t("description")}</Label>
            <Textarea
              id={`${idPrefix}-desc`}
              rows={2}
              value={stepDescription}
              placeholder={descriptionPlaceholder}
              onChange={(event) => setStepDescription(event.target.value)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

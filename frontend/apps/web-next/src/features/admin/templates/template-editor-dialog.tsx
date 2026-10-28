"use client";

import { Tooltip } from "@astryxdesign/core/Tooltip";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleHelp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { isInputFieldType, InputTypeSelect } from "@/features/apps/editor/input-type-select";
import type { InputFieldType } from "@/features/apps/apps";
import {
  filterSupportedKwargs,
  firstInvalidNumericKwarg,
  type ModelKwargs
} from "@/features/assistants/editor/model-kwargs";
import { ModelKwargsRows, modelKwargFieldId } from "@/features/assistants/editor/model-kwargs-rows";
import { TemplateCategoryField } from "./template-category-field";
import { TemplateIconPicker } from "./template-icon-picker";
import {
  APP_KEY,
  ASSISTANT_KEY,
  TEMPLATE_CATEGORIES,
  type AppTemplate,
  type AssistantTemplate,
  type TemplateKind,
  createAppTemplate,
  createAssistantTemplate,
  findTemplateModel,
  updateAppTemplate,
  updateAssistantTemplate
} from "./templates";

type EditableTemplate = AssistantTemplate | AppTemplate;
type CompletionModel = Parameters<typeof ModelSelector>[0]["models"][number];

/**
 * Creates or edits an assistant or app template. The completion models load
 * first, so a new template starts with the first one and an edited one keeps
 * its own (the Svelte templateForm's findTemplateModel).
 */
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
  const models = useQuery({ ...adminModelsQueryOptions(browserApi), enabled: open });
  const editing = Boolean(template);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? t("edit_template") : t("new_template")}</DialogTitle>
          <DialogDescription>
            {kind === "apps" ? t("create_app_template") : t("create_assistant_template")}
          </DialogDescription>
        </DialogHeader>
        <QueryStateBoundary query={models} rows={6}>
          {(data) => (
            <TemplateEditorForm
              kind={kind}
              template={template ?? null}
              completionModels={data.completion_models}
              onClose={() => onOpenChange(false)}
            />
          )}
        </QueryStateBoundary>
      </DialogContent>
    </Dialog>
  );
}

function TemplateEditorForm({
  kind,
  template,
  completionModels,
  onClose
}: {
  kind: TemplateKind;
  template: EditableTemplate | null;
  completionModels: CompletionModel[];
  onClose: () => void;
}) {
  const t = useTranslations();
  const { tenant } = useAppContext();
  const queryClient = useQueryClient();
  const isApp = kind === "apps";
  const editing = template !== null;

  const [name, setName] = useState(template?.name ?? "");
  const [iconName, setIconName] = useState<string | null>(template?.icon_name ?? null);
  const [category, setCategory] = useState(
    template?.category ?? TEMPLATE_CATEGORIES[kind][0]!.value
  );
  const [description, setDescription] = useState(template?.description ?? "");
  const [prompt, setPrompt] = useState(template?.prompt_text ?? "");
  const [modelId, setModelId] = useState(
    () => findTemplateModel(completionModels, template ?? undefined)?.id ?? null
  );
  const [kwargs, setKwargs] = useState<ModelKwargs>(
    () => (template?.completion_model_kwargs as ModelKwargs | null | undefined) ?? {}
  );
  // A stored type that is not one of the five (older templates saved "text")
  // shows as nothing chosen and must be chosen before saving.
  const [inputType, setInputType] = useState<InputFieldType | null>(() => {
    if (!template || !("input_type" in template)) return "text-field";
    return isInputFieldType(template.input_type) ? template.input_type : null;
  });
  const [inputDescription, setInputDescription] = useState(
    template && "input_description" in template ? (template.input_description ?? "") : ""
  );

  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const categoryRef = useRef<HTMLInputElement>(null);
  const nameProblem = submitted && !name.trim() ? t("template_name_required") : null;
  const categoryProblem = submitted && !category.trim() ? t("category_required") : null;
  const inputTypeProblem = submitted && isApp && !inputType ? t("input_type_required") : null;

  const model = completionModels.find((candidate) => candidate.id === modelId) ?? null;

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
    mutationFn: (appInputType: InputFieldType) => {
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
      const base = {
        name: name.trim(),
        category: category.trim(),
        description: description.trim() || null,
        prompt: prompt.trim() || null,
        completion_model_id: model?.id ?? null,
        // Kwargs the chosen model does not take are dropped, as the Svelte form does.
        completion_model_kwargs: filterSupportedKwargs(kwargs, model),
        wizard: wizardBody,
        icon_name: iconName
      };
      if (isApp) {
        const appBody = {
          ...base,
          input_type: appInputType,
          input_description: inputDescription.trim() || null
        };
        return editing
          ? updateAppTemplate(browserApi, template.id, appBody)
          : createAppTemplate(browserApi, appBody);
      }
      return editing
        ? updateAssistantTemplate(browserApi, template.id, base)
        : createAssistantTemplate(browserApi, base);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: isApp ? APP_KEY : ASSISTANT_KEY });
      toast.success(editing ? t("template_updated") : t("template_created"));
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    // Problems show at their fields on submit, and focus moves to the first.
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (save.isPending) return;
        // A number the model setting cannot take would save, then fail when an
        // app or assistant is created from the template.
        const invalidKwarg = firstInvalidNumericKwarg(model, kwargs);
        const firstProblem = !name.trim()
          ? nameRef.current
          : !category.trim()
            ? categoryRef.current
            : isApp && !inputType
              ? "template-input-type"
              : invalidKwarg
                ? modelKwargFieldId("template", invalidKwarg)
                : null;
        if (firstProblem) {
          revealProblems(() => setSubmitted(true), firstProblem);
          return;
        }
        save.mutate(inputType ?? "text-field");
      }}
    >
      <SettingsRow title={t("template_name")} htmlFor="template-name">
        <div className="flex items-center gap-3">
          <TemplateIconPicker value={iconName} onChange={setIconName} />
          <Input
            ref={nameRef}
            id="template-name"
            value={name}
            required
            className="h-11 flex-1"
            onChange={(event) => setName(event.target.value)}
            {...fieldProblemProps("template-name", nameProblem)}
          />
        </div>
        <FieldProblem id="template-name" problem={nameProblem} />
      </SettingsRow>
      <SettingsRow title={t("description")} htmlFor="template-description">
        <Textarea
          id="template-description"
          value={description}
          rows={2}
          onChange={(event) => setDescription(event.target.value)}
        />
      </SettingsRow>
      <SettingsRow title={t("category")} description={t("category_help")}>
        <TemplateCategoryField
          kind={kind}
          value={category}
          onChange={setCategory}
          problem={categoryProblem}
          customRef={categoryRef}
        />
      </SettingsRow>
      {isApp && (
        <>
          <SettingsRow
            title={t("input_description")}
            description={t("input_description_description")}
            htmlFor="template-input-description"
          >
            <Input
              id="template-input-description"
              value={inputDescription}
              onChange={(event) => setInputDescription(event.target.value)}
            />
          </SettingsRow>
          <SettingsRow
            title={t("input_type")}
            description={t("input_type_description")}
            htmlFor="template-input-type"
          >
            <InputTypeSelect
              id="template-input-type"
              value={inputType}
              onChange={setInputType}
              {...fieldProblemProps("template-input-type", inputTypeProblem)}
            />
            <FieldProblem id="template-input-type" problem={inputTypeProblem} />
          </SettingsRow>
        </>
      )}
      <SettingsRow
        title={t("prompt")}
        description={isApp ? t("app_prompt_description") : t("describe_assistant_behavior")}
        htmlFor="template-prompt"
      >
        <Textarea
          id="template-prompt"
          value={prompt}
          rows={4}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </SettingsRow>
      <SettingsRow
        title={t("completion_model")}
        description={isApp ? t("completion_model_description") : t("this_model_will_be_used")}
        htmlFor="template-model"
      >
        <ModelSelector
          id="template-model"
          models={completionModels}
          selectedId={modelId}
          onSelect={setModelId}
          className="w-full justify-between"
          showPricing={tenant.show_model_pricing === true}
        />
      </SettingsRow>
      <ModelKwargsRows
        idPrefix="template"
        model={model}
        kwargs={kwargs}
        behaviourDescription={
          isApp ? t("model_behaviour_description") : t("select_preset_behavior")
        }
        showProblems={submitted}
        onChange={setKwargs}
      />

      <div className="flex flex-col gap-3 rounded-lg border p-3">
        <span className="text-sm font-medium">{t("wizard_configuration")}</span>
        <WizardStep
          titleLabel={t("wizard_attachments_section")}
          description={t("wizard_attachments_description")}
          help={t("wizard_attachments_help")}
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
            help={t("wizard_collections_help")}
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
        <Button type="button" variant="outline" onClick={onClose}>
          {t("cancel")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button type="submit" aria-busy={save.isPending || undefined}>
          {save.isPending ? t("saving") : editing ? t("save") : t("create")}
        </Button>
      </DialogFooter>
    </form>
  );
}

function WizardStep({
  titleLabel,
  description,
  help,
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
  help: string;
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
          <span className="flex items-center gap-1 text-sm font-medium">
            {titleLabel}
            {/* When to use this step; a tap opens it on touch, as on an info icon. */}
            <Tooltip content={help} touchTrigger="tap">
              <button
                type="button"
                aria-label={t("help_about", { topic: titleLabel })}
                className="text-muted-foreground hover:text-foreground focus-visible:outline-ring inline-flex size-6 items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:size-11"
              >
                <CircleHelp aria-hidden="true" className="size-4" />
              </button>
            </Tooltip>
          </span>
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

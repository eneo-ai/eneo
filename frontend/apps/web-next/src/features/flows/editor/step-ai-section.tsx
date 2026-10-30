"use client";

import { Button } from "@astryxdesign/core/Button";
import { FieldLabel } from "@astryxdesign/core/Field";
import { FileInput } from "@astryxdesign/core/FileInput";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { Paperclip, X } from "lucide-react";
import { useLocale, useTranslations } from "use-intl";
import { useId, useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import {
  BEHAVIOUR_LIST,
  behaviourFromKwargs,
  isSelectKwarg,
  kwargCapability,
  kwargsForBehaviour,
  modelKwargLabel,
  modelKwargOptionLabel,
  modelSpecificKwargs,
  supportsBehaviorPresets,
  type ModelBehaviour,
  type ModelKwargName
} from "@/features/assistants/editor/model-kwargs";
import { fileRestrictionsRules, planFileUploads } from "@/features/files/upload-plan";
import { toastUploadRejection } from "@/features/files/upload-rejection-toast";
import { KnowledgePicker } from "@/features/knowledge/select/knowledge-picker";
import type { KnowledgeSelections } from "@/features/knowledge/select/logic";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import { Anchor, EditorSection, FieldMessage, problemStatus } from "./editor-fields";
import { TemplateTextArea } from "./reference-text-area";
import { useRecordUpload } from "./editor-uploads";
import type { FieldProblems } from "./field-problems";
import {
  readRetrievalPolicy,
  readTextProcessingMode,
  supportsRetrievalPolicy,
  withRetrievalPolicy,
  type RetrievalPolicyMode
} from "./step-configs";
import type { AssistantConfig, FlowAssistant, StepClassification, StepConfig } from "./step-types";
import type { VariableGroup } from "./step-variables";

const DEFAULT_VALUE = "__default";

/** The model's settings it supports: a behaviour preset (temperature), then its own. */
function ModelSettings({
  formId,
  modelId,
  kwargs,
  onChange,
  problem
}: {
  formId: string;
  modelId: string | null;
  kwargs: AssistantConfig["completion_model_kwargs"];
  onChange: (kwargs: AssistantConfig["completion_model_kwargs"]) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const model = space.completion_models.find((candidate) => candidate.id === modelId) ?? null;
  const behaviour = behaviourFromKwargs(kwargs);
  const specific = modelSpecificKwargs(model);
  const temperature = kwargCapability(model, "temperature");
  const set = (name: ModelKwargName, value: number | string | null) =>
    onChange({ ...kwargs, [name]: value });

  function selectBehaviour(next: ModelBehaviour) {
    const preset = kwargsForBehaviour(next);
    if (preset) onChange({ ...kwargs, temperature: preset.temperature });
    else if (behaviour !== "custom") onChange({ ...kwargs, temperature: 1 });
  }

  if (!model) return null;
  return (
    <Anchor formId={formId} anchor="completion_model_kwargs" className="grid gap-4 sm:grid-cols-2">
      {supportsBehaviorPresets(model) && (
        <Selector
          label={t("model_behaviour")}
          description={t("select_preset_behavior")}
          options={BEHAVIOUR_LIST.map((value) => ({
            value,
            label:
              value === "creative"
                ? t("creative")
                : value === "default"
                  ? t("default_behavior")
                  : value === "deterministic"
                    ? t("deterministic")
                    : t("custom")
          }))}
          value={behaviour}
          onChange={(value) => selectBehaviour(value as ModelBehaviour)}
          status={problemStatus(problem)}
        />
      )}
      {supportsBehaviorPresets(model) && behaviour === "custom" && (
        <NumberInput
          label={t("temperature")}
          value={typeof kwargs.temperature === "number" ? kwargs.temperature : null}
          onChange={(value) => set("temperature", value ?? null)}
          min={temperature?.minimum ?? 0}
          max={temperature?.maximum ?? 2}
          step={temperature?.step ?? 0.05}
          hasClear
        />
      )}
      {specific.map((name) => {
        const capability = kwargCapability(model, name);
        const current = kwargs[name] ?? null;
        if (isSelectKwarg(name)) {
          return (
            <Selector
              key={name}
              label={modelKwargLabel(name, t)}
              options={[
                { value: DEFAULT_VALUE, label: t("default_behavior") },
                ...(capability?.options ?? []).map((option) => ({
                  value: option,
                  label: modelKwargOptionLabel(option, t)
                }))
              ]}
              value={typeof current === "string" ? current : DEFAULT_VALUE}
              onChange={(value) => set(name, value === DEFAULT_VALUE ? null : value)}
            />
          );
        }
        return (
          <NumberInput
            key={name}
            label={modelKwargLabel(name, t)}
            value={typeof current === "number" ? current : null}
            onChange={(value) => set(name, value ?? null)}
            min={capability?.minimum ?? 0}
            max={capability?.maximum ?? null}
            step={capability?.step ?? 0.05}
            placeholder={t("default_behavior")}
            hasClear
          />
        );
      })}
    </Anchor>
  );
}

/** The files the step's AI reads beside its instruction, with uploads that join the draft. */
function Attachments({
  formId,
  files,
  restrictions,
  onChange,
  problem
}: {
  formId: string;
  files: AssistantConfig["attachments"];
  restrictions: FlowAssistant["allowed_attachments"];
  onChange: (files: AssistantConfig["attachments"]) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [uploading, setUploading] = useState(false);
  const recordUpload = useRecordUpload();
  const rules = fileRestrictionsRules(restrictions);

  async function add(picked: File | File[] | null) {
    const incoming = picked === null ? [] : Array.isArray(picked) ? picked : [picked];
    if (incoming.length === 0 || uploading) return;
    const { accepted, rejected } = planFileUploads(incoming, files, rules);
    const shown = { maxFiles: false };
    for (const rejection of rejected) toastUploadRejection(rejection, t, locale, shown);
    if (accepted.length === 0) return;
    setUploading(true);
    const added: AssistantConfig["attachments"] = [];
    try {
      for (const file of accepted) {
        const body = new FormData();
        body.append("upload_file", file);
        const uploaded = await unwrap(
          browserApi.POST("/api/v1/files/", {
            body: body as unknown as { upload_file: string },
            bodySerializer: (formData: unknown) => formData as FormData
          })
        );
        recordUpload({ kind: "file", id: uploaded.id });
        added.push(uploaded);
      }
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setUploading(false);
      if (added.length > 0) onChange([...files, ...added]);
    }
  }

  return (
    <Anchor formId={formId} anchor="attachments">
      <Text type="label" as="p" display="block" className="m-0">
        {t("flow_step_editor_attachments")}
      </Text>
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flow_step_editor_attachments_description")}
      </Text>
      {files.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {files.map((file) => (
            <li
              key={file.id}
              className="border-ax-border rounded-ax-element flex min-w-0 items-center gap-2 border px-3 py-1"
            >
              <Paperclip className="text-ax-text-secondary size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-sm" title={file.name}>
                {file.name}
              </span>
              <Text type="supporting" size="xsm">
                {formatBytes(file.size, locale)}
              </Text>
              <Button
                label={t("flow_step_editor_remove_attachment", { name: file.name })}
                isIconOnly
                icon={<X className="size-4" aria-hidden="true" />}
                variant="ghost"
                size="sm"
                onClick={() => onChange(files.filter((candidate) => candidate.id !== file.id))}
              />
            </li>
          ))}
        </ul>
      )}
      <FileInput
        label={t("flow_step_editor_attachments_add")}
        value={null}
        onChange={(picked) => void add(picked)}
        isMultiple
        accept={rules.acceptString || undefined}
        isLoading={uploading}
        status={problemStatus(problem)}
      />
    </Anchor>
  );
}

/**
 * The step's AI: its instruction, its model and the model's settings, and
 * the knowledge and files it reads. All of it belongs to the step's
 * flow-managed assistant and is saved with the step in one edit.
 */
export function StepAiSection({
  formId,
  sectionId,
  draft,
  assistant,
  savedAssistant,
  onAssistantChange,
  onStepChange,
  problems,
  groups,
  classification
}: {
  formId: string;
  sectionId: string;
  draft: StepConfig;
  assistant: AssistantConfig;
  savedAssistant: FlowAssistant;
  onAssistantChange: (change: Partial<AssistantConfig>) => void;
  onStepChange: (next: StepConfig) => void;
  problems: FieldProblems;
  groups: VariableGroup[];
  classification: StepClassification | null;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const { tenant } = useAppContext();
  const modelSelectorId = useId();
  const selections: KnowledgeSelections = {
    collections: assistant.groups,
    websites: assistant.websites,
    integrationKnowledge: assistant.integration_knowledge_list
  };
  const hasKnowledge =
    assistant.groups.length +
      assistant.websites.length +
      assistant.integration_knowledge_list.length >
    0;
  const readsInSections = readTextProcessingMode(draft.input_config) !== null;
  const qualifying = classification?.qualifying_model_ids ?? null;
  const modelBelow =
    qualifying !== null &&
    classification?.required_model_level !== null &&
    assistant.completion_model_id !== null &&
    !qualifying.includes(assistant.completion_model_id);
  const qualifyingNames = (qualifying ?? [])
    .map((id) => space.completion_models.find((model) => model.id === id))
    .flatMap((model) => (model ? [model.nickname?.trim() || model.name] : []));
  const retrieval = readRetrievalPolicy(draft.output_config);

  function changeKnowledge(next: KnowledgeSelections) {
    onAssistantChange({
      groups: next.collections,
      websites: next.websites,
      integration_knowledge_list: next.integrationKnowledge
    });
  }

  return (
    <EditorSection
      id={sectionId}
      title={t("flow_step_editor_ai_title")}
      description={t("flow_step_editor_ai_description")}
    >
      <Anchor formId={formId} anchor="prompt">
        <TemplateTextArea
          label={t("flow_step_editor_instruction")}
          description={t("flow_step_editor_instruction_description")}
          value={assistant.prompt}
          onChange={(prompt) => onAssistantChange({ prompt })}
          groups={groups}
          rows={8}
          status={problemStatus(problems.prompt)}
          placeholder={t("flow_step_editor_instruction_placeholder")}
        />
        {!assistant.prompt.trim() && draft.output_mode !== "speaker_mapping" && (
          <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
            {t("flow_step_editor_instruction_missing")}
          </Text>
        )}
      </Anchor>

      <Anchor formId={formId} anchor="completion_model" className="flex flex-col gap-2">
        <FieldLabel label={t("completion_model")} inputID={modelSelectorId} />
        <ModelSelector
          id={modelSelectorId}
          models={space.completion_models}
          selectedId={assistant.completion_model_id ?? ""}
          onSelect={(id) => onAssistantChange({ completion_model_id: id })}
          className="w-full justify-between"
          showPricing={tenant.show_model_pricing === true}
        />
        <FieldMessage message={problems.completion_model} />
        {modelBelow && (
          <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
            {qualifyingNames.length > 0
              ? t("flow_step_editor_model_below_classification", {
                  models: qualifyingNames.join(", ")
                })
              : t("flow_step_editor_model_below_classification_none")}
          </Text>
        )}
        {!assistant.completion_model_id && (
          <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
            {t("flow_step_editor_model_missing")}
          </Text>
        )}
      </Anchor>

      <ModelSettings
        formId={formId}
        modelId={assistant.completion_model_id}
        kwargs={assistant.completion_model_kwargs}
        onChange={(completion_model_kwargs) => onAssistantChange({ completion_model_kwargs })}
        problem={problems.completion_model_kwargs}
      />

      <Anchor formId={formId} anchor="knowledge">
        <div className="flex flex-col gap-1">
          <Text type="label" as="p" display="block" className="m-0">
            {t("knowledge")}
          </Text>
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_step_editor_knowledge_description")}
          </Text>
        </div>
        <KnowledgePicker origin="personal" selections={selections} onChange={changeKnowledge} />
        <KnowledgePicker origin="organization" selections={selections} onChange={changeKnowledge} />
        <FieldMessage message={problems.knowledge} />
        {hasKnowledge && readsInSections && (
          <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
            {t("flow_reading_mode_sections_knowledge_note")}
          </Text>
        )}
      </Anchor>

      {(hasKnowledge || retrieval !== null) && supportsRetrievalPolicy(draft.output_mode) && (
        <Anchor formId={formId} anchor="output_config.retrieval_policy">
          <Selector
            label={t("flow_step_editor_retrieval_policy")}
            description={t("flow_step_editor_retrieval_policy_description")}
            options={[
              { value: DEFAULT_VALUE, label: t("flow_step_editor_retrieval_policy_default") },
              { value: "best_effort", label: t("flow_step_editor_retrieval_policy_best_effort") },
              { value: "fail_closed", label: t("flow_step_editor_retrieval_policy_fail_closed") }
            ]}
            value={retrieval ?? DEFAULT_VALUE}
            onChange={(value) =>
              onStepChange({
                ...draft,
                output_config: withRetrievalPolicy(
                  draft.output_config,
                  value === DEFAULT_VALUE ? null : (value as RetrievalPolicyMode)
                )
              })
            }
            status={problemStatus(problems["output_config.retrieval_policy"])}
          />
        </Anchor>
      )}

      <Attachments
        formId={formId}
        files={assistant.attachments}
        restrictions={savedAssistant.allowed_attachments}
        onChange={(attachments) => onAssistantChange({ attachments })}
        problem={problems.attachments}
      />
    </EditorSection>
  );
}

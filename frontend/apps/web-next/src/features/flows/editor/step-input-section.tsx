"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { Switch } from "@astryxdesign/core/Switch";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Anchor, EditorSection, FieldMessage, problemStatus } from "./editor-fields";
import { TemplateTextArea } from "./reference-text-area";
import type { FieldProblems } from "./field-problems";
import { transcriptionEnabled } from "./step-draft";
import {
  FILE_INPUT_TYPES,
  longMaterialEligibility,
  newSourceRef,
  readHttpConfig,
  readInputBindings,
  readLongMaterial,
  readRuntimeInput,
  readTextProcessingMode,
  readToolConfig,
  sourceRefKey,
  sourceRefStepOrder,
  textProcessingEligibility,
  withHttpConfig,
  withLongMaterial,
  withRuntimeInput,
  withTextProcessingMode,
  withToolConfig,
  writeInputBindings,
  type RuntimeInputChange,
  type RuntimeInputFormat,
  type TextProcessingMode
} from "./step-configs";
import { HttpFields } from "./step-http-fields";
import {
  inputTypeLabel,
  inputSourceLabel,
  invalidOptionLabel,
  chainIssueText,
  stepLabel
} from "./step-labels";
import {
  applyInputSourceChange,
  applyInputTypeChange,
  chainIssue,
  inputSourceOptions,
  inputTypeOptions
} from "./step-rules";
import { ToolFields } from "./step-tool-fields";
import type { FlowPublic, InputSource, InputType, OutputType, StepConfig } from "./step-types";
import { materialOptions, stepsBefore, type VariableGroup } from "./step-variables";

const WHOLE = "whole";

const DOCUMENT_MIME_TYPES = [
  { value: "application/pdf", label: "PDF" },
  {
    value: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    label: "Word (.docx)"
  },
  {
    value: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    label: "Excel (.xlsx)"
  },
  { value: "application/vnd.ms-excel", label: "Excel (.xls)" },
  {
    value: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    label: "PowerPoint (.pptx)"
  },
  { value: "text/csv", label: "CSV" },
  { value: "text/plain", label: "TXT" },
  { value: "text/markdown", label: "Markdown" }
];
const AUDIO_MIME_TYPES = [
  { value: "audio/mpeg", label: "MP3" },
  { value: "audio/wav", label: "WAV" },
  { value: "audio/ogg", label: "OGG" },
  { value: "audio/x-m4a", label: "M4A" },
  { value: "audio/webm", label: "WebM" },
  { value: "audio/mp4", label: "MP4" }
];

function UploadMimeTypes({
  format,
  value,
  onChange
}: {
  format: RuntimeInputFormat;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const t = useTranslations();
  const presets = format === "audio" ? AUDIO_MIME_TYPES : DOCUMENT_MIME_TYPES;
  const known = new Set(presets.map((item) => item.value));
  const selected = value.filter((mime) => known.has(mime));
  const custom = value.filter((mime) => !known.has(mime));
  const signature = JSON.stringify(custom);
  // Keep separators while typing; a saved/rebased configuration replaces the draft.
  const [draft, setDraft] = useState({ signature, text: custom.join(", ") });
  if (draft.signature !== signature) setDraft({ signature, text: custom.join(", ") });
  return (
    <VStack gap={3} className="sm:col-span-2">
      <CheckboxList
        label={t("flow_runtime_input_mimetypes_label")}
        description={t("flow_runtime_input_mimetypes_hint")}
        value={selected}
        onChange={(items) => onChange([...items, ...custom])}
        density="compact"
      >
        {presets.map((item) => (
          <CheckboxListItem key={item.value} value={item.value} label={item.label} />
        ))}
      </CheckboxList>
      <TextInput
        label={t("flow_runtime_input_mimetypes_custom")}
        description={t("flow_runtime_input_mimetypes_custom_description")}
        value={draft.text}
        onChange={(text) => {
          const items = [
            ...new Set(
              text
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean)
            )
          ];
          setDraft({ text, signature: JSON.stringify(items.filter((mime) => !known.has(mime))) });
          onChange([...new Set([...selected, ...items])]);
        }}
        onBlur={() => setDraft({ signature, text: custom.join(", ") })}
        autoComplete="off"
        isOptional
      />
      <Button
        label={t("flow_runtime_input_mimetypes_reset")}
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => {
          setDraft({ signature: "[]", text: "" });
          onChange([]);
        }}
      />
    </VStack>
  );
}

function Uploads({
  formId,
  draft,
  onChange,
  problem
}: {
  formId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const runtime = readRuntimeInput(draft.input_config);
  const fileType = FILE_INPUT_TYPES.has(draft.input_type);
  const change = (patch: RuntimeInputChange) =>
    onChange({
      ...draft,
      input_config: withRuntimeInput(draft.input_config, draft.input_type, patch)
    });
  return (
    <Anchor formId={formId} anchor="input_config.runtime_input">
      {fileType ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_uploads_always", { type: inputTypeLabel(draft.input_type, t) })}
        </Text>
      ) : (
        <Switch
          label={t("flow_step_editor_uploads_enabled")}
          description={t("flow_step_editor_uploads_enabled_description")}
          value={runtime.enabled}
          onChange={(enabled) =>
            change(enabled ? { enabled, required: runtime.required } : { enabled })
          }
          status={problemStatus(problem)}
        />
      )}
      {runtime.enabled && (
        <div className="grid gap-4 sm:grid-cols-2">
          {!fileType && (
            <Selector
              label={t("flow_runtime_input_format_label")}
              options={(["document", "audio", "file"] as const).map((value) => ({
                value,
                label: t(`flow_runtime_input_format_${value}`)
              }))}
              value={runtime.inputFormat}
              onChange={(value) => change({ inputFormat: value as RuntimeInputFormat })}
              width="100%"
            />
          )}
          <Switch
            label={t("flow_runtime_input_required")}
            description={t("flow_runtime_input_required_desc")}
            value={runtime.required}
            onChange={(required) => change({ required })}
          />
          <NumberInput
            label={t("flow_step_editor_uploads_max_files")}
            value={runtime.maxFiles}
            onChange={(value) => change({ maxFiles: value && value > 0 ? value : null })}
            min={1}
            isIntegerOnly
            hasClear
            isOptional
            placeholder={t("flow_step_editor_uploads_max_files_none")}
          />
          <TextInput
            label={t("flow_step_editor_uploads_label")}
            description={t("flow_step_editor_uploads_label_description")}
            value={runtime.label}
            onChange={(label) => change({ label })}
            isOptional
            autoComplete="off"
          />
          <TextInput
            label={t("flow_step_editor_uploads_description")}
            description={t("flow_step_editor_uploads_description_description")}
            value={runtime.description}
            onChange={(description) => change({ description })}
            isOptional
            autoComplete="off"
          />
          <UploadMimeTypes
            format={runtime.inputFormat}
            value={runtime.acceptedMimetypes}
            onChange={(acceptedMimetypes) => change({ acceptedMimetypes })}
          />
        </div>
      )}
      {fileType && <FieldMessage message={problem} />}
    </Anchor>
  );
}

function ReadingMode({
  formId,
  draft,
  onChange,
  problem
}: {
  formId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const mode = readTextProcessingMode(draft.input_config);
  const eligibility = textProcessingEligibility(draft);
  // Long material reads the whole input in its own way.
  const longMaterial = readLongMaterial(draft.input_config);
  if (mode === null && (eligibility !== "eligible" || draft.input_source === "http_get"))
    return null;
  return (
    <Anchor formId={formId} anchor="input_config.text_processing">
      <RadioList
        label={t("flow_reading_mode_title")}
        description={t("flow_reading_mode_description")}
        value={mode ?? WHOLE}
        onChange={(value) =>
          onChange({
            ...draft,
            input_config: withTextProcessingMode(
              draft.input_config,
              value === WHOLE ? null : (value as TextProcessingMode)
            )
          })
        }
        status={problemStatus(problem)}
      >
        <RadioListItem
          value={WHOLE}
          label={t("flow_reading_mode_whole")}
          description={t("flow_reading_mode_whole_desc")}
        />
        <RadioListItem
          value="process_each_section"
          label={t("flow_reading_mode_sections")}
          description={t("flow_reading_mode_sections_desc")}
          isDisabled={
            (eligibility !== "eligible" || longMaterial) && mode !== "process_each_section"
          }
        />
        <RadioListItem
          value="summarize"
          label={t("flow_reading_mode_summarize")}
          description={t("flow_reading_mode_summarize_desc")}
          isDisabled={(eligibility !== "eligible" || longMaterial) && mode !== "summarize"}
        />
      </RadioList>
      {eligibility !== "eligible" ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {eligibility === "mapped"
            ? t("flow_reading_mode_unavailable_mapped")
            : t("flow_reading_mode_unavailable_output")}
        </Text>
      ) : longMaterial ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_editor_tools_reading_mode_long_material")}
        </Text>
      ) : null}
    </Anchor>
  );
}

/**
 * Long material: input larger than the model reads at once is read in
 * parts. Offered only where the core accepts it; a stored setting the step
 * no longer allows stays visible with the reason, so it can be turned off.
 */
function LongMaterial({
  formId,
  draft,
  onChange,
  problem
}: {
  formId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const on = readLongMaterial(draft.input_config);
  const eligibility = longMaterialEligibility(draft);
  if (!on && eligibility !== "eligible") return null;
  const conflict =
    on && eligibility !== "eligible"
      ? t(`flow_editor_tools_long_material_conflict_${eligibility}`)
      : null;
  return (
    <Anchor formId={formId} anchor="input_config.long_material">
      <Switch
        label={t("flow_editor_tools_long_material")}
        description={t("flow_editor_tools_long_material_description")}
        value={on}
        onChange={(next) =>
          onChange({ ...draft, input_config: withLongMaterial(draft.input_config, next) })
        }
        status={problemStatus(problem ?? conflict)}
      />
    </Anchor>
  );
}

/**
 * The step's underlag: results of earlier steps it reads, and its own text
 * with references. Either replaces what the input source would give.
 */
function Underlag({
  formId,
  flow,
  draft,
  stepOrder,
  onChange,
  groups,
  problem
}: {
  formId: string;
  flow: FlowPublic;
  draft: StepConfig;
  stepOrder: number;
  onChange: (next: StepConfig) => void;
  groups: VariableGroup[];
  problem?: string;
}) {
  const t = useTranslations();
  const state = readInputBindings(draft.input_bindings);
  if (state.status !== "valid") {
    return (
      <Anchor formId={formId} anchor="input_bindings">
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_underlag_unsupported")}
        </Text>
        <FieldMessage message={problem} />
      </Anchor>
    );
  }
  const options = materialOptions(flow, stepOrder);
  const chosen = new Set(state.sourceRefs.map(sourceRefKey));
  const uploads = readRuntimeInput(draft.input_config).enabled;
  const replaces = state.question.trim() !== "" || state.sourceRefs.length > 0;
  // Results the step reads that are not offered here: a removed or later
  // step, or a field the earlier step no longer declares.
  const unlisted = state.sourceRefs.filter(
    (ref) => !options.some((option) => option.key === sourceRefKey(ref))
  );
  const missing = unlisted.filter((ref) => {
    const order = sourceRefStepOrder(ref);
    return order === null || order >= stepOrder;
  });

  function removeRef(ref: (typeof unlisted)[number]) {
    if (state.status !== "valid") return;
    onChange({
      ...draft,
      input_bindings: writeInputBindings(
        state.question,
        state.sourceRefs.filter((candidate) => candidate !== ref)
      )
    });
  }

  function refName(ref: (typeof unlisted)[number]): string {
    const order = sourceRefStepOrder(ref);
    const step = order === null ? null : flow.steps.find((item) => item.step_order === order);
    const source = order === null ? ref.stepRef : stepLabel(order, step?.user_description, t);
    return ref.fieldPath
      ? t("flow_step_editor_underlag_field", { step: source, field: ref.fieldPath })
      : source;
  }

  function setRefs(keys: string[]) {
    if (state.status !== "valid") return;
    const kept = state.sourceRefs.filter(
      (ref) =>
        keys.includes(sourceRefKey(ref)) ||
        !options.some((option) => option.key === sourceRefKey(ref))
    );
    const added = options
      .filter((option) => keys.includes(option.key) && !chosen.has(option.key))
      .map((option) => newSourceRef(option.stepOrder, option.output, option.fieldPath));
    onChange({ ...draft, input_bindings: writeInputBindings(state.question, [...kept, ...added]) });
  }

  return (
    <Anchor formId={formId} anchor="input_bindings">
      <div className="flex flex-col gap-1">
        <Text type="label" as="p" display="block" className="m-0">
          {t("flow_step_editor_underlag_title")}
        </Text>
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_underlag_description")}
        </Text>
      </div>
      {options.length > 0 && (
        <CheckboxList
          label={t("flow_step_editor_underlag_results")}
          description={t("flow_step_editor_underlag_results_description")}
          value={options.filter((option) => chosen.has(option.key)).map((option) => option.key)}
          onChange={setRefs}
          density="compact"
        >
          {options.map((option) => (
            <CheckboxListItem
              key={option.key}
              value={option.key}
              label={
                option.fieldPath
                  ? t("flow_step_editor_underlag_field", {
                      step: stepLabel(option.stepOrder, option.stepName, t),
                      field: option.fieldPath
                    })
                  : stepLabel(option.stepOrder, option.stepName, t)
              }
              description={
                option.output === "structured" && !option.fieldPath
                  ? t("flow_step_editor_underlag_whole_structured")
                  : undefined
              }
            />
          ))}
        </CheckboxList>
      )}
      {missing.length > 0 && (
        <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
          {t("flow_step_editor_underlag_missing_step")}
        </Text>
      )}
      {unlisted.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {unlisted.map((ref) => (
            <li key={sourceRefKey(ref)} className="flex flex-wrap items-center gap-2">
              <Text type="body" size="sm">
                {refName(ref)}
              </Text>
              <Button
                label={t("flow_step_editor_underlag_remove_ref", { name: refName(ref) })}
                variant="ghost"
                size="sm"
                icon={<Trash2 className="size-4" aria-hidden="true" />}
                onClick={() => removeRef(ref)}
              />
            </li>
          ))}
        </ul>
      )}
      <TemplateTextArea
        label={t("flow_step_editor_underlag_text")}
        description={
          uploads
            ? t("flow_step_editor_underlag_text_uploads")
            : t("flow_step_editor_underlag_text_description")
        }
        value={state.question}
        onChange={(question) =>
          onChange({ ...draft, input_bindings: writeInputBindings(question, state.sourceRefs) })
        }
        groups={groups}
        rows={4}
        isOptional
        status={problemStatus(problem)}
      />
      {replaces && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_underlag_replaces")}
        </Text>
      )}
    </Anchor>
  );
}

/** What the step reads: its source, the type, and the source's own settings. */
export function StepInputSection({
  formId,
  sectionId,
  flow,
  stepId,
  stepOrder,
  draft,
  onChange,
  problems,
  groups,
  toolGroups,
  showUnderlag
}: {
  formId: string;
  sectionId: string;
  flow: FlowPublic;
  stepId: string;
  stepOrder: number;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
  groups: VariableGroup[];
  toolGroups: VariableGroup[];
  showUnderlag: boolean;
}) {
  const t = useTranslations();
  const previous = stepsBefore(flow, stepOrder).at(-1) ?? null;
  const previousOutput: OutputType | null = previous?.output_type ?? null;
  const sourceOptions = inputSourceOptions(stepOrder, draft.input_source);
  const typeOptions = inputTypeOptions(draft, previousOutput);
  const issue = chainIssue(draft, stepOrder, previousOutput);
  const sourceIssue =
    issue === "flow_input_not_first" || issue === "previous_on_first"
      ? chainIssueText(issue, t)
      : null;
  const typeIssue = issue && !sourceIssue ? chainIssueText(issue, t) : null;
  const audio = draft.input_type === "audio";

  return (
    <EditorSection
      id={sectionId}
      title={t("flow_step_editor_input_title")}
      description={t("flow_step_editor_input_description")}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Anchor formId={formId} anchor="input_source">
          <Selector
            label={t("flow_step_editor_input_source")}
            options={sourceOptions.map((option) => ({
              value: option.value,
              label: option.invalid
                ? invalidOptionLabel(inputSourceLabel(option.value, t), t)
                : inputSourceLabel(option.value, t)
            }))}
            value={draft.input_source}
            onChange={(value) =>
              onChange(applyInputSourceChange(draft, value as InputSource, previousOutput))
            }
            status={problemStatus(problems.input_source ?? sourceIssue)}
            width="100%"
          />
        </Anchor>
        <Anchor formId={formId} anchor="input_type">
          <Selector
            label={t("flow_step_input_type")}
            description={
              draft.input_source === "tool" ? t("flow_step_input_type_tool_desc") : undefined
            }
            options={typeOptions.map((option) => ({
              value: option.value,
              label: option.invalid
                ? invalidOptionLabel(inputTypeLabel(option.value, t), t)
                : inputTypeLabel(option.value, t)
            }))}
            value={draft.input_type}
            onChange={(value) => onChange(applyInputTypeChange(draft, value as InputType))}
            status={problemStatus(problems.input_type ?? typeIssue)}
            width="100%"
          />
        </Anchor>
      </div>

      {draft.input_source === "previous_step" && previous && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_reads_previous", {
            step: stepLabel(previous.step_order, previous.user_description, t)
          })}
        </Text>
      )}
      {draft.input_source === "all_previous_steps" && stepOrder > 1 && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_reads_all_previous")}
        </Text>
      )}

      {audio && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {transcriptionEnabled(flow.metadata_json)
            ? t("flow_step_editor_transcription_flow_settings")
            : t("flow_step_editor_transcription_turned_on")}
        </Text>
      )}

      {draft.input_source === "flow_input" && (
        <Uploads
          formId={formId}
          draft={draft}
          onChange={onChange}
          problem={problems["input_config.runtime_input"]}
        />
      )}

      {draft.input_source === "http_get" && (
        <Anchor formId={formId} anchor="input_config.http">
          <HttpFields
            flowId={flow.id}
            stepId={stepId}
            direction="input"
            config={readHttpConfig(draft.input_config, "input")}
            onChange={(http) =>
              onChange({ ...draft, input_config: withHttpConfig(draft.input_config, http) })
            }
            groups={toolGroups}
            problem={problems["input_config.http"]}
          />
        </Anchor>
      )}

      {draft.input_source === "tool" && (
        <Anchor formId={formId} anchor="input_config.tool">
          <ToolFields
            flowId={flow.id}
            tool={readToolConfig(draft.input_config)}
            onChange={(tool) =>
              onChange({ ...draft, input_config: withToolConfig(draft.input_config, tool) })
            }
            groups={toolGroups}
            problem={problems["input_config.tool"]}
          />
        </Anchor>
      )}

      {draft.output_mode !== "transcribe_only" && (
        <ReadingMode
          formId={formId}
          draft={draft}
          onChange={onChange}
          problem={problems["input_config.text_processing"]}
        />
      )}

      <LongMaterial
        formId={formId}
        draft={draft}
        onChange={onChange}
        problem={problems["input_config.long_material"]}
      />

      {showUnderlag && draft.input_source !== "http_get" && draft.input_source !== "tool" && (
        <Underlag
          formId={formId}
          flow={flow}
          draft={draft}
          stepOrder={stepOrder}
          onChange={onChange}
          groups={groups}
          problem={problems.input_bindings}
        />
      )}
    </EditorSection>
  );
}

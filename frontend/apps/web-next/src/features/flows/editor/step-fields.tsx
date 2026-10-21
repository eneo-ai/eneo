"use client";

import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "next-intl";
import { TextInput } from "@/components/astryx/text-input";
import {
  kwargCapability,
  modelKwargLabel,
  modelKwargOptionLabel,
  modelSpecificKwargs,
  supportsKwarg,
  type ModelKwargName,
  type ModelKwargs,
  type ModelWithKwargs
} from "@/features/assistants/editor/model-kwargs";
import { useSpace } from "@/features/spaces/use-space";
import { formFieldsOf, stepsOf, type FlowDefinition, type FlowStep } from "../types";
import type { DraftField, JsonText } from "./use-step-draft";

export type FieldProblems = Partial<Record<DraftField, string>>;

/** The status Astryx fields take for a problem the validator or the form found. */
export const problemStatus = (problem: string | undefined) =>
  problem ? ({ type: "error", message: problem } as const) : undefined;

/** The value the "space default" option of a model selector carries. */
export const DEFAULT_MODEL = "";

/** Name and description, the fields every step has. */
export function NameFields({
  step,
  onChange,
  problems
}: {
  step: FlowStep;
  onChange: (patch: Partial<FlowStep>) => void;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  return (
    <div className="grid gap-4 sm:grid-cols-2 sm:items-end">
      <TextInput
        label={t("name")}
        value={step.name}
        onChange={(name) => onChange({ name })}
        isRequired
        status={problemStatus(problems.name)}
        placeholder={t("flow_editor_name_placeholder")}
      />
      <TextInput
        label={t("flow_editor_description")}
        description={t("flow_editor_description_hint")}
        value={step.description ?? ""}
        onChange={(description) => onChange({ description: description || null })}
        status={problemStatus(problems.description)}
        placeholder={t("flow_editor_description_placeholder")}
      />
    </div>
  );
}

/** How templates refer to inputs and earlier steps, with this flow's own keys as the example. */
export function TemplateHint({
  definition,
  stepKey
}: {
  definition: FlowDefinition;
  stepKey: string | null;
}) {
  const t = useTranslations();
  const field = formFieldsOf(definition)[0]?.key ?? "key";
  const steps = stepsOf(definition);
  const at = stepKey ? steps.findIndex((step) => step.key === stepKey) : steps.length;
  const earlier = (at > 0 ? steps[at - 1] : null)?.key ?? "steg";
  return (
    <Text type="supporting" size="xsm" as="p" display="block" className="m-0 leading-snug">
      {t("flow_editor_template_hint", { form: `{{form.${field}}}`, step: `{{steps.${earlier}}}` })}
    </Text>
  );
}

/** A JSON object edited as text: the schema of an output, a tool's arguments. */
export function JsonTextField({
  label,
  description,
  json,
  onChange,
  problem,
  rows = 10
}: {
  label: string;
  description?: string;
  json: JsonText;
  onChange: (text: string) => void;
  problem?: string;
  rows?: number;
}) {
  const t = useTranslations();
  const message =
    problem ??
    (json.error === "invalid"
      ? t("flow_editor_json_invalid")
      : json.error === "not_object"
        ? t("flow_editor_json_not_object")
        : json.error === "empty"
          ? t("flow_editor_json_empty")
          : undefined);
  return (
    <TextArea
      label={label}
      description={description}
      value={json.text}
      onChange={onChange}
      rows={rows}
      hasSpellCheck={false}
      status={problemStatus(message)}
      className="font-mono"
    />
  );
}

/** The file and audio inputs a step is handed, as a checkbox list. */
export function FilesFromField({
  definition,
  value,
  onChange,
  problem
}: {
  definition: FlowDefinition;
  value: string[];
  onChange: (keys: string[]) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const files = formFieldsOf(definition).filter(
    (field) => field.type === "file" || field.type === "audio"
  );
  if (files.length === 0) {
    return (
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flow_editor_files_none")}
      </Text>
    );
  }
  return (
    <CheckboxList
      label={t("flow_param_files")}
      description={t("flow_editor_files_hint")}
      value={value}
      onChange={onChange}
      density="compact"
      status={problemStatus(problem)}
    >
      {files.map((field) => (
        <CheckboxListItem
          key={field.key}
          value={field.key}
          label={field.label}
          description={
            field.type === "audio" ? t("flow_field_type_audio") : t("flow_field_type_file")
          }
        />
      ))}
    </CheckboxList>
  );
}

/** The input a step reads, chosen among the run inputs of the given types. */
export function FormFieldSelector({
  label,
  definition,
  types,
  value,
  onChange,
  problem,
  optional = false,
  description
}: {
  label: string;
  definition: FlowDefinition;
  types: readonly string[];
  value: string | null;
  onChange: (key: string | null) => void;
  problem?: string;
  optional?: boolean;
  description?: string;
}) {
  const t = useTranslations();
  const fields = formFieldsOf(definition).filter((field) => types.includes(field.type));
  const options = fields.map((field) => ({ value: field.key, label: field.label }));
  const status = problemStatus(problem);
  const placeholder = fields.length === 0 ? t("flow_editor_no_matching_input") : t("select");
  if (optional) {
    return (
      <Selector
        label={label}
        description={description}
        options={options}
        value={value}
        onChange={(next: string | null) => onChange(next || null)}
        placeholder={placeholder}
        hasClear
        isOptional
        isDisabled={fields.length === 0}
        status={status}
      />
    );
  }
  return (
    <Selector
      label={label}
      description={description}
      options={options}
      value={value ?? undefined}
      onChange={(next) => onChange(next || null)}
      placeholder={placeholder}
      isRequired
      isDisabled={fields.length === 0}
      status={status}
    />
  );
}

/** An earlier step, chosen by name (a review's target). */
export function EarlierStepSelector({
  label,
  definition,
  before,
  value,
  onChange,
  problem,
  description
}: {
  label: string;
  definition: FlowDefinition;
  /** Only steps before this position are offered. */
  before: number;
  value: string | null;
  onChange: (key: string | null) => void;
  problem?: string;
  description?: string;
}) {
  const t = useTranslations();
  const steps = stepsOf(definition)
    .slice(0, Math.max(0, before))
    .filter((step) => step.kind !== "review");
  return (
    <Selector
      label={label}
      description={description}
      options={[
        { value: DEFAULT_MODEL, label: t("flow_editor_previous_step") },
        ...steps.map((step, index) => ({
          value: step.key,
          label: `${t("flow_ref_step", { index: index + 1 })} · ${step.name}`
        }))
      ]}
      value={value ?? DEFAULT_MODEL}
      onChange={(next) => onChange(next || null)}
      status={problemStatus(problem)}
    />
  );
}

/** The completion model of a model step, with the space default as the first choice. */
export function ModelSelector({
  value,
  onChange,
  problem
}: {
  value: string | null;
  onChange: (id: string | null) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  return (
    <Selector
      label={t("model")}
      options={[
        {
          value: DEFAULT_MODEL,
          label: t("flow_param_model_default"),
          description: t("flow_model_default_detail")
        },
        ...space.completion_models.map((model) => ({
          value: model.id,
          label: model.nickname || model.name
        }))
      ]}
      value={value ?? DEFAULT_MODEL}
      onChange={(next) => onChange(next || null)}
      hasSearch={space.completion_models.length > 8}
      status={problemStatus(problem)}
    />
  );
}

/** The model settings a model supports: temperature, then its own (reasoning effort, top_p, …). */
export function ModelKwargsFields({
  modelId,
  value,
  onChange
}: {
  modelId: string | null;
  value: ModelKwargs;
  onChange: (kwargs: ModelKwargs) => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const model: ModelWithKwargs | null =
    (modelId && space.completion_models.find((candidate) => candidate.id === modelId)) || null;
  // Without a chosen model the space default decides at run time; offer temperature only.
  const names: ModelKwargName[] = model
    ? [
        ...(supportsKwarg(model, "temperature") ? (["temperature"] as const) : []),
        ...modelSpecificKwargs(model)
      ]
    : ["temperature"];
  const set = (name: ModelKwargName, next: number | string | null) => {
    const kwargs: ModelKwargs = { ...value };
    if (next === null || next === "") delete kwargs[name];
    else (kwargs as Record<string, unknown>)[name] = next;
    onChange(kwargs);
  };
  if (names.length === 0) return null;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {names.map((name) => {
        const capability = kwargCapability(model, name);
        const current = value[name] ?? null;
        if (capability?.control === "select" && capability.options?.length) {
          return (
            <Selector
              key={name}
              label={modelKwargLabel(name, t)}
              options={[
                { value: DEFAULT_MODEL, label: t("flow_model_settings_default") },
                ...capability.options.map((option) => ({
                  value: option,
                  label: modelKwargOptionLabel(option, t)
                }))
              ]}
              value={typeof current === "string" ? current : DEFAULT_MODEL}
              onChange={(next) => set(name, next || null)}
            />
          );
        }
        return (
          <NumberInput
            key={name}
            label={modelKwargLabel(name, t)}
            value={typeof current === "number" ? current : null}
            onChange={(next) => set(name, next)}
            min={capability?.minimum ?? (name === "temperature" ? 0 : null)}
            max={capability?.maximum ?? (name === "temperature" ? 2 : null)}
            step={capability?.step ?? (name === "temperature" ? 0.1 : 1)}
            placeholder={t("flow_model_settings_default")}
            hasClear
          />
        );
      })}
    </div>
  );
}

"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Selector } from "@astryxdesign/core/Selector";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
import type { FlowDefinitionUpdate, FlowPublic } from "./flows-api";
import {
  evidenceExportAllowed,
  FORM_FIELD_TYPES,
  formFieldProblems,
  formFieldsOf,
  hasOptions,
  metadataWithSettings,
  renamedFormFields,
  suggestedFieldName,
  type FormFieldDraft,
  type FormFieldProblem,
  type FormFieldType
} from "./flow-form-fields";
import {
  flowTakesAudio,
  metadataWithTranscription,
  speakersRequired,
  transcriptionModelMissing,
  transcriptionSettingsOf,
  type TranscriptionSettings
} from "./flow-transcription";
import {
  TranscriptionFields,
  TranscriptionSummary,
  type TranscriptionResources
} from "./flow-transcription-settings";

const TYPE_KEYS: Record<FormFieldType, string> = {
  text: "flows_field_type_text",
  number: "flows_field_type_number",
  date: "flows_field_type_date",
  select: "flows_field_type_select",
  multiselect: "flows_field_type_multiselect",
  list: "flows_field_type_list"
};

const PROBLEM_KEYS: Record<FormFieldProblem["problem"], string> = {
  required: "flows_field_problem_required",
  duplicate: "flows_field_problem_duplicate",
  namespace_head: "flows_field_problem_reserved",
  reserved: "flows_field_problem_reserved",
  step_alias: "flows_field_problem_step_alias",
  dot: "flows_field_problem_dot",
  options_required: "flows_field_problem_options"
};

/** Whether the flow shows transcription settings: it takes audio, or has them turned on. */
function showsTranscription(flow: FlowPublic): boolean {
  return flowTakesAudio(flow.steps) || transcriptionSettingsOf(flow.metadata_json).enabled;
}

/**
 * The read view: what a run asks for, how its audio is transcribed and
 * whether its evidence may be exported.
 */
function SettingsSummary({
  flow,
  transcription
}: {
  flow: FlowPublic;
  transcription: TranscriptionResources;
}) {
  const t = useTranslations();
  const fields = formFieldsOf(flow.metadata_json);
  const settings = transcriptionSettingsOf(flow.metadata_json);
  return (
    <MetadataList label={{ position: "start", width: "11rem" }}>
      <MetadataListItem label={t("name")}>{flow.name}</MetadataListItem>
      <MetadataListItem label={t("description")}>
        {flow.description?.trim() || (
          <span className="text-ax-text-secondary">{t("flows_no_description")}</span>
        )}
      </MetadataListItem>
      <MetadataListItem label={t("flows_form_heading")}>
        {fields.length === 0 ? (
          <span className="text-ax-text-secondary">{t("flows_form_empty")}</span>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {fields.map((field) => (
              <li key={field.key}>
                {t(
                  field.required ? "flows_form_field_summary_required" : "flows_form_field_summary",
                  {
                    label: field.label,
                    type: t(TYPE_KEYS[field.type])
                  }
                )}
              </li>
            ))}
          </ul>
        )}
      </MetadataListItem>
      {showsTranscription(flow) ? (
        <TranscriptionSummary
          settings={settings}
          resources={transcription}
          required={speakersRequired(flow.steps)}
          modelMissing={transcriptionModelMissing(settings, flow.steps)}
        />
      ) : null}
      <MetadataListItem label={t("flows_evidence_export")}>
        {evidenceExportAllowed(flow.metadata_json)
          ? t("flows_evidence_export_allowed")
          : t("flows_evidence_export_not_allowed")}
      </MetadataListItem>
    </MetadataList>
  );
}

function FormFieldRow({
  field,
  index,
  problems,
  onChange,
  onRemove,
  existingNames
}: {
  field: FormFieldDraft;
  index: number;
  problems: readonly FormFieldProblem[];
  onChange: (field: FormFieldDraft) => void;
  onRemove: () => void;
  existingNames: readonly string[];
}) {
  const t = useTranslations();
  const legendId = useId();
  const nameProblem = problems.find((problem) => problem.part === "name");
  const optionsProblem = problems.find((problem) => problem.part === "options");
  const title = field.label.trim() || t("flows_form_field_number", { number: index + 1 });

  return (
    <div
      role="group"
      aria-labelledby={legendId}
      className="border-ax-border rounded-ax-container flex flex-col gap-3 border p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <span id={legendId} className="text-ax-text text-sm font-semibold break-words">
          {title}
        </span>
        <IconButton
          label={t("flows_form_field_remove", { field: title })}
          icon={<Trash2 aria-hidden="true" />}
          variant="ghost"
          size="sm"
          onClick={onRemove}
        />
      </div>
      <TextInput
        label={t("flows_form_field_label")}
        value={field.label}
        onChange={(label) =>
          onChange({
            ...field,
            label,
            name: field.nameEdited ? field.name : suggestedFieldName(label, existingNames)
          })
        }
        autoComplete="off"
      />
      <TextInput
        label={t("flows_form_field_name")}
        description={t("flows_form_field_name_hint", {
          token: `{{flow_input.${field.name.trim() || "…"}}}`
        })}
        value={field.name}
        onChange={(name) => onChange({ ...field, name, nameEdited: true })}
        isRequired
        autoComplete="off"
        status={
          nameProblem ? { type: "error", message: t(PROBLEM_KEYS[nameProblem.problem]) } : undefined
        }
      />
      <Selector
        label={t("flows_form_field_type")}
        value={field.type}
        onChange={(type) => onChange({ ...field, type: type as FormFieldType })}
        options={FORM_FIELD_TYPES.map((type) => ({ value: type, label: t(TYPE_KEYS[type]) }))}
      />
      {hasOptions(field.type) ? (
        <TextArea
          label={t("flows_form_field_options")}
          description={t("flows_form_field_options_hint")}
          value={field.options.join("\n")}
          onChange={(text) => onChange({ ...field, options: text.split("\n") })}
          rows={3}
          isRequired
          status={
            optionsProblem
              ? { type: "error", message: t(PROBLEM_KEYS[optionsProblem.problem]) }
              : undefined
          }
        />
      ) : null}
      <CheckboxInput
        label={t("flows_form_field_required")}
        value={field.required}
        onChange={(required) => onChange({ ...field, required })}
      />
    </div>
  );
}

/**
 * The flow's settings: its name, description, the run form people fill in
 * when they start a run, how audio is transcribed (for a flow that takes
 * audio) and whether run evidence may be exported. Shown as facts; editors
 * change them in a form that saves them as one revision.
 */
export function FlowSettings({
  flow,
  canEdit,
  transcription,
  onSave
}: {
  flow: FlowPublic;
  canEdit: boolean;
  /** The space's transcription models and services. */
  transcription: TranscriptionResources;
  /** Saves the definition change; resolves true when it was saved. */
  onSave: (definition: FlowDefinitionUpdate) => Promise<boolean>;
}) {
  const t = useTranslations();
  const headingId = useId();
  const formId = useId();
  const formRef = useRef<HTMLFormElement>(null);
  const editButtonRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<FormFieldDraft[]>([]);
  const [savedFields, setSavedFields] = useState<FormFieldDraft[]>([]);
  const [allowExport, setAllowExport] = useState(false);
  const [showProblems, setShowProblems] = useState(false);
  const [transcriptionDraft, setTranscriptionDraft] = useState<TranscriptionSettings>(() =>
    transcriptionSettingsOf(flow.metadata_json)
  );
  const [maxSpeakersInvalid, setMaxSpeakersInvalid] = useState(false);
  const nextKey = useRef(0);

  const problems = formFieldProblems(fields);
  const nameMissing = !name.trim();
  const takesAudio = flowTakesAudio(flow.steps);

  function startEditing() {
    setName(flow.name);
    setDescription(flow.description ?? "");
    const saved = formFieldsOf(flow.metadata_json);
    setSavedFields(saved);
    setFields(saved);
    setAllowExport(evidenceExportAllowed(flow.metadata_json));
    setTranscriptionDraft(transcriptionSettingsOf(flow.metadata_json));
    setMaxSpeakersInvalid(false);
    setShowProblems(false);
    setEditing(true);
  }

  function stopEditing() {
    setEditing(false);
    // The form is gone; its "Ändra" button takes focus back.
    requestAnimationFrame(() => editButtonRef.current?.querySelector("button")?.focus());
  }

  function addField() {
    nextKey.current += 1;
    setFields((current) => [
      ...current,
      {
        key: `new-${nextKey.current}`,
        name: "",
        label: "",
        type: "text",
        required: false,
        options: [],
        nameEdited: false
      }
    ]);
  }

  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (nameMissing || problems.length > 0 || maxSpeakersInvalid) {
      // Rendered before focus moves, so the first field is read with its error.
      flushSync(() => setShowProblems(true));
      formRef.current
        ?.querySelector<HTMLElement>('[aria-invalid="true"], [data-invalid] input')
        ?.focus();
      return;
    }
    setSaving(true);
    const renames = renamedFormFields(savedFields, fields);
    const saved = await onSave({
      name: name.trim(),
      description: description.trim() || null,
      metadata_json: metadataWithTranscription(
        metadataWithSettings(flow.metadata_json, fields, allowExport),
        transcriptionSettingsOf(flow.metadata_json),
        transcriptionDraft,
        { takesAudio }
      ),
      ...(Object.keys(renames).length > 0 ? { form_field_renames: renames } : {})
    });
    setSaving(false);
    if (saved) stopEditing();
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Heading level={2} id={headingId} weight="semibold" className="text-lg">
          {t("flows_settings_heading")}
        </Heading>
        {canEdit && !editing ? (
          <div ref={editButtonRef}>
            <Button label={t("flows_settings_edit")} size="sm" onClick={startEditing} />
          </div>
        ) : null}
      </div>
      {!editing ? (
        <SettingsSummary flow={flow} transcription={transcription} />
      ) : (
        <form
          id={formId}
          ref={formRef}
          onSubmit={submit}
          noValidate
          className="border-ax-border bg-ax-card rounded-ax-container flex flex-col gap-4 border p-4"
        >
          <TextInput
            label={t("name")}
            value={name}
            onChange={setName}
            isRequired
            autoComplete="off"
            status={
              showProblems && nameMissing
                ? { type: "error", message: t("flows_new_name_required") }
                : undefined
            }
          />
          <TextArea
            label={t("description")}
            value={description}
            onChange={setDescription}
            rows={3}
          />
          <fieldset className="flex flex-col gap-3">
            <legend className="text-ax-text mb-1 text-sm font-semibold">
              {t("flows_form_heading")}
            </legend>
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flows_form_description")}
            </Text>
            {fields.map((field, index) => (
              <FormFieldRow
                key={field.key}
                field={field}
                index={index}
                problems={
                  showProblems ? problems.filter((problem) => problem.key === field.key) : []
                }
                existingNames={fields
                  .filter((other) => other.key !== field.key)
                  .map((other) => other.name)}
                onChange={(next) =>
                  setFields((current) =>
                    current.map((candidate) => (candidate.key === next.key ? next : candidate))
                  )
                }
                onRemove={() => {
                  setFields((current) =>
                    current.filter((candidate) => candidate.key !== field.key)
                  );
                  // The row is gone; the add button keeps focus in the form.
                  requestAnimationFrame(() =>
                    formRef.current?.querySelector<HTMLElement>("[data-add-field] button")?.focus()
                  );
                }}
              />
            ))}
            <div data-add-field>
              <Button
                label={t("flows_form_add_field")}
                icon={<Plus aria-hidden="true" />}
                size="sm"
                onClick={addField}
              />
            </div>
          </fieldset>
          {showsTranscription(flow) ? (
            <TranscriptionFields
              settings={transcriptionDraft}
              resources={transcription}
              takesAudio={takesAudio}
              required={speakersRequired(flow.steps)}
              modelMissing={transcriptionModelMissing(transcriptionDraft, flow.steps)}
              maxSpeakersProblem={maxSpeakersInvalid}
              onChange={setTranscriptionDraft}
              onMaxSpeakersInvalid={setMaxSpeakersInvalid}
            />
          ) : null}
          <CheckboxInput
            label={t("flows_evidence_export_allow")}
            description={t("flows_evidence_export_hint")}
            value={allowExport}
            onChange={setAllowExport}
          />
          <div className="flex flex-wrap justify-end gap-2">
            <Button label={t("cancel")} onClick={stopEditing} />
            <Button
              type="submit"
              variant="primary"
              label={t("flows_settings_save")}
              isLoading={saving}
              isInterruptible
            />
          </div>
        </form>
      )}
    </section>
  );
}

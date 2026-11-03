import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Selector } from "@astryxdesign/core/Selector";
import { Switch } from "@astryxdesign/core/Switch";
import { Heading, Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { ArrowDown, ArrowUp, CircleCheck, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useEffectEvent, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@/components/astryx/text-input";
import { EmptyState } from "@/components/composites/empty-state";
import { LeaveConfirmation } from "@/components/composites/leave-confirmation";
import type { FlowDefinitionUpdate, FlowPublic } from "./flows-api";
import {
  evidenceExportAllowed,
  FORM_FIELD_TYPES,
  formFieldProblems,
  formFieldsOf,
  hasOptions,
  metadataWithSettings,
  persistedFormFields,
  renamedFormFields,
  roleFor,
  suggestedFieldName,
  withFieldChanged,
  withFieldMoved,
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

/** The field a page can ask the form to focus. */
type RequestedField = "name" | "transcription_model" | "speaker_service";

type SettingsOpenRequest = { nonce: number; focus?: RequestedField };

/** Requests already answered, by object: the section remounts when a step closes. */
const answeredRequests = new WeakSet<SettingsOpenRequest>();

/** The form's values. */
type SettingsDraft = {
  name: string;
  description: string;
  fields: FormFieldDraft[];
  allowExport: boolean;
  transcription: TranscriptionSettings;
};

function draftOf(flow: FlowPublic): SettingsDraft {
  return {
    name: flow.name,
    description: flow.description ?? "",
    fields: formFieldsOf(flow.metadata_json),
    allowExport: evidenceExportAllowed(flow.metadata_json),
    transcription: transcriptionSettingsOf(flow.metadata_json)
  };
}

/** What a draft saves, to compare by: a row's key or a space the save trims is no change. */
function savedValues(draft: SettingsDraft): string {
  return JSON.stringify({
    ...draft,
    name: draft.name.trim(),
    description: draft.description.trim(),
    fields: persistedFormFields(draft.fields)
  });
}

/**
 * The read view: the flow at a glance, what a run asks for, how its audio is
 * transcribed and whether its evidence may be downloaded. Without
 * `transcription` (a page that has not read the space) it says only whether
 * the flow transcribes.
 */
export function SettingsSummary({
  flow,
  transcription,
  stepCount,
  problemCount
}: {
  flow: FlowPublic;
  transcription?: TranscriptionResources;
  stepCount?: number;
  /** The draft check's problem count; null while unchecked. */
  problemCount?: number | null;
}) {
  const t = useTranslations();
  const fields = formFieldsOf(flow.metadata_json);
  const settings = transcriptionSettingsOf(flow.metadata_json);
  const transcribes = flowTakesAudio(flow.steps) || settings.enabled;
  return (
    <MetadataList label={{ position: "start", width: "11rem" }}>
      <MetadataListItem label={t("name")}>{flow.name}</MetadataListItem>
      <MetadataListItem label={t("description")}>
        {flow.description?.trim() || (
          <span className="text-ax-text-secondary">{t("flows_no_description")}</span>
        )}
      </MetadataListItem>
      <MetadataListItem label={t("flows_settings_steps")}>
        {stepCount ?? flow.steps.length}
      </MetadataListItem>
      <MetadataListItem label={t("flows_settings_form_fields")}>
        {fields.length}
        {fields.length > 0 ? (
          <ul className="text-ax-text-secondary mt-0.5 flex flex-col gap-0.5">
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
        ) : null}
      </MetadataListItem>
      <MetadataListItem label={t("flow_editor_tools_transcription_heading")}>
        {t(transcribes ? "flow_editor_tools_on" : "flow_editor_tools_off")}
      </MetadataListItem>
      {transcribes && transcription ? (
        <TranscriptionSummary
          settings={settings}
          resources={transcription}
          required={speakersRequired(flow.steps)}
          modelMissing={transcriptionModelMissing(settings, flow.steps)}
        />
      ) : null}
      <MetadataListItem label={t("flows_evidence_export")}>
        {t(
          evidenceExportAllowed(flow.metadata_json)
            ? "flow_editor_tools_on"
            : "flow_editor_tools_off"
        )}
      </MetadataListItem>
      {problemCount == null ? null : (
        <MetadataListItem label={t("flows_settings_check")}>
          {problemCount === 0 ? (
            <span className="inline-flex items-center gap-1.5">
              <CircleCheck className="text-ax-success size-4 shrink-0" aria-hidden="true" />
              {t("flows_settings_check_ok")}
            </span>
          ) : (
            t("flows_settings_check_problems", { count: problemCount })
          )}
        </MetadataListItem>
      )}
    </MetadataList>
  );
}

function FormFieldRow({
  field,
  title,
  isFirst,
  isLast,
  moveId,
  problems,
  onChange,
  onMove,
  onRemove,
  existingNames
}: {
  field: FormFieldDraft;
  /** The field's label, or "Fält 2" until it has one. */
  title: string;
  isFirst: boolean;
  isLast: boolean;
  /** The id of the field's move button in that direction. */
  moveId: (direction: "up" | "down") => string;
  problems: readonly FormFieldProblem[];
  onChange: (field: FormFieldDraft) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  existingNames: readonly string[];
}) {
  const t = useTranslations();
  const legendId = useId();
  const nameProblem = problems.find((problem) => problem.part === "name");
  const optionsProblem = problems.find((problem) => problem.part === "options");
  const role = roleFor(field.type);

  return (
    <div
      role="group"
      aria-labelledby={legendId}
      className="border-ax-border rounded-ax-container flex flex-col gap-3 border p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <span id={legendId} className="text-ax-text min-w-0 text-sm font-semibold break-words">
          {title}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            id={moveId("up")}
            label={t("flows_step_move_up", { step: title })}
            icon={<ArrowUp aria-hidden="true" />}
            variant="ghost"
            size="sm"
            isDisabled={isFirst}
            onClick={() => onMove(-1)}
          />
          <IconButton
            id={moveId("down")}
            label={t("flows_step_move_down", { step: title })}
            icon={<ArrowDown aria-hidden="true" />}
            variant="ghost"
            size="sm"
            isDisabled={isLast}
            onClick={() => onMove(1)}
          />
          <IconButton
            label={t("flows_form_field_remove", { field: title })}
            icon={<Trash2 aria-hidden="true" />}
            variant="ghost"
            size="sm"
            onClick={onRemove}
          />
        </div>
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
      {role ? (
        <CheckboxInput
          label={t(
            role === "run_label"
              ? "flows_form_field_role_run_label"
              : "flows_form_field_role_run_date"
          )}
          description={t(
            role === "run_label"
              ? "flows_form_field_role_run_label_hint"
              : "flows_form_field_role_run_date_hint"
          )}
          value={field.role === role}
          onChange={(on) => onChange({ ...field, role: on ? role : undefined })}
        />
      ) : null}
    </div>
  );
}

/**
 * The flow's settings: its name, description, the run form people fill in
 * when they start a run, how audio is transcribed and whether run evidence
 * may be downloaded. Shown as facts; editors change them in a form that saves
 * them as one revision. The form saves only what it was loaded from: settings
 * changed meanwhile (the chat, another tab) are never overwritten, the form
 * says so and offers them instead.
 */
export function FlowSettings({
  flow,
  canEdit,
  transcription,
  onSave,
  onEditingChange,
  openRequest,
  stepCount,
  problemCount,
  onDirtyChange
}: {
  flow: FlowPublic;
  canEdit: boolean;
  /** The space's transcription models and services. */
  transcription: TranscriptionResources;
  /** Saves the definition change; resolves true when it was saved. */
  onSave: (definition: FlowDefinitionUpdate) => Promise<boolean>;
  /** Told true while the form is open (its edits are not saved), and false once it closes. */
  onEditingChange?: (editing: boolean) => void;
  /**
   * Opens the form (if closed), scrolls to the named field and focuses it. A
   * new object asks again.
   */
  openRequest?: SettingsOpenRequest;
  /** Shown in the read view. */
  stepCount?: number;
  /** The draft check's problem count (null while unchecked), shown in the read view. */
  problemCount?: number | null;
  /** Told true while the open form differs from the flow it was loaded from. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const headingId = useId();
  const formId = useId();
  const sectionRef = useRef<HTMLElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const editButtonRef = useRef<HTMLDivElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<FormFieldDraft[]>([]);
  const [allowExport, setAllowExport] = useState(false);
  const [showProblems, setShowProblems] = useState(false);
  const [transcriptionDraft, setTranscriptionDraft] = useState<TranscriptionSettings>(() =>
    transcriptionSettingsOf(flow.metadata_json)
  );
  const [maxSpeakersInvalid, setMaxSpeakersInvalid] = useState(false);
  // What the form was loaded from.
  const [loaded, setLoaded] = useState(() => draftOf(flow));
  const nextKey = useRef(0);

  const problems = formFieldProblems(fields);
  const nameMissing = !name.trim();
  const takesAudio = flowTakesAudio(flow.steps);
  const loadedValues = savedValues(loaded);
  const dirty =
    editing &&
    (maxSpeakersInvalid ||
      savedValues({
        name,
        description,
        fields,
        allowExport,
        transcription: transcriptionDraft
      }) !== loadedValues);
  // The settings changed since the form loaded them; a revision that left them
  // alone (a moved step) is no reason, and the form's own save closes it.
  const stale = editing && !saving && savedValues(draftOf(flow)) !== loadedValues;

  useEffect(() => {
    if (!editing) return;
    onEditingChange?.(true);
    return () => onEditingChange?.(false);
  }, [editing, onEditingChange]);

  useEffect(() => {
    if (!dirty) return;
    onDirtyChange?.(true);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (stale) announce(t("flows_settings_stale_title"));
  }, [stale, announce, t]);

  const answerRequest = useEffectEvent((request: SettingsOpenRequest) => {
    if (canEdit && !editing) flushSync(startEditing);
    focusField(request.focus ?? "name");
  });

  useEffect(() => {
    if (!openRequest || answeredRequests.has(openRequest)) return;
    // After this commit: a page may mount the section and ask in one go.
    const frame = requestAnimationFrame(() => {
      answeredRequests.add(openRequest);
      answerRequest(openRequest);
    });
    return () => cancelAnimationFrame(frame);
  }, [openRequest]);

  function loadForm(from: FlowPublic) {
    const saved = draftOf(from);
    setLoaded(saved);
    setName(saved.name);
    setDescription(saved.description);
    setFields(saved.fields);
    setAllowExport(saved.allowExport);
    setTranscriptionDraft(saved.transcription);
    setMaxSpeakersInvalid(false);
    setShowProblems(false);
  }

  function startEditing() {
    loadForm(flow);
    setEditing(true);
  }

  /**
   * Scrolls to a field of the form and focuses it; a transcription field not
   * on screen falls back to the first control there. Read-only, the section.
   */
  function focusField(field: RequestedField) {
    const form = formRef.current;
    const wrapper =
      form?.querySelector(`[data-settings-field="${field}"]`) ??
      form?.querySelector('[data-settings-field="transcription"]');
    const control = wrapper?.querySelector<HTMLElement>("input, textarea, button");
    if (!control) {
      sectionRef.current?.scrollIntoView({ block: "start" });
      return;
    }
    control.scrollIntoView({ block: "center" });
    control.focus({ preventScroll: true });
  }

  function reload() {
    flushSync(() => loadForm(flow));
    announce(t("flows_settings_reloaded"));
    // The banner and its button are gone: the form's first field takes focus.
    focusField("name");
  }

  function stopEditing() {
    setEditing(false);
    // The form is gone; its "Ändra" button takes focus back.
    requestAnimationFrame(() => editButtonRef.current?.querySelector("button")?.focus());
  }

  function addField() {
    nextKey.current += 1;
    flushSync(() =>
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
      ])
    );
    // The first field replaces the empty state, and the add button with it.
    if (fields.length === 0) {
      formRef.current?.querySelector<HTMLElement>("[data-add-field] button")?.focus();
    }
  }

  const moveId = (key: string, direction: "up" | "down") => `${formId}-${key}-${direction}`;

  /** A field's title: its label, or its place in the form while it has none. */
  const fieldTitle = (field: FormFieldDraft, position: number) =>
    field.label.trim() || t("flows_form_field_number", { number: position });

  /**
   * Moves a field up or down the form; its button keeps focus, at an end its twin. The
   * announcement names it as its row does after the move (an unlabeled field's place changed).
   */
  function moveField(field: FormFieldDraft, position: number, delta: -1 | 1) {
    const next = withFieldMoved(fields, field.key, delta);
    if (!next) return;
    flushSync(() => setFields(next));
    const moved = position + delta;
    announce(t("flows_step_moved", { step: fieldTitle(field, moved), position: moved }));
    const same = document.getElementById(moveId(field.key, delta < 0 ? "up" : "down"));
    const other = document.getElementById(moveId(field.key, delta < 0 ? "down" : "up"));
    (same instanceof HTMLButtonElement && !same.disabled ? same : other)?.focus();
  }

  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (stale) {
      // Saving would overwrite what changed: the banner says what to do first.
      reloadRef.current?.focus();
      return;
    }
    if (nameMissing || problems.length > 0 || maxSpeakersInvalid) {
      // Rendered before focus moves, so the first field is read with its error.
      flushSync(() => setShowProblems(true));
      formRef.current
        ?.querySelector<HTMLElement>('[aria-invalid="true"], [data-invalid] input')
        ?.focus();
      return;
    }
    setSaving(true);
    const renames = renamedFormFields(loaded.fields, fields);
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

  const addFieldButton = (
    <div data-add-field>
      <Button
        label={t("flows_form_add_field")}
        icon={<Plus aria-hidden="true" />}
        size="sm"
        onClick={addField}
      />
    </div>
  );

  return (
    <section
      id="flow-settings"
      ref={sectionRef}
      aria-labelledby={headingId}
      className="flex flex-col gap-3"
    >
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
        <SettingsSummary
          flow={flow}
          transcription={transcription}
          stepCount={stepCount}
          problemCount={problemCount}
        />
      ) : (
        <form
          id={formId}
          ref={formRef}
          onSubmit={submit}
          noValidate
          className="border-ax-border bg-ax-card rounded-ax-container flex max-w-3xl flex-col gap-4 border p-4"
        >
          {stale ? (
            <Banner
              status="warning"
              title={t("flows_settings_stale_title")}
              description={t("flows_settings_stale_description")}
              collapsible={false}
              endContent={
                <Button
                  ref={reloadRef}
                  label={t("flows_settings_reload")}
                  size="sm"
                  onClick={reload}
                />
              }
            />
          ) : null}
          <div className="flex max-w-xl flex-col gap-4">
            <div data-settings-field="name">
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
            </div>
            <TextArea
              label={t("description")}
              value={description}
              onChange={setDescription}
              rows={3}
            />
          </div>
          <fieldset className="flex flex-col gap-3">
            <legend className="text-ax-text mb-1 text-sm font-semibold">
              {t("flows_form_heading")}
            </legend>
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flows_form_description")}
            </Text>
            {fields.length === 0 ? (
              <EmptyState
                title={t("flows_form_empty")}
                description={t("flows_settings_form_empty_example", {
                  token: "{{flow_input.extern_referens}}"
                })}
                actions={addFieldButton}
                headingLevel={3}
                isCompact
                // Opening the form is no news, and removing the last field moves focus here.
                isAnnounced={false}
              />
            ) : null}
            {fields.map((field, index) => {
              const title = fieldTitle(field, index + 1);
              return (
                <FormFieldRow
                  key={field.key}
                  field={field}
                  title={title}
                  isFirst={index === 0}
                  isLast={index === fields.length - 1}
                  moveId={(direction) => moveId(field.key, direction)}
                  onMove={(delta) => moveField(field, index + 1, delta)}
                  problems={
                    showProblems ? problems.filter((problem) => problem.key === field.key) : []
                  }
                  existingNames={fields
                    .filter((other) => other.key !== field.key)
                    .map((other) => other.name)}
                  onChange={(next) => setFields((current) => withFieldChanged(current, next))}
                  onRemove={() => {
                    setFields((current) =>
                      current.filter((candidate) => candidate.key !== field.key)
                    );
                    // The row is gone; the add button keeps focus in the form.
                    requestAnimationFrame(() =>
                      formRef.current
                        ?.querySelector<HTMLElement>("[data-add-field] button")
                        ?.focus()
                    );
                  }}
                />
              );
            })}
            {fields.length > 0 ? addFieldButton : null}
          </fieldset>
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
          <Switch
            label={t("flows_evidence_export")}
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
      {editing ? <LeaveConfirmation active={dirty} /> : null}
    </section>
  );
}

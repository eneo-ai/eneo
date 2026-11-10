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
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useEffectEvent, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Collapsible } from "@/components/astryx/collapsible";
import { TextInput } from "@/components/astryx/text-input";
import { EmptyState } from "@/components/composites/empty-state";
import { LeaveConfirmation } from "@/components/composites/leave-confirmation";
import { useAppContext } from "@/components/providers/app-context";
import { EditorSection } from "./editor/editor-fields";
import { useFlowReadLabel } from "./flow-read-layout";
import { FlowRetentionDialog, FlowRetentionSummary } from "./flow-retention";
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
  type TranscriptionResources,
  type TranscriptionSettings
} from "./flow-transcription";
import { TranscriptionFields, TranscriptionSummary } from "./flow-transcription-settings";

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
type RequestedField = "name" | "transcription_model" | "speaker_service" | "live_model";

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

type SpaceClassification = { name: string; security_level: number };

/**
 * The read view: what a run asks for, how its audio is transcribed and whether
 * its evidence may be downloaded. Without `transcription` (a page that has not
 * read the space) it says only whether the flow transcribes. The page's title
 * names the flow, so the list does not; rows with nothing to say (no run form,
 * no transcription) are left out.
 */
export function SettingsSummary({
  flow,
  transcription,
  hideIdentity = false,
  classification
}: {
  flow: FlowPublic;
  transcription?: TranscriptionResources;
  /** Leaves out the description and the step count, for a page whose header and step list say them. */
  hideIdentity?: boolean;
  /** The space's security classification, when it has one. */
  classification?: SpaceClassification | null;
}) {
  const t = useTranslations();
  const fields = formFieldsOf(flow.metadata_json);
  const raisingSteps = flow.steps.filter(
    (step) => (step.output_classification_override ?? 0) > (classification?.security_level ?? 0)
  ).length;
  const settings = transcriptionSettingsOf(flow.metadata_json);
  const transcribes = flowTakesAudio(flow.steps) || settings.enabled;
  // The flow read views' label column; on top wherever the summary itself is narrow.
  const rootRef = useRef<HTMLDivElement>(null);
  const label = useFlowReadLabel(rootRef);
  // The transcription's own settings under their heading, after the rest, so they scan as one.
  const transcriptionDetails = transcribes && transcription;
  const list = (
    <MetadataList label={label}>
      {hideIdentity ? null : (
        <>
          <MetadataListItem label={t("description")}>
            {flow.description?.trim() || (
              <span className="text-ax-text-secondary">{t("flows_no_description")}</span>
            )}
          </MetadataListItem>
          <MetadataListItem label={t("flows_settings_steps")}>{flow.steps.length}</MetadataListItem>
        </>
      )}
      {fields.length > 0 ? (
        <MetadataListItem label={t("flows_settings_form_fields")}>
          {fields.length}
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
        </MetadataListItem>
      ) : null}
      {transcribes && !transcriptionDetails ? (
        <MetadataListItem label={t("flow_editor_tools_transcription_heading")}>
          {t("flow_editor_tools_on")}
        </MetadataListItem>
      ) : null}
      <MetadataListItem label={t("flows_evidence_export")}>
        {t(
          evidenceExportAllowed(flow.metadata_json)
            ? "flow_editor_tools_on"
            : "flow_editor_tools_off"
        )}
      </MetadataListItem>
      <MetadataListItem label={t("flows_retention_heading")}>
        <FlowRetentionSummary flow={flow} />
      </MetadataListItem>
      {classification ? (
        <MetadataListItem label={t("flows_classification_heading")}>
          {raisingSteps > 0
            ? t("flows_classification_raised", { name: classification.name, count: raisingSteps })
            : classification.name}
          <span className="text-ax-text-secondary mt-0.5 block text-sm">
            {t("flows_classification_hint")}
          </span>
        </MetadataListItem>
      ) : null}
    </MetadataList>
  );
  return (
    <div ref={rootRef} className="flex min-w-0 flex-col gap-6">
      {list}
      {transcriptionDetails ? (
        <MetadataList
          label={label}
          title={
            <Heading level={3} weight="semibold" className="text-base">
              {t("flow_editor_tools_transcription_heading")}
            </Heading>
          }
        >
          <TranscriptionSummary
            settings={settings}
            resources={transcriptionDetails}
            required={speakersRequired(flow.steps)}
            modelMissing={transcriptionModelMissing(settings, flow.steps)}
          />
        </MetadataList>
      ) : null}
    </div>
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
  existingNames,
  labelTaken
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
  /** Another field of the form has the same label: the run form could not tell them apart. */
  labelTaken: boolean;
}) {
  const t = useTranslations();
  const legendId = useId();
  const nameProblem = problems.find((problem) => problem.part === "name");
  const optionsProblem = problems.find((problem) => problem.part === "options");
  const role = roleFor(field.type);
  const token = `{{flow_input.${field.name.trim() || "…"}}}`;
  // Following the label the name needs no look; one typed by hand, or with a problem, does.
  const typedName =
    field.nameEdited && field.name.trim() !== suggestedFieldName(field.label, existingNames);
  const [nameToggled, setNameToggled] = useState<boolean | null>(null);
  const nameOpen = nameProblem !== undefined || (nameToggled ?? typedName);

  return (
    <div
      role="group"
      aria-labelledby={legendId}
      data-field-key={field.key}
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
        status={
          labelTaken
            ? {
                type: "warning",
                message: t("flows_field_label_taken", { label: field.label.trim() })
              }
            : undefined
        }
      />
      <Collapsible
        isOpen={nameOpen}
        onOpenChange={setNameToggled}
        chevronPosition="start"
        trigger={
          <span className="text-ax-text-secondary flex min-w-0 flex-wrap items-baseline gap-x-1.5 py-1 text-start text-sm font-normal">
            {t("flows_form_field_name_trigger")}
            <code className="text-ax-text min-w-0 break-all">{token}</code>
          </span>
        }
      >
        <div className="pt-2">
          <TextInput
            label={t("flows_form_field_name")}
            description={t("flows_form_field_name_hint")}
            value={field.name}
            onChange={(name) => onChange({ ...field, name, nameEdited: true })}
            isRequired
            autoComplete="off"
            status={
              nameProblem
                ? { type: "error", message: t(PROBLEM_KEYS[nameProblem.problem]) }
                : undefined
            }
          />
        </div>
      </Collapsible>
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
  classification,
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
  /** The space's security classification, when it has one. */
  classification?: SpaceClassification | null;
  /** Told true while the open form differs from the flow it was loaded from. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const t = useTranslations();
  const { can } = useAppContext();
  const [retentionOpen, setRetentionOpen] = useState(false);
  const mayChangeRetention = can("retention_manage");
  const announce = useAnnounce();
  const headingId = useId();
  const formId = useId();
  const evidenceHeadingId = useId();
  const sectionRef = useRef<HTMLElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
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

  /** "Ändra inställningar": its button leaves with the summary, so focus goes to the form's first field. */
  function openForm() {
    flushSync(startEditing);
    focusField("name");
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
    requestAnimationFrame(() => editButtonRef.current?.focus());
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
    // The new row's label is what to fill in first (the empty state and its button may be gone).
    formRef.current
      ?.querySelector<HTMLElement>(`[data-field-key="new-${nextKey.current}"] input`)
      ?.focus();
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
        {/* Every way to change the settings sits here, each named for what it
            changes; retention has its own dialog, open on a published flow too. */}
        {!editing && (canEdit || mayChangeRetention) ? (
          <div className="flex flex-wrap items-center gap-2">
            {canEdit ? (
              <Button
                ref={editButtonRef}
                label={t("flows_settings_edit")}
                size="sm"
                onClick={openForm}
              />
            ) : null}
            {mayChangeRetention ? (
              <Button
                label={t("flows_retention_change")}
                size="sm"
                onClick={() => setRetentionOpen(true)}
              />
            ) : null}
          </div>
        ) : null}
      </div>
      {!editing ? (
        <SettingsSummary
          flow={flow}
          transcription={transcription}
          hideIdentity
          classification={classification}
        />
      ) : (
        <form
          id={formId}
          ref={formRef}
          onSubmit={submit}
          noValidate
          className="flex max-w-3xl flex-col gap-4"
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
          <fieldset className="border-ax-border flex flex-col gap-3 border-t pt-5">
            <legend className="float-left w-full p-0">
              <Heading level={3}>{t("flows_form_heading")}</Heading>
            </legend>
            <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
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
                  labelTaken={
                    field.label.trim() !== "" &&
                    fields.some(
                      (other) =>
                        other.key !== field.key &&
                        other.label.trim().toLocaleLowerCase() ===
                          field.label.trim().toLocaleLowerCase()
                    )
                  }
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
          <EditorSection id={evidenceHeadingId} title={t("flows_evidence_heading")}>
            <Switch
              label={t("flows_evidence_export")}
              description={t("flows_evidence_export_hint")}
              value={allowExport}
              onChange={setAllowExport}
            />
          </EditorSection>
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
      <FlowRetentionDialog flow={flow} open={retentionOpen} onOpenChange={setRetentionOpen} />
    </section>
  );
}

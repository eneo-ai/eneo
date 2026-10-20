"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { List, ListItem } from "@astryxdesign/core/List";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { uniqueKey } from "./editor/step-keys";
import { problemStatus } from "./editor/step-fields";
import { fieldTypeLine } from "./flow-definition";
import { stepReads } from "./flow-reads";
import {
  formFieldsOf,
  stepsOf,
  type FlowDefinition,
  type FlowStep,
  type FormField,
  type FormFieldType
} from "./types";

const TYPES: FormFieldType[] = ["text", "number", "select", "file", "audio"];

const TYPE_KEYS: Record<FormFieldType, string> = {
  text: "flow_field_type_text",
  number: "flow_field_type_number",
  select: "flow_field_type_select",
  file: "flow_field_type_file",
  audio: "flow_field_type_audio"
};

/** The steps that read a run input: by template, as a file, as audio, or for speaker names. */
export function stepsReadingInput(key: string, definition: FlowDefinition): FlowStep[] {
  return stepsOf(definition).filter(
    (step) =>
      stepReads(step, definition).some((read) => read.kind === "form" && read.key === key) ||
      (step.kind === "transcribe" && step.speaker_mapping?.participants_field === key)
  );
}

type Draft = {
  label: string;
  type: FormFieldType;
  required: boolean;
  description: string;
  options: string;
};

const blank: Draft = { label: "", type: "text", required: true, description: "", options: "" };

function draftOf(field: FormField): Draft {
  return {
    label: field.label,
    type: field.type,
    required: field.required !== false,
    description: field.description ?? "",
    options: (field.options ?? []).join(", ")
  };
}

/** The form of one run input: label (its key follows), type, required, description, options. */
function InputForm({
  draft,
  onChange,
  problem,
  existingKey
}: {
  draft: Draft;
  onChange: (next: Draft) => void;
  problem: string | null;
  existingKey: string | null;
}) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextInput
          label={t("flow_input_label")}
          description={
            existingKey
              ? t("flow_input_key_existing", { key: existingKey })
              : t("flow_input_key_hint")
          }
          value={draft.label}
          onChange={(label) => onChange({ ...draft, label })}
          isRequired
          status={problemStatus(problem ?? undefined)}
        />
        <Selector
          label={t("flow_input_type")}
          options={TYPES.map((type) => ({ value: type, label: t(TYPE_KEYS[type]) }))}
          value={draft.type}
          onChange={(type) => onChange({ ...draft, type: type as FormFieldType })}
        />
      </div>
      <TextInput
        label={t("flow_input_description")}
        description={t("flow_input_description_hint")}
        value={draft.description}
        onChange={(description) => onChange({ ...draft, description })}
      />
      {draft.type === "select" && (
        <TextInput
          label={t("flow_input_options")}
          description={t("flow_input_options_hint")}
          value={draft.options}
          onChange={(options) => onChange({ ...draft, options })}
          isRequired
        />
      )}
      <CheckboxInput
        label={t("flow_input_required")}
        value={draft.required}
        onChange={(required) => onChange({ ...draft, required })}
      />
    </div>
  );
}

/**
 * The run inputs of a flow, edited in a dialog: the list with move, edit
 * and remove, and a form to add or change one. An input a step reads
 * cannot be removed; the steps are named instead. Saving hands the whole
 * list back; the panel saves it as a draft revision.
 */
export function FlowInputsEditor({
  definition,
  open,
  onOpenChange,
  onSave,
  saving
}: {
  definition: FlowDefinition;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Resolves when the save landed (the dialog closes), rejects when it was refused (it stays). */
  onSave: (fields: FormField[]) => Promise<unknown>;
  saving: boolean;
}) {
  const t = useTranslations();
  const [fields, setFields] = useState<FormField[]>(() => formFieldsOf(definition));
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(blank);
  const [problem, setProblem] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const dirty = JSON.stringify(fields) !== JSON.stringify(formFieldsOf(definition));

  const startEdit = (index: number | "new") => {
    setEditing(index);
    setDraft(index === "new" ? blank : draftOf(fields[index]!));
    setProblem(null);
    setBlocked(null);
  };
  const commit = () => {
    if (!draft.label.trim()) return setProblem(t("flow_editor_required"));
    const options =
      draft.type === "select"
        ? draft.options
            .split(",")
            .map((option) => option.trim())
            .filter(Boolean)
        : null;
    if (draft.type === "select" && !options?.length) {
      return setProblem(t("flow_input_options_required"));
    }
    const existing = editing !== "new" && editing !== null ? fields[editing]! : null;
    const field: FormField = {
      key:
        existing?.key ??
        uniqueKey(
          draft.label,
          fields.map((candidate) => candidate.key)
        ),
      label: draft.label.trim(),
      type: draft.type,
      required: draft.required,
      description: draft.description.trim() || null,
      options
    };
    setFields((current) =>
      editing === "new" ? [...current, field] : current.map((f, i) => (i === editing ? field : f))
    );
    setEditing(null);
  };
  const remove = (index: number) => {
    const field = fields[index]!;
    const readers = stepsReadingInput(field.key, definition);
    if (readers.length > 0) {
      setBlocked(
        t("flow_input_remove_blocked", {
          label: field.label,
          names: readers.map((step) => step.name).join(", ")
        })
      );
      return;
    }
    setBlocked(null);
    setFields((current) => current.filter((_, i) => i !== index));
  };
  const move = (index: number, direction: -1 | 1) => {
    const to = index + direction;
    if (to < 0 || to >= fields.length) return;
    setFields((current) => {
      const next = [...current];
      const [moved] = next.splice(index, 1);
      next.splice(to, 0, moved!);
      return next;
    });
  };

  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange} width={640} maxHeight="85dvh">
      <Layout
        header={
          <DialogHeader
            title={t("flow_inputs_editor_title")}
            subtitle={t("flow_inputs_editor_subtitle")}
            onOpenChange={onOpenChange}
          />
        }
        content={
          <LayoutContent>
            <div className="flex flex-col gap-4">
              {fields.length === 0 && editing === null ? (
                <Text type="supporting" size="sm">
                  {t("flow_inputs_none")}
                </Text>
              ) : (
                <List density="compact" hasDividers>
                  {fields.map((field, index) => (
                    <ListItem
                      key={field.key}
                      label={field.label}
                      description={fieldTypeLine(field, t)}
                      endContent={
                        <span className="flex items-center gap-0.5">
                          <IconButton
                            label={t("flow_input_move_up", { label: field.label })}
                            tooltip={t("flow_editor_move_up")}
                            icon={<ArrowUp className="size-4" />}
                            variant="ghost"
                            size="sm"
                            isDisabled={index === 0}
                            onClick={() => move(index, -1)}
                          />
                          <IconButton
                            label={t("flow_input_move_down", { label: field.label })}
                            tooltip={t("flow_editor_move_down")}
                            icon={<ArrowDown className="size-4" />}
                            variant="ghost"
                            size="sm"
                            isDisabled={index === fields.length - 1}
                            onClick={() => move(index, 1)}
                          />
                          <IconButton
                            label={t("flow_input_edit", { label: field.label })}
                            tooltip={t("edit")}
                            icon={<Pencil className="size-4" />}
                            variant="ghost"
                            size="sm"
                            onClick={() => startEdit(index)}
                          />
                          <IconButton
                            label={t("flow_input_remove", { label: field.label })}
                            tooltip={t("remove")}
                            icon={<Trash2 className="size-4" />}
                            variant="ghost"
                            size="sm"
                            onClick={() => remove(index)}
                          />
                        </span>
                      }
                    />
                  ))}
                </List>
              )}
              {blocked && (
                <Text
                  type="body"
                  size="sm"
                  as="p"
                  display="block"
                  role="alert"
                  className="text-ax-error m-0"
                >
                  {blocked}
                </Text>
              )}
              {editing === null ? (
                <Button
                  label={t("flow_input_add")}
                  size="sm"
                  icon={<Plus className="size-4" />}
                  onClick={() => startEdit("new")}
                  className="self-start"
                />
              ) : (
                <div className="border-ax-border rounded-ax-container flex flex-col gap-4 border p-4">
                  <Text type="body" weight="semibold">
                    {editing === "new" ? t("flow_input_add") : t("flow_input_edit_title")}
                  </Text>
                  <InputForm
                    draft={draft}
                    onChange={setDraft}
                    problem={problem}
                    existingKey={editing === "new" ? null : fields[editing]!.key}
                  />
                  <div className="flex justify-end gap-2">
                    <Button label={t("cancel")} size="sm" onClick={() => setEditing(null)} />
                    <Button
                      label={editing === "new" ? t("add") : t("flow_input_apply")}
                      variant="primary"
                      size="sm"
                      onClick={commit}
                    />
                  </div>
                </div>
              )}
            </div>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <div className="flex justify-end gap-2">
              <Button label={t("cancel")} onClick={() => onOpenChange(false)} />
              <Button
                label={t("flow_editor_save_draft")}
                variant="primary"
                isDisabled={!dirty || editing !== null}
                isLoading={saving}
                isInterruptible
                onClick={() => {
                  if (saving) return;
                  onSave(fields)
                    .then(() => onOpenChange(false))
                    .catch(() => {});
                }}
              />
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}

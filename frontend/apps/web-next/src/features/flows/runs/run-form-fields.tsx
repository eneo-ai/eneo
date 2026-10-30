"use client";

import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { DateInput, type DateInputProps } from "@astryxdesign/core/DateInput";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "use-intl";
import { calendarDate } from "@/lib/calendar-date";
import { fieldLabel, type FieldProblem, type FieldValue } from "./run-contract";
import type { RunFormField } from "./runs-api";

type IsoDate = NonNullable<DateInputProps["value"]>;

/** The id of the element around a form field, for "go to the problem". */
export function fieldAnchorId(formId: string, name: string): string {
  return `${formId}-field-${name.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

/** Moves focus to the first control inside the element with `id`. */
export function focusFirstControl(id: string): boolean {
  const control = document
    .getElementById(id)
    ?.querySelector<HTMLElement>(
      "input:not([type=hidden]), textarea, select, button, [tabindex]:not([tabindex='-1'])"
    );
  if (!control) return false;
  control.focus();
  return true;
}

export function fieldProblemText(
  field: RunFormField,
  problem: FieldProblem,
  t: ReturnType<typeof useTranslations>
): string {
  const label = fieldLabel(field);
  switch (problem) {
    case "required":
      return isListType(field)
        ? t("flow_runs_field_required_choose", { field: label })
        : t("flow_runs_field_required", { field: label });
    case "number":
      return t("flow_runs_field_number", { field: label });
    case "date":
      return t("flow_runs_field_date", { field: label });
    case "option":
      return t("flow_runs_field_option", { field: label });
  }
}

function isListType(field: RunFormField) {
  return field.type === "select" || field.type === "multiselect";
}

/**
 * One field of the run form, with the control its type asks for: text,
 * number, date, a choice, several choices, or a list (one entry per line).
 * A problem shows as text at the field (`message`).
 */
export function RunFormFieldControl({
  formId,
  field,
  value,
  onChange,
  message
}: {
  formId: string;
  field: RunFormField;
  value: FieldValue | undefined;
  onChange: (value: FieldValue) => void;
  message: string | null;
}) {
  const t = useTranslations();
  const label = fieldLabel(field);
  const status = message ? ({ type: "error", message } as const) : undefined;
  const required = field.required === true;
  const requirement = required ? { isRequired: true } : { isOptional: true };
  const text = typeof value === "string" ? value : "";
  const list = Array.isArray(value) ? value : [];
  const options = field.options ?? [];

  let control: React.ReactNode;
  switch (field.type) {
    case "number":
      control = (
        <NumberInput
          label={label}
          value={text.trim() && Number.isFinite(Number(text)) ? Number(text) : null}
          onChange={(next) => onChange(next == null ? "" : String(next))}
          status={status}
          hasClear
          width="100%"
          {...requirement}
        />
      );
      break;
    case "date":
      control = (
        <DateInput
          label={label}
          value={(calendarDate(text) as IsoDate | undefined) ?? undefined}
          onChange={(next) => onChange(next ?? "")}
          presentation="adaptive-bottom-sheet"
          weekStartsOn="mon"
          hasClear
          status={status}
          width="100%"
          {...requirement}
        />
      );
      break;
    case "select":
      // An optional choice can be cleared again; a required one cannot.
      control = required ? (
        <Selector
          label={label}
          options={options}
          value={text || undefined}
          onChange={(next: string) => onChange(next)}
          placeholder={t("flow_runs_field_choose")}
          status={status}
          width="100%"
          isRequired
        />
      ) : (
        <Selector
          label={label}
          options={options}
          value={text || null}
          onChange={(next: string | null) => onChange(next ?? "")}
          placeholder={t("flow_runs_field_choose")}
          hasClear
          status={status}
          width="100%"
          isOptional
        />
      );
      break;
    case "multiselect":
      control = (
        <CheckboxList
          label={label}
          value={list}
          onChange={(next) => onChange(next)}
          density="compact"
          status={status}
          description={required ? t("flow_runs_field_choose_at_least_one") : undefined}
        >
          {options.map((option) => (
            <CheckboxListItem key={option} value={option} label={option} />
          ))}
        </CheckboxList>
      );
      break;
    case "list":
      control = (
        <TextArea
          label={label}
          description={t("flow_runs_field_list_hint")}
          value={list.join("\n")}
          onChange={(next) => onChange(next.split("\n"))}
          rows={3}
          status={status}
          width="100%"
          {...requirement}
        />
      );
      break;
    default:
      control = (
        <TextArea
          label={label}
          value={text}
          onChange={(next) => onChange(next)}
          rows={2}
          status={status}
          width="100%"
          {...requirement}
        />
      );
  }

  return <div id={fieldAnchorId(formId, field.name)}>{control}</div>;
}

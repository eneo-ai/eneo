"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { IconButton } from "@astryxdesign/core/IconButton";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { flushSync } from "react-dom";
import { focusFirstControl } from "./run-form-fields";
import {
  emptyValue,
  fieldChoices,
  fieldDescription,
  fieldKind,
  fieldLabel,
  isReviewObject,
  itemPreview,
  objectFields,
  schemaOf,
  withProperty,
  type ReviewSchema,
  type ReviewValue
} from "./review-structured";

type FieldProps = {
  schema: ReviewSchema;
  value: ReviewValue | undefined;
  label: string;
  depth: number;
  /** A closed row is named by its first text fields. */
  preview?: string;
  defaultIsOpen?: boolean;
  onChange: (value: ReviewValue) => void;
};

/** Puts focus in a new row's first field, past the row's own disclosure. */
function focusNewRow(id: string) {
  const field = document
    .getElementById(id)
    ?.querySelector<HTMLElement>("textarea, input:not([type=hidden]), [role=combobox]");
  if (field) field.focus();
  else focusFirstControl(id);
}

/** A value the form cannot edit, shown as it is stored. */
function ShownValue({ label, value, note }: { label: string; value: unknown; note?: string }) {
  const t = useTranslations();
  const empty = value === undefined || value === null || value === "";
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className="text-ax-text-secondary text-sm font-medium">{label}</p>
      {note ? <p className="text-ax-text-secondary text-xs">{note}</p> : null}
      {empty ? (
        <p className="text-ax-text-secondary text-sm">{t("flow_runs_value_empty")}</p>
      ) : typeof value === "object" ? (
        <pre className="bg-ax-sunken rounded-ax-inner text-ax-text max-h-64 overflow-auto p-2 text-xs">
          {JSON.stringify(value, null, 2)}
        </pre>
      ) : (
        <p className="text-ax-text text-sm break-words whitespace-pre-wrap">
          {typeof value === "boolean" ? (value ? t("yes") : t("no")) : String(value)}
        </p>
      )}
    </div>
  );
}

function ObjectFields({
  schema,
  value,
  depth,
  onChange
}: Pick<FieldProps, "schema" | "value" | "depth" | "onChange">) {
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {objectFields(schema, value).map((field) => (
        <StructuredField
          key={field.key}
          schema={field.schema}
          value={isReviewObject(value) ? value[field.key] : undefined}
          label={fieldLabel(field.schema, field.key)}
          depth={depth + 1}
          onChange={(next) => onChange(withProperty(value, field.key, next))}
        />
      ))}
    </div>
  );
}

function ListRows({
  schema,
  value,
  label,
  depth,
  onChange
}: Pick<FieldProps, "schema" | "value" | "label" | "depth" | "onChange">) {
  const t = useTranslations();
  const baseId = useId();
  const [added, setAdded] = useState<number | null>(null);
  const items = Array.isArray(value) ? value : [];
  const itemSchema = schemaOf(schema.items);
  const minItems = typeof schema.minItems === "number" ? schema.minItems : 0;
  const maxItems = typeof schema.maxItems === "number" ? schema.maxItems : Infinity;
  const addId = `${baseId}-add`;
  const rowId = (index: number) => `${baseId}-row-${index}`;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      {items.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_review_no_rows")}</p>
      ) : (
        <ol className="m-0 flex flex-col p-0" aria-label={label}>
          {items.map((item, index) => {
            const rowLabel = t("flow_run_extras_review_row", { number: index + 1 });
            return (
              <li
                key={index}
                id={rowId(index)}
                className="border-ax-border flex min-w-0 items-start gap-2 border-t py-2 first:border-t-0"
              >
                <div className="min-w-0 flex-1">
                  <StructuredField
                    schema={itemSchema}
                    value={item}
                    label={rowLabel}
                    preview={itemPreview(itemSchema, item)}
                    depth={depth + 1}
                    defaultIsOpen={index === added}
                    onChange={(next) =>
                      onChange(items.map((existing, at) => (at === index ? next : existing)))
                    }
                  />
                </div>
                <IconButton
                  label={t("flow_run_extras_review_remove_row", { number: index + 1 })}
                  icon={<Trash2 aria-hidden="true" />}
                  variant="ghost"
                  isDisabled={items.length <= minItems}
                  onClick={() => {
                    flushSync(() => onChange(items.filter((_, at) => at !== index)));
                    focusFirstControl(addId);
                  }}
                />
              </li>
            );
          })}
        </ol>
      )}
      {fieldKind(itemSchema) !== "unsupported" ? (
        <div id={addId}>
          <Button
            label={t("flow_run_extras_review_add_row")}
            isDisabled={items.length >= maxItems}
            onClick={() => {
              flushSync(() => {
                setAdded(items.length);
                onChange([...items, emptyValue(itemSchema)]);
              });
              focusNewRow(rowId(items.length));
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

function StructuredField({
  schema,
  value,
  label,
  depth,
  preview,
  defaultIsOpen,
  onChange
}: FieldProps) {
  const t = useTranslations();
  const kind = fieldKind(schema, value, depth);
  const description = fieldDescription(schema);

  if (kind === "object" || kind === "array") {
    const contents =
      kind === "object" ? (
        <ObjectFields schema={schema} value={value} depth={depth} onChange={onChange} />
      ) : (
        <ListRows schema={schema} value={value} label={label} depth={depth} onChange={onChange} />
      );
    if (depth === 0) return contents;
    const count = kind === "array" && Array.isArray(value) ? value.length : null;
    return (
      <Collapsible
        defaultIsOpen={defaultIsOpen ?? depth === 1}
        chevronPosition="start"
        trigger={
          <span className="flex min-w-0 flex-col text-sm">
            <span className="text-ax-text font-medium break-words">
              {preview ? `${label}: ${preview}` : label}
            </span>
            {count !== null ? (
              <span className="text-ax-text-secondary text-xs">
                {t("flow_run_extras_review_rows", { count })}
              </span>
            ) : null}
          </span>
        }
      >
        <div className="border-ax-border ml-2 flex min-w-0 flex-col gap-3 border-l py-2 pl-4">
          {description ? <p className="text-ax-text-secondary text-sm">{description}</p> : null}
          {contents}
        </div>
      </Collapsible>
    );
  }

  switch (kind) {
    case "string": {
      const text = typeof value === "string" ? value : "";
      return (
        <TextArea
          label={label}
          description={description}
          value={text}
          onChange={onChange}
          rows={text.length > 80 || text.includes("\n") ? 4 : 1}
          width="100%"
        />
      );
    }
    case "number":
      return (
        <NumberInput
          label={label}
          description={description}
          value={typeof value === "number" ? value : null}
          onChange={onChange}
          hasClear
          isIntegerOnly={schema.type === "integer"}
          min={typeof schema.minimum === "number" ? schema.minimum : null}
          max={typeof schema.maximum === "number" ? schema.maximum : null}
          width="100%"
        />
      );
    case "boolean":
      return (
        <Selector
          label={label}
          description={description}
          placeholder={t("flow_run_extras_review_choose")}
          value={typeof value === "boolean" ? String(value) : undefined}
          onChange={(next) => onChange(next === "true")}
          options={[
            { value: "true", label: t("yes") },
            { value: "false", label: t("no") }
          ]}
          width="100%"
        />
      );
    case "enum": {
      const choices = fieldChoices(schema);
      const current = typeof value === "string" ? value : "";
      const chosen = current !== "" || choices.includes("");
      return (
        <Selector
          label={label}
          description={description}
          placeholder={t("flow_run_extras_review_choose")}
          value={chosen ? current : undefined}
          onChange={onChange}
          options={[
            // A stored value the contract no longer offers stays visible, not choosable.
            ...(chosen && !choices.includes(current)
              ? [{ value: current, label: current, disabled: true }]
              : []),
            ...choices.map((choice) => ({
              value: choice,
              label: choice || t("flow_runs_value_empty")
            }))
          ]}
          width="100%"
        />
      );
    }
    case "readonly":
      return <ShownValue label={label} value={value} />;
    default:
      return (
        <ShownValue label={label} value={value} note={t("flow_run_extras_review_unsupported")} />
      );
  }
}

/**
 * The paused step's JSON output as a form built from its output contract:
 * nested objects open and close, lists get rows to add and remove (within
 * the contract's bounds), and each scalar gets the control its type asks
 * for. Fields the contract does not name and parts the form cannot edit
 * are kept as they are. `problem` is a refusal that names no field.
 */
export function StructuredReviewEditor({
  id,
  schema,
  value,
  problem,
  onChange
}: {
  id: string;
  schema: ReviewSchema;
  value: ReviewValue;
  problem: string | null;
  onChange: (value: ReviewValue) => void;
}) {
  const t = useTranslations();
  return (
    <div id={id} className="flex min-w-0 flex-col gap-3">
      <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_review_form_hint")}</p>
      {problem ? <p className="text-ax-error text-sm">{problem}</p> : null}
      <StructuredField
        schema={schema}
        value={value}
        label={t("flow_runs_review_output")}
        depth={0}
        onChange={onChange}
      />
    </div>
  );
}

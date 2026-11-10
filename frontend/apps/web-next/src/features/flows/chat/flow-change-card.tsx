import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@/components/astryx/collapsible";
import { PencilLine } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState, type ReactNode } from "react";
import { IconTile } from "@/components/composites/icon-tile";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { anchorForPath } from "../editor/field-problems";
import {
  hasHttpConfig,
  readHttpConfig,
  readRuntimeInput,
  readTemplateFill,
  reviewChoiceOf
} from "../editor/step-configs";
import { httpAuthSummary, httpBodyModeLabel, reviewChoiceLabel } from "../editor/step-labels";
import type { ReviewPolicy } from "../editor/step-types";
import { runtimeInputLabel, stepLabel } from "../flow-labels";
import { isFlowsToolCall } from "./flows-tool-call";
import { ReferenceText } from "./reference-text";
import { useFlowReferences } from "./reference-pill";

/** The tools of the flow chat whose call carries the steps it changed, each field before and after. */
const CHANGE_TOOLS = new Set(["update_step", "update_steps"]);

export type ChangedField = { field: string; before: unknown; after: unknown };

export type ChangedStep = {
  stepId: string;
  stepOrder: number;
  name: string | null;
  fields: ChangedField[];
};

/**
 * The step and assistant fields the card can name, by the editor's own label
 * where it has one; any other field shows by its own name.
 */
const FIELD_LABEL_KEYS: Record<string, string> = {
  user_description: "flows_change_field_user_description",
  input_source: "flow_step_editor_input_source",
  input_type: "flow_step_input_type",
  input_contract: "flows_change_field_input_contract",
  input_config: "flows_change_field_input_config",
  input_bindings: "flows_change_field_input_bindings",
  output_mode: "flow_step_output_mode",
  output_type: "flow_step_output_type",
  output_contract: "flow_step_output_contract",
  output_config: "flows_change_field_output_config",
  output_classification_override: "flow_step_security_classification",
  review_policy: "flow_step_review_policy",
  timeout_seconds: "flow_step_editor_timeout",
  "assistant.prompt": "flow_step_editor_instruction",
  "assistant.name": "flows_change_field_assistant_name",
  "assistant.description": "flows_change_field_assistant_description",
  "assistant.completion_model": "flow_step_editor_model",
  "assistant.completion_model_kwargs": "flows_change_field_assistant_completion_model_kwargs",
  "assistant.attachments": "flow_step_editor_attachments",
  "assistant.groups": "flows_change_field_assistant_groups",
  "assistant.websites": "flows_change_field_assistant_websites"
};

/** The catalog prefix of an enum field's values, as the editor names them. */
const ENUM_PREFIXES: Record<string, string> = {
  input_source: "flow_input_source_",
  input_type: "flow_type_",
  output_mode: "flow_output_mode_",
  output_type: "flow_output_type_"
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function changedField(value: unknown): ChangedField | null {
  if (!isRecord(value) || typeof value.field !== "string" || !value.field) return null;
  return { field: value.field, before: value.before, after: value.after };
}

function changedStep(value: unknown): ChangedStep | null {
  if (!isRecord(value) || typeof value.step_id !== "string" || !value.step_id) return null;
  const fields = Array.isArray(value.fields)
    ? value.fields.map(changedField).filter((field): field is ChangedField => field !== null)
    : [];
  if (fields.length === 0) return null;
  return {
    stepId: value.step_id,
    stepOrder: typeof value.step_order === "number" ? value.step_order : 0,
    name: typeof value.name === "string" ? value.name : null,
    fields
  };
}

/**
 * The steps an `update_step` or `update_steps` call of the flow chat changed,
 * from the call's data; empty for any other call, and for a change that set
 * every field to what it already was.
 */
export function changedSteps(
  call: Pick<ToolCallRecord, "toolName" | "structuredContent" | "serverName" | "isInternal">
): ChangedStep[] {
  if (!isFlowsToolCall(call) || !CHANGE_TOOLS.has(call.toolName)) return [];
  const changes = call.structuredContent?.changes;
  if (!Array.isArray(changes)) return [];
  return changes.map(changedStep).filter((step): step is ChangedStep => step !== null);
}

/** The chat's change card for a tool call; null for a call that changed no step. */
export function flowChangeCardFor(call: ToolCallRecord): ReactNode {
  const steps = changedSteps(call);
  return steps.length > 0 ? <FlowChangeCard steps={steps} /> : null;
}

type Translate = ReturnType<typeof useTranslations>;

/** One labelled part of a changed configuration ("Adress att skicka till: https://…"). */
type Line = { label: string; text: string };

/** A changed value as the card shows it: one text, or a configuration as labelled lines. */
type Shown = string | Line[];

/** A plain value in words: text as it is, a flag as Ja/Nej, a list joined, nothing as "(tomt)". */
function plainText(value: unknown, t: Translate): string {
  if (value === null || value === undefined || value === "") return t("flows_change_card_empty");
  if (typeof value === "string") return value;
  if (typeof value === "boolean")
    return t(value ? "flows_change_card_yes" : "flows_change_card_no");
  if (typeof value === "number") return String(value);
  if (Array.isArray(value) && value.every((item) => typeof item !== "object" || item === null)) {
    return value.map(String).join(", ");
  }
  return JSON.stringify(value);
}

/** A step's or an assistant's configuration as lines, in the editor's words where it has them. */
function configLines(field: string, config: Record<string, unknown>, t: Translate): Line[] {
  if (hasHttpConfig(config)) {
    const input = field === "input_config";
    const http = readHttpConfig(config, input ? "input" : "output");
    return [
      {
        label: t(input ? "flow_step_editor_http_url_get" : "flow_step_editor_http_url_post"),
        text: plainText(http.url, t)
      },
      { label: t("flow_step_editor_http_auth"), text: httpAuthSummary(http.auth, t) },
      ...(input
        ? []
        : [{ label: t("flow_step_editor_http_body"), text: httpBodyModeLabel(http.body.mode, t) }]),
      {
        label: t("flow_step_editor_http_timeout"),
        text: t("flow_step_editor_seconds", { count: http.timeout_seconds })
      }
    ];
  }
  if (field === "output_config" && ("bindings" in config || "template_asset_id" in config)) {
    const template = readTemplateFill(config);
    return [
      {
        label: t("flow_step_editor_template"),
        text: template.templateName ?? t("flow_step_editor_template_none")
      },
      ...Object.entries(template.bindings).map(([name, source]) => ({
        label: name,
        text: plainText(source, t)
      }))
    ];
  }
  return Object.entries(config).flatMap(([key, value]): Line[] => {
    if (key === "runtime_input") {
      const runtime = readRuntimeInput(config);
      return [
        { label: t("flow_step_editor_uploads_enabled"), text: plainText(runtime.enabled, t) },
        ...(runtime.enabled
          ? [
              {
                label: t("flow_runtime_input_format_label"),
                text: runtimeInputLabel(runtime.inputFormat, t)
              }
            ]
          : [])
      ];
    }
    if (key === "question" && field === "input_bindings") {
      return [{ label: t("flow_step_editor_underlag_text"), text: plainText(value, t) }];
    }
    return [{ label: key, text: plainText(value, t) }];
  });
}

/** A changed value in the editor's words: enum values by name, configurations as lines. */
function shownValue(field: string, value: unknown, t: Translate): Shown {
  const prefix = ENUM_PREFIXES[field];
  if (prefix && typeof value === "string" && t.has(`${prefix}${value}`)) {
    return t(`${prefix}${value}`);
  }
  if (field === "timeout_seconds" && typeof value === "number") {
    return t("flow_step_editor_seconds", { count: value });
  }
  if (field === "review_policy" && (value === null || isRecord(value))) {
    return reviewChoiceLabel(reviewChoiceOf(value as ReviewPolicy | null), t);
  }
  if (field === "output_classification_override" && value === null) {
    return t("flow_step_security_inherit");
  }
  if (field.endsWith("_contract") && isRecord(value) && isRecord(value.properties)) {
    return Object.keys(value.properties).join(", ");
  }
  if (isRecord(value)) return configLines(field, value, t);
  return plainText(value, t);
}

/**
 * The lines of a configuration that changed: a part that reads the same
 * before and after is left out, unless nothing that the card names differs.
 */
function changedLines(before: Shown, after: Shown): [Shown, Shown] {
  if (typeof before === "string" || typeof after === "string") return [before, after];
  const same = (line: Line, other: Line[]) =>
    other.some((item) => item.label === line.label && item.text === line.text);
  const keptBefore = before.filter((line) => !same(line, after));
  const keptAfter = after.filter((line) => !same(line, before));
  return keptBefore.length + keptAfter.length > 0 ? [keptBefore, keptAfter] : [before, after];
}

/** The lines a value folds to until "Visa hela", and the characters of text. */
const FOLDED_LINES = 4;
const FOLDED_CHARS = 200;

// ponytail: length heuristic, not a measurement; measure the clamp if a
// short value ever shows "Visa hela" without anything more to show.
function isLong(shown: Shown): boolean {
  return typeof shown === "string"
    ? shown.length > FOLDED_CHARS || shown.split("\n").length > FOLDED_LINES
    : shown.length > FOLDED_LINES;
}

function ShownValue({ shown, folded }: { shown: Shown; folded: boolean }) {
  const t = useTranslations();
  if (typeof shown === "string") {
    return (
      <span className={folded ? "line-clamp-4" : undefined}>
        <ReferenceText text={shown} />
      </span>
    );
  }
  // A configuration that only gained lines had none of them before.
  if (shown.length === 0) return <span>{t("flows_change_card_empty")}</span>;
  const lines = folded ? shown.slice(0, FOLDED_LINES) : shown;
  return (
    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
      {lines.map((line) => (
        <li key={line.label} className={folded ? "line-clamp-2" : undefined}>
          <ReferenceText
            text={t("flows_change_card_line", { label: line.label, value: line.text })}
          />
        </li>
      ))}
    </ul>
  );
}

/** One changed field, before and after, folded to a few lines with "Visa hela". */
function FieldChange({ field }: { field: ChangedField }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const key = FIELD_LABEL_KEYS[field.field];
  const [before, after] = changedLines(
    shownValue(field.field, field.before, t),
    shownValue(field.field, field.after, t)
  );
  const long = isLong(before) || isLong(after);
  const folded = long && !open;
  return (
    <li className="flex flex-col gap-1">
      <p className="text-ax-text-secondary m-0 text-xs font-semibold">
        {key ? t(key) : field.field}
      </p>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-ax-text-tertiary">{t("flows_change_card_before")}</dt>
        <dd className="text-ax-text-secondary m-0 min-w-0 break-words whitespace-pre-wrap">
          <ShownValue shown={before} folded={folded} />
        </dd>
        <dt className="text-ax-text-tertiary">{t("flows_change_card_after")}</dt>
        <dd className="text-ax-text m-0 min-w-0 break-words whitespace-pre-wrap">
          <ShownValue shown={after} folded={folded} />
        </dd>
      </dl>
      {long ? (
        <div>
          <Button
            size="sm"
            variant="ghost"
            label={open ? t("flows_change_card_show_less") : t("flows_change_card_show_all")}
            onClick={() => setOpen((value) => !value)}
          />
        </div>
      ) : null}
    </li>
  );
}

// Compact trigger rows, as the chat's activity disclosures have.
const CARD_COLLAPSIBLE_CLASS =
  "[&_.astryx-collapsible-trigger]:min-h-8 [&_.astryx-collapsible-trigger]:text-[13px] [&_.astryx-collapsible-trigger]:font-medium";

/**
 * What a change of the chat did to the flow, drawn in the answer where the
 * change was made and kept with the conversation: the steps it touched, and
 * for each field its value before and after, so the person sees what the
 * change covered without opening every step. One changed step opens at
 * once; several fold, one per step. Values read as the editor says them,
 * folded to a few lines with "Visa hela". "Visa steget" opens the step at
 * the changed field.
 */
export function FlowChangeCard({ steps }: { steps: ChangedStep[] }) {
  const t = useTranslations();
  const references = useFlowReferences();
  const label = t("flows_change_card_title", { count: steps.length });

  /**
   * Opens the step's editor at the first changed field the editor has a
   * place for; a change it has none for brings the step's card into view.
   */
  function showStep(step: ChangedStep) {
    if (!references) return;
    const saved = references.flow.steps.find((item) => item.id === step.stepId);
    const anchor = saved
      ? step.fields
          .map((field) => anchorForPath(field.field.replace(/^assistant\./, ""), saved))
          .find((found) => found !== null)
      : undefined;
    // onConnectStep opens a step's editor at a field, whichever field it is.
    if (anchor && references.onConnectStep) references.onConnectStep(step.stepId, anchor);
    else references.onShowStep(step.stepId);
  }

  return (
    <section
      aria-label={label}
      className="border-ax-border bg-ax-sunken rounded-ax-container flex w-full flex-col gap-3 border p-3.5 font-sans"
    >
      <div className="flex items-center gap-2.5">
        <IconTile size="sm" hue="blue" icon={<PencilLine className="size-4" />} />
        <h3 className="m-0 text-[13.5px] font-semibold">{label}</h3>
      </div>
      <div className={CARD_COLLAPSIBLE_CLASS}>
        {steps.map((step) => {
          const title = stepLabel({ user_description: step.name, step_order: step.stepOrder }, t);
          return (
            <Collapsible
              key={step.stepId}
              trigger={`${title} · ${t("flows_change_card_fields", { count: step.fields.length })}`}
              chevronPosition="start"
              defaultIsOpen={steps.length === 1}
            >
              <div className="flex flex-col gap-2.5 pb-2">
                <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
                  {step.fields.map((field) => (
                    <FieldChange key={field.field} field={field} />
                  ))}
                </ul>
                {references ? (
                  <div>
                    <Button
                      size="sm"
                      variant="ghost"
                      label={t("flows_change_card_show_step")}
                      onClick={() => showStep(step)}
                    />
                  </div>
                ) : null}
              </div>
            </Collapsible>
          );
        })}
      </div>
    </section>
  );
}

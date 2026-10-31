"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { PencilLine } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { IconTile } from "@/components/composites/icon-tile";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { stepLabel } from "../flow-labels";
import { isFlowsToolCall } from "./flows-tool-call";
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

/** The step and assistant fields the card can name; any other field shows by its own name. */
const FIELD_LABEL_KEYS: Record<string, string> = {
  user_description: "flows_change_field_user_description",
  input_source: "flows_change_field_input_source",
  input_type: "flows_change_field_input_type",
  input_contract: "flows_change_field_input_contract",
  input_config: "flows_change_field_input_config",
  input_bindings: "flows_change_field_input_bindings",
  output_mode: "flows_change_field_output_mode",
  output_type: "flows_change_field_output_type",
  output_contract: "flows_change_field_output_contract",
  output_config: "flows_change_field_output_config",
  output_classification_override: "flows_change_field_output_classification_override",
  review_policy: "flows_change_field_review_policy",
  timeout_seconds: "flows_change_field_timeout_seconds",
  "assistant.prompt": "flows_change_field_assistant_prompt",
  "assistant.name": "flows_change_field_assistant_name",
  "assistant.description": "flows_change_field_assistant_description",
  "assistant.completion_model": "flows_change_field_assistant_completion_model",
  "assistant.completion_model_kwargs": "flows_change_field_assistant_completion_model_kwargs",
  "assistant.attachments": "flows_change_field_assistant_attachments",
  "assistant.groups": "flows_change_field_assistant_groups",
  "assistant.websites": "flows_change_field_assistant_websites"
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

/** A changed value as the card shows it: text as it is, a number or flag as text, nothing as "(tomt)". */
function shownValue(value: unknown, t: ReturnType<typeof useTranslations>): string {
  if (value === null || value === undefined || value === "") return t("flows_change_card_empty");
  if (typeof value === "string") return value;
  if (typeof value === "boolean")
    return t(value ? "flows_change_card_yes" : "flows_change_card_no");
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

// Compact trigger rows, as the chat's activity disclosures have.
const CARD_COLLAPSIBLE_CLASS =
  "[&_.astryx-collapsible-trigger]:min-h-8 [&_.astryx-collapsible-trigger]:text-[13px] [&_.astryx-collapsible-trigger]:font-medium";

/**
 * What a change of the chat did to the flow, drawn in the answer where the
 * change was made and kept with the conversation: the steps it touched, and
 * for each field its value before and after, so the person sees what the
 * change covered without opening every step. One changed step opens at
 * once; several fold, one per step. "Visa steget" brings the step's card
 * into view when the page has it.
 */
export function FlowChangeCard({ steps }: { steps: ChangedStep[] }) {
  const t = useTranslations();
  const references = useFlowReferences();
  const label = t("flows_change_card_title", { count: steps.length });

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
                  {step.fields.map((field) => {
                    const key = FIELD_LABEL_KEYS[field.field];
                    return (
                      <li key={field.field} className="flex flex-col gap-1">
                        <p className="text-ax-text-secondary m-0 text-xs font-semibold">
                          {key ? t(key) : field.field}
                        </p>
                        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
                          <dt className="text-ax-text-tertiary">{t("flows_change_card_before")}</dt>
                          <dd className="text-ax-text-secondary m-0 line-clamp-4 break-words whitespace-pre-wrap">
                            {shownValue(field.before, t)}
                          </dd>
                          <dt className="text-ax-text-tertiary">{t("flows_change_card_after")}</dt>
                          <dd className="text-ax-text m-0 line-clamp-4 break-words whitespace-pre-wrap">
                            {shownValue(field.after, t)}
                          </dd>
                        </dl>
                      </li>
                    );
                  })}
                </ul>
                {references ? (
                  <div>
                    <Button
                      size="sm"
                      variant="ghost"
                      label={t("flows_change_card_show_step")}
                      onClick={() => references.onShowStep(step.stepId)}
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

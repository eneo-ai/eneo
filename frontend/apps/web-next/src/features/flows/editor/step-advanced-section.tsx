"use client";

import { NumberInput } from "@astryxdesign/core/NumberInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { executionLimitsQueryOptions } from "./editor-api";
import { Anchor, EditorSection, problemStatus } from "./editor-fields";
import type { FieldProblems } from "./field-problems";
import { isJsonObject, type JsonObject, type StepConfig } from "./step-types";

export type ContractField = "input_contract" | "output_contract";

/** JSON typed into a contract field, kept as text until it is a JSON object. */
export type ContractDrafts = Partial<Record<ContractField, string>>;

export function contractText(value: JsonObject | null): string {
  return value === null ? "" : JSON.stringify(value, null, 2);
}

/** The contract the text holds: null for empty text, undefined when it is not a JSON object. */
export function parseContract(text: string): JsonObject | null | undefined {
  if (!text.trim()) return null;
  try {
    const value: unknown = JSON.parse(text);
    return isJsonObject(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Settings for those who need them: the step's time budget and the JSON
 * schemas it checks what it reads and what it answers against.
 */
export function StepAdvancedSection({
  formId,
  sectionId,
  draft,
  onChange,
  drafts,
  onDraftsChange,
  problems
}: {
  formId: string;
  sectionId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  drafts: ContractDrafts;
  onDraftsChange: (drafts: ContractDrafts) => void;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const limits = useQuery(executionLimitsQueryOptions()).data;
  function contractField(field: ContractField, label: string, description: string) {
    const text = drafts[field] ?? contractText(draft[field]);
    const parsed = parseContract(text);
    return (
      <Anchor formId={formId} anchor={field}>
        <TextArea
          label={label}
          description={description}
          value={text}
          onChange={(next) => {
            const value = parseContract(next);
            onDraftsChange({ ...drafts, [field]: next });
            if (value !== undefined) onChange({ ...draft, [field]: value });
          }}
          rows={6}
          hasSpellCheck={false}
          isOptional
          className="font-mono"
          status={problemStatus(
            problems[field] ??
              (parsed === undefined ? t("flow_step_editor_contract_invalid") : null)
          )}
          width="100%"
        />
      </Anchor>
    );
  }

  return (
    <EditorSection
      id={sectionId}
      title={t("flow_step_editor_advanced_title")}
      description={t("flow_step_editor_advanced_description")}
    >
      <Anchor formId={formId} anchor="timeout_seconds">
        <NumberInput
          label={t("flow_step_editor_timeout")}
          description={[
            t("flow_step_editor_timeout_description"),
            limits
              ? t("flow_step_editor_timeout_max", { max: limits.max_step_timeout_seconds })
              : null
          ]
            .filter(Boolean)
            .join(" ")}
          value={draft.timeout_seconds}
          onChange={(value) =>
            onChange({
              ...draft,
              timeout_seconds: value === null || value === undefined || value <= 0 ? null : value
            })
          }
          min={1}
          max={limits?.max_step_timeout_seconds}
          isIntegerOnly
          hasClear
          isOptional
          units={t("flow_step_editor_seconds_unit")}
          placeholder={
            limits
              ? String(limits.default_step_timeout_seconds)
              : t("flow_step_editor_timeout_default")
          }
          status={problemStatus(problems.timeout_seconds)}
        />
      </Anchor>
      {contractField(
        "input_contract",
        t("flow_step_input_contract"),
        t("flow_step_editor_input_contract_description")
      )}
      {(draft.output_type === "json" || draft.output_contract !== null) &&
        contractField(
          "output_contract",
          t("flow_step_output_contract"),
          t("flow_step_editor_output_contract_description")
        )}
    </EditorSection>
  );
}

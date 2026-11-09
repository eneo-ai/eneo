import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { Collapsible } from "@/components/astryx/collapsible";
import { executionLimitsQueryOptions } from "./editor-api";
import { Anchor, problemStatus } from "./editor-fields";
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
 * schemas it checks what it reads and what it answers against. Folded while
 * none of them is set; it opens on what it holds, never on a remembered
 * choice: a setting in use, a contract accepted from an example or a problem
 * in it opens it (the problem before focus moves to its field).
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
  const texts = {
    input_contract: drafts.input_contract ?? contractText(draft.input_contract),
    output_contract: drafts.output_contract ?? contractText(draft.output_contract)
  };
  const inUse = [
    draft.timeout_seconds !== null,
    texts.input_contract.trim() !== "",
    texts.output_contract.trim() !== ""
  ].filter(Boolean).length;
  const hasProblem =
    (["timeout_seconds", "input_contract", "output_contract"] as const).some(
      (field) => problems[field]
    ) ||
    parseContract(texts.input_contract) === undefined ||
    parseContract(texts.output_contract) === undefined;
  const [isOpen, setIsOpen] = useState(inUse > 0 || hasProblem);
  // A problem that appears, or an output contract set from outside (accepted
  // from an example answer), opens it in the same render.
  const [seen, setSeen] = useState({ hasProblem, output: texts.output_contract });
  if (seen.hasProblem !== hasProblem || seen.output !== texts.output_contract) {
    setSeen({ hasProblem, output: texts.output_contract });
    if (hasProblem || texts.output_contract.trim() !== "") setIsOpen(true);
  }

  function contractField(field: ContractField, label: string, description: string) {
    const text = texts[field];
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
          controlClassName="font-mono"
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
    <section aria-labelledby={sectionId} className="border-ax-border border-t pt-3">
      <Collapsible
        isOpen={isOpen}
        onOpenChange={setIsOpen}
        chevronPosition="start"
        trigger={
          <span className="flex flex-col gap-0.5 py-1 text-start">
            <Text id={sectionId} type="large" weight="bold">
              {t("flow_step_editor_advanced_title")}
            </Text>
            <Text type="supporting" size="sm">
              {inUse > 0
                ? t("flow_step_editor_advanced_in_use", { count: inUse })
                : t("flow_step_editor_advanced_description")}
            </Text>
          </span>
        }
      >
        <div className="flex flex-col gap-4 pt-3">
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
                  timeout_seconds:
                    value === null || value === undefined || value <= 0 ? null : value
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
        </div>
      </Collapsible>
    </section>
  );
}

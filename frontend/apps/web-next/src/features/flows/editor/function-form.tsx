"use client";

import { Selector } from "@astryxdesign/core/Selector";
import { useTranslations } from "next-intl";
import { TextInput } from "@/components/astryx/text-input";
import { functionPurposeLabel } from "../flow-labels";
import type { FlowDefinition, FunctionStep } from "../types";
import {
  FilesFromField,
  JsonTextField,
  NameFields,
  problemStatus,
  TemplateHint,
  type FieldProblems
} from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

const PURPOSES: FunctionStep["purpose"][] = [
  "web_search",
  "image_generation",
  "file_analysis",
  "file_creation",
  "charts",
  "compute"
];

/** The form of a function step: the function and tool, its arguments as JSON, the files it may read. */
export function FunctionForm({
  draft,
  definition,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const step = draft.draft.step as FunctionStep;
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Selector
          label={t("flow_param_function")}
          options={PURPOSES.map((purpose) => ({
            value: purpose,
            label: functionPurposeLabel(purpose, t)
          }))}
          value={step.purpose}
          onChange={(purpose) => draft.update({ purpose: purpose as FunctionStep["purpose"] })}
          status={problemStatus(problems.purpose)}
        />
        <TextInput
          label={t("flow_editor_tool")}
          description={t("flow_editor_tool_hint")}
          value={step.tool}
          onChange={(tool) => draft.update({ tool: tool.trim() })}
          isRequired
          status={problemStatus(problems.tool)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <JsonTextField
          label={t("flow_param_arguments")}
          description={t("flow_editor_arguments_hint")}
          json={draft.draft.json.arguments}
          onChange={(text) => draft.setJson("arguments", text)}
          problem={problems.arguments}
        />
        <TemplateHint definition={definition} stepKey={step.key} />
      </div>
      <FilesFromField
        definition={definition}
        value={step.files_from ?? []}
        onChange={(files_from) => draft.update({ files_from })}
        problem={problems.files_from}
      />
    </>
  );
}

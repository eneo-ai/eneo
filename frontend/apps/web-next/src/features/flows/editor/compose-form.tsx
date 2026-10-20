"use client";

import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "next-intl";
import type { ComposeStep, FlowDefinition } from "../types";
import { NameFields, problemStatus, TemplateHint, type FieldProblems } from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

/** The form of a text step: one template over inputs and earlier steps. */
export function ComposeForm({
  draft,
  definition,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const step = draft.draft.step as ComposeStep;
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <div className="flex flex-col gap-1.5">
        <TextArea
          label={t("flow_param_template")}
          value={step.template}
          onChange={(template) => draft.update({ template })}
          rows={10}
          isRequired
          status={problemStatus(problems.template)}
          placeholder={t("flow_editor_template_placeholder")}
        />
        <TemplateHint definition={definition} stepKey={step.key} />
      </div>
    </>
  );
}

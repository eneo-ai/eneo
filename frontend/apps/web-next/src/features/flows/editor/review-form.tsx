"use client";

import { NumberInput } from "@astryxdesign/core/NumberInput";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { FlowDefinition, ReviewStep } from "../types";
import { EarlierStepSelector, NameFields, problemStatus, type FieldProblems } from "./step-fields";
import type { StepDraftState } from "./use-step-draft";

type Unit = "days" | "hours" | "minutes";
const SECONDS: Record<Unit, number> = { days: 86_400, hours: 3_600, minutes: 60 };

/** The largest unit that divides the limit evenly, so 7 days shows as 7 days. */
function unitOf(seconds: number | null | undefined): Unit {
  if (!seconds) return "days";
  if (seconds % SECONDS.days === 0) return "days";
  if (seconds % SECONDS.hours === 0) return "hours";
  return "minutes";
}

/**
 * The form of a review step: what the reviewer may do, which step's output
 * they see, and how long the run waits for the decision.
 */
export function ReviewForm({
  draft,
  definition,
  index,
  problems
}: {
  draft: StepDraftState;
  definition: FlowDefinition;
  /** The step's position; only earlier steps can be reviewed. */
  index: number;
  problems: FieldProblems;
}) {
  const t = useTranslations();
  const step = draft.draft.step as ReviewStep;
  const seconds = step.expires_after_seconds ?? null;
  const [unit, setUnit] = useState<Unit>(() => unitOf(seconds));
  const amount = seconds ? Math.round(seconds / SECONDS[unit]) : null;
  const setLimit = (nextAmount: number | null, nextUnit: Unit) => {
    setUnit(nextUnit);
    draft.update({
      expires_after_seconds:
        nextAmount && nextAmount > 0 ? Math.round(nextAmount * SECONDS[nextUnit]) : null
    });
  };
  return (
    <>
      <NameFields step={step} onChange={draft.update} problems={problems} />
      <EarlierStepSelector
        label={t("flow_section_reviews")}
        definition={definition}
        before={index}
        value={step.of ?? null}
        onChange={(of) => draft.update({ of })}
        problem={problems.of}
      />
      <RadioList
        label={t("flow_editor_review_mode")}
        value={step.mode ?? "edit"}
        onChange={(mode) => draft.update({ mode: mode === "view" ? "view" : "edit" })}
        status={problemStatus(problems.mode)}
      >
        <RadioListItem
          value="edit"
          label={t("flow_review_mode_edit_title")}
          description={t("flow_review_mode_edit_detail")}
        />
        <RadioListItem
          value="view"
          label={t("flow_review_mode_view_title")}
          description={t("flow_review_mode_view_detail")}
        />
      </RadioList>
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <NumberInput
          label={t("flow_param_time_limit")}
          description={t("flow_editor_time_limit_hint")}
          value={amount}
          onChange={(next) => setLimit(next, unit)}
          min={1}
          isIntegerOnly
          hasClear
          placeholder={t("flow_editor_time_limit_none")}
          status={problemStatus(problems.expires_after_seconds)}
        />
        <Selector
          label={t("flow_editor_time_unit")}
          options={[
            { value: "days", label: t("flow_editor_unit_days") },
            { value: "hours", label: t("flow_editor_unit_hours") },
            { value: "minutes", label: t("flow_editor_unit_minutes") }
          ]}
          value={unit}
          onChange={(next) => setLimit(amount, next as Unit)}
        />
      </div>
    </>
  );
}

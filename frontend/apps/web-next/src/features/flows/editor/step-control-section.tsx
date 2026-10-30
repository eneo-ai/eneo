"use client";

import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { useSpace } from "@/features/spaces/use-space";
import { knownClassifications, levelName } from "./classification-names";
import { Anchor, EditorSection, problemStatus } from "./editor-fields";
import { securityClassificationsQueryOptions } from "./editor-api";
import { describeSaveError, type FieldProblems } from "./field-problems";
import {
  reviewChoiceOf,
  reviewLocked,
  reviewSupported,
  withReviewChoice,
  withReviewExpiry,
  type ReviewChoice
} from "./step-configs";
import { reviewChoiceLabel, stepLabel } from "./step-labels";
import type { StepClassification, StepConfig } from "./step-types";

const INHERIT = "__inherit";
const HOUR = 3600;

function Review({
  formId,
  draft,
  onChange,
  problem
}: {
  formId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problem?: string;
}) {
  const t = useTranslations();
  const choice = reviewChoiceOf(draft.review_policy);
  const supported = reviewSupported(draft.output_mode);
  const locked = reviewLocked(draft.output_mode);
  const expires = draft.review_policy?.expires_after_seconds ?? null;
  return (
    <Anchor formId={formId} anchor="review_policy">
      <RadioList
        label={t("flow_step_review_policy")}
        description={t("flow_step_review_policy_desc")}
        value={choice}
        onChange={(value) =>
          onChange({
            ...draft,
            review_policy: withReviewChoice(draft.review_policy, value as ReviewChoice)
          })
        }
        isDisabled={!supported || locked}
        disabledMessage={
          locked
            ? t("flow_step_review_policy_speaker_mapping_locked")
            : !supported
              ? t("flow_step_review_policy_outbound_disabled")
              : undefined
        }
        status={problemStatus(problem)}
      >
        {(["none", "view", "edit"] as const).map((value) => (
          <RadioListItem key={value} value={value} label={reviewChoiceLabel(value, t)} />
        ))}
      </RadioList>
      {(locked || !supported) && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {locked
            ? t("flow_step_review_policy_speaker_mapping_locked")
            : t("flow_step_review_policy_outbound_disabled")}
        </Text>
      )}
      {choice !== "none" && (
        <NumberInput
          label={t("flow_step_editor_review_expiry")}
          description={t("flow_step_editor_review_expiry_description")}
          value={expires === null ? null : Math.round((expires / HOUR) * 100) / 100}
          onChange={(hours) =>
            onChange({
              ...draft,
              review_policy: withReviewExpiry(
                draft.review_policy,
                hours === null || hours === undefined || hours <= 0
                  ? null
                  : Math.round(hours * HOUR)
              )
            })
          }
          min={1}
          units={t("flow_step_editor_hours_unit")}
          placeholder={t("flow_step_editor_review_expiry_default")}
          hasClear
          isOptional
        />
      )}
    </Anchor>
  );
}

/**
 * The step's security classification as the core's rule judges the draft:
 * what its input carries, what its model must clear and what its result
 * carries. The override can raise the result's class, never lower it.
 */
function Classification({
  formId,
  draft,
  onChange,
  preview,
  problem
}: {
  formId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  preview: { data: StepClassification | null; isPending: boolean; error: unknown };
  problem?: string;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const listing = useQuery(securityClassificationsQueryOptions());
  // A member the list refuses still reads the names the space carries.
  const classifications = knownClassifications(listing.data?.items, space);
  const enabled = listing.data?.enabled ?? space.security_classification !== null;
  const facts = preview.data;
  const floor = facts?.output_floor ?? space.security_classification?.security_level ?? null;
  const override = draft.output_classification_override;
  const choices = classifications.filter((item) => floor === null || item.security_level >= floor);
  const options = [
    {
      value: INHERIT,
      label: space.security_classification
        ? t("flow_step_editor_classification_inherit_named", {
            name: space.security_classification.name
          })
        : t("flow_step_security_inherit")
    },
    ...choices.map((item) => ({ value: String(item.security_level), label: item.name })),
    ...(override !== null && !choices.some((item) => item.security_level === override)
      ? [{ value: String(override), label: levelName(override, classifications, t) }]
      : [])
  ];

  if (!enabled && override === null) {
    return (
      <Anchor formId={formId} anchor="output_classification_override">
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_classification_off")}
        </Text>
      </Anchor>
    );
  }

  return (
    <Anchor formId={formId} anchor="output_classification_override">
      {preview.isPending ? (
        <LoadingState label={t("flow_step_editor_classification_loading")} rows={2} />
      ) : preview.error ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_classification_unavailable", {
            reason: describeSaveError(preview.error, { stepId: "", stepOrder: 0, config: draft }, t)
              .message
          })}
        </Text>
      ) : facts ? (
        <MetadataList title={t("flow_step_editor_classification_facts")}>
          <MetadataListItem label={t("flow_step_editor_classification_input")}>
            {levelName(facts.input_level, classifications, t)}
          </MetadataListItem>
          {facts.reads.length > 0 && (
            <MetadataListItem label={t("flow_step_editor_classification_reads")}>
              {facts.reads.map((order) => stepLabel(order, null, t)).join(", ")}
            </MetadataListItem>
          )}
          {facts.knowledge_level !== null && (
            <MetadataListItem label={t("flow_step_editor_classification_knowledge")}>
              {levelName(facts.knowledge_level, classifications, t)}
            </MetadataListItem>
          )}
          {facts.external_source_level !== null && (
            <MetadataListItem label={t("flow_step_editor_classification_tool_server")}>
              {levelName(facts.external_source_level, classifications, t)}
            </MetadataListItem>
          )}
          {facts.required_model_level !== null && (
            <MetadataListItem label={t("flow_step_editor_classification_model_required")}>
              {levelName(facts.required_model_level, classifications, t)}
            </MetadataListItem>
          )}
          <MetadataListItem label={t("flow_step_editor_classification_output")}>
            {levelName(facts.effective_output_level, classifications, t)}
          </MetadataListItem>
        </MetadataList>
      ) : null}
      {facts?.violation && (
        <Text type="supporting" size="sm" as="p" display="block" className="text-ax-error m-0">
          {t.has(`flow_error_${facts.violation.code}`)
            ? t(`flow_error_${facts.violation.code}`)
            : facts.violation.message}
        </Text>
      )}
      <Selector
        label={t("flow_step_security_classification")}
        description={t("flow_step_editor_classification_override_description")}
        options={options}
        value={override === null ? INHERIT : String(override)}
        onChange={(value) =>
          onChange({
            ...draft,
            output_classification_override: value === INHERIT ? null : Number(value)
          })
        }
        status={problemStatus(problem)}
        width="100%"
      />
    </Anchor>
  );
}

/** Review after the step, and the classification its result carries. */
export function StepControlSection({
  formId,
  sectionId,
  draft,
  onChange,
  problems,
  preview
}: {
  formId: string;
  sectionId: string;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
  preview: { data: StepClassification | null; isPending: boolean; error: unknown };
}) {
  const t = useTranslations();
  return (
    <EditorSection id={sectionId} title={t("flow_step_editor_control_title")}>
      <Review formId={formId} draft={draft} onChange={onChange} problem={problems.review_policy} />
      <Classification
        formId={formId}
        draft={draft}
        onChange={onChange}
        preview={preview}
        problem={problems.output_classification_override}
      />
    </EditorSection>
  );
}

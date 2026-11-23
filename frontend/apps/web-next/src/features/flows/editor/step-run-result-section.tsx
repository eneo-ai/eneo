import { Button } from "@astryxdesign/core/Button";
import { HStack } from "@astryxdesign/core/HStack";
import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useTranslations } from "use-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { flowDeliverables } from "../flow-deliverables";
import type { FlowStep } from "../flows-api";
import { Anchor, EditorSection, TemplateScope } from "./editor-fields";
import type { FieldProblems } from "./field-problems";
import { readDeliverable, readHttpConfig } from "./step-configs";
import { HttpFields } from "./step-http-fields";
import { outputTypeLabel } from "./step-labels";
import { applyHttpOutputChange } from "./step-rules";
import type { FlowPublic, StepConfig } from "./step-types";
import { variableGroups } from "./step-variables";

/** The id of the button in "Vad som skickas" that opens `stepId`. */
export function openStepButtonId(formId: string, stepId: string): string {
  return `${formId}-open-${stepId}`;
}

/** The id of the "Vad som skickas" heading, which takes focus when no button can. */
export function sendsHeadingId(formId: string): string {
  return `${formId}-sends`;
}

/**
 * What the step that sends the run's result sends, in step order, and to
 * whom. It sends nothing of its own: the steps the run delivers are chosen
 * on them (`flowDeliverables`), so this view lists them and opens them.
 * While the form holds edits on an older version than the newest
 * (`olderVersion`), the list, its buttons and the add are not shown: they
 * come from the other steps, which the newest may have moved or removed.
 * The receiver is the step's own and stays.
 */
export function StepRunResultSections({
  formId,
  flow,
  stepId,
  stepOrder,
  draft,
  onChange,
  problems,
  onGoStep,
  onAddStepBefore,
  olderVersion
}: {
  formId: string;
  flow: FlowPublic;
  stepId: string;
  stepOrder: number;
  draft: StepConfig;
  onChange: (next: StepConfig) => void;
  problems: FieldProblems;
  /** Opens another step of the flow; absent, no step is offered to open. */
  onGoStep?: (stepId: string) => void;
  /** Adds a step right before the step that sends; absent, it is not offered. */
  onAddStepBefore?: () => void;
  /** The form holds unsaved edits on an older version of the flow than the newest. */
  olderVersion: boolean;
}) {
  const t = useTranslations();
  const run = flowDeliverables(
    flow.steps.map((step) => (step.id === stepId ? { ...step, ...draft } : step))
  );
  const name = (step: Pick<FlowStep, "user_description">) =>
    step.user_description?.trim() || t("flow_step_editor_unnamed");
  const openLabel = (step: FlowStep) =>
    t("flow_step_editor_run_result_open_step", { order: step.step_order, name: name(step) });
  // A step that could be sent has no row of its own: its button names it.
  const openButton = ({ id, ...step }: FlowStep) => {
    if (!onGoStep || !id) return null;
    const label = openLabel({ id, ...step });
    return (
      <Button
        key={id}
        id={openStepButtonId(formId, id)}
        label={label}
        size="sm"
        variant="ghost"
        // A long step name is cut to the width; the tooltip shows all of it.
        tooltip={label}
        onClick={() => onGoStep(id)}
      />
    );
  };
  // Laid out in the section's own width, so a long name is cut, not pushed out.
  const openButtons = (steps: readonly FlowStep[], justify?: "center") => (
    <HStack gap={2} wrap="wrap" justify={justify}>
      {steps.map(openButton)}
    </HStack>
  );

  return (
    <>
      <EditorSection
        id={sendsHeadingId(formId)}
        title={t("flow_step_editor_run_result_sends_title")}
        isFocusTarget
      >
        {olderVersion ? (
          <Text type="supporting" size="sm" as="p" display="block" className="m-0 max-w-prose">
            {t("flow_step_editor_run_result_older_version")}
          </Text>
        ) : run.deliverables.length > 0 ? (
          <VStack gap={4}>
            <List hasDividers density="compact" edge="flush">
              {run.deliverables.map((step) => (
                <ListItem
                  key={step.id}
                  // Nodes, not strings: a long name wraps instead of being cut.
                  label={<Text>{readDeliverable(step.output_config)?.label || name(step)}</Text>}
                  description={
                    <Text type="supporting" size="sm">
                      {t("flow_step_editor_run_result_row", {
                        order: step.step_order,
                        type: outputTypeLabel(step.output_type, t)
                      })}
                    </Text>
                  }
                  // The row names the result and its step: the button only says
                  // "Öppna", and its full name starts with that word (WCAG 2.5.3).
                  endContent={
                    onGoStep && step.id ? (
                      <Button
                        id={openStepButtonId(formId, step.id)}
                        label={t("flow_step_editor_run_result_open")}
                        aria-label={openLabel(step)}
                        size="sm"
                        variant="secondary"
                        onClick={() => onGoStep(step.id!)}
                      />
                    ) : undefined
                  }
                />
              ))}
            </List>
            {run.candidates.length > 0 && (
              <VStack gap={2}>
                <Text type="label" as="p" display="block" className="m-0">
                  {t("flow_step_editor_run_result_more_title")}
                </Text>
                {openButtons(run.candidates)}
              </VStack>
            )}
          </VStack>
        ) : (
          // Nothing is a warning yet: a step just added has nothing before it to send.
          <VStack gap={3}>
            <EmptyState
              title={t("flow_step_editor_run_result_empty_title")}
              description={t(
                run.candidates.length > 0
                  ? "flow_step_editor_run_result_empty_candidates"
                  : "flow_step_editor_run_result_empty_none"
              )}
              headingLevel={4}
              isCompact
              // Part of the step's settings, not news: nothing to announce.
              isAnnounced={false}
              actions={
                run.candidates.length === 0 &&
                onAddStepBefore && (
                  <Button
                    label={t("flow_step_editor_run_result_add_before")}
                    size="sm"
                    variant="secondary"
                    onClick={onAddStepBefore}
                  />
                )
              }
            />
            {/* Below the frame, whose actions row takes its content's width. */}
            {run.candidates.length > 0 && onGoStep && openButtons(run.candidates, "center")}
          </VStack>
        )}
      </EditorSection>

      <EditorSection
        id={`${formId}-receiver`}
        title={t("flow_step_editor_run_result_receiver_title")}
      >
        <Anchor formId={formId} anchor="output_config.http">
          {/* Its headers are read when the result is sent; the step itself holds nothing to read. */}
          <TemplateScope value={{ flow, stepOrder }}>
            <HttpFields
              formId={formId}
              flowId={flow.id}
              stepId={stepId}
              direction="output"
              config={readHttpConfig(draft.output_config, "output")}
              onChange={(http) => onChange(applyHttpOutputChange(draft, http))}
              groups={variableGroups({ flow, stepOrder })}
              problems={problems}
            />
          </TemplateScope>
        </Anchor>
      </EditorSection>
    </>
  );
}

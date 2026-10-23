"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { Heading } from "@astryxdesign/core/Heading";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Token } from "@astryxdesign/core/Token";
import { ArrowDown, ArrowUp, Ellipsis, Lightbulb, Plus, Workflow } from "lucide-react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { flowAssistantQueryOptions } from "./editor/editor-api";
import { stepUsesModel } from "./editor/step-rules";
import type { FlowStep } from "./flows-api";
import { inputTypeLabel, producesLabel, readLabel, stepLabel } from "./flow-labels";
import { stepName, stepReaders, stepReads, type StepPrompts } from "./flow-steps";
import {
  flowSuggestionsQueryOptions,
  shownSuggestions,
  suggestionCounts
} from "./flow-suggestions";

/** The id of a step's control, so focus can be put back on it after the list re-renders. */
export function stepControlId(stepId: string, control: "open" | "up" | "down"): string {
  return `flow-step-${stepId}-${control}`;
}

type StepActions = {
  onOpen: (step: FlowStep) => void;
  onMove: (step: FlowStep, delta: -1 | 1) => void;
  /** Resolves once the removal is saved or refused. */
  onRemove: (step: FlowStep) => Promise<unknown>;
  /** Opens the add dialog for a 1-based position. */
  onAdd: (position: number) => void;
};

/** The shortcut that adds a step naming the speakers after the step that transcribes. */
export type SpeakerStepOffer = { stepId: string; pending: boolean; onAccept: () => void };

function StepCard({
  step,
  steps,
  prompts,
  index,
  canEdit,
  suggestionCount,
  speakerOffer,
  actions
}: {
  step: FlowStep;
  steps: readonly FlowStep[];
  prompts: StepPrompts;
  index: number;
  canEdit: boolean;
  /** How many of the core's suggestions are about this step. */
  suggestionCount: number;
  speakerOffer: SpeakerStepOffer | null;
  actions: StepActions & { onAskRemove: (step: FlowStep) => void };
}) {
  const t = useTranslations();
  const titleId = useId();
  const id = step.id ?? "";
  const label = stepLabel(step, t);
  const reads = stepReads(step, steps, prompts);
  const review = step.review_policy?.mode;

  return (
    <article
      aria-labelledby={titleId}
      className="border-ax-border bg-ax-card rounded-ax-container flex flex-col gap-3 border p-4"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-[1_1_14rem] flex-col gap-1">
          <Heading level={3} id={titleId} weight="semibold" wordBreak="break-word">
            <span className="text-ax-text-secondary block text-xs font-medium">
              {t("flows_step_label_unnamed", { order: step.step_order })}
            </span>
            <span className="text-base">{stepName(step) ?? t("flows_step_unnamed")}</span>
          </Heading>
          {review || suggestionCount > 0 ? (
            <span className="flex flex-wrap gap-1">
              {review ? (
                <Badge
                  variant="warning"
                  label={review === "edit" ? t("flows_review_edit") : t("flows_review_view")}
                />
              ) : null}
              {suggestionCount > 0 ? (
                <Badge
                  variant="neutral"
                  icon={<Lightbulb aria-hidden="true" className="size-3" />}
                  label={
                    <>
                      <span aria-hidden="true">
                        {t("flow_suggestion_marker", { count: suggestionCount })}
                      </span>
                      <span className="sr-only">
                        {t("flow_suggestion_marker_named", { count: suggestionCount, step: label })}
                      </span>
                    </>
                  }
                />
              ) : null}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <Button
            id={stepControlId(id, "open")}
            label={canEdit ? t("flows_step_open_edit") : t("flows_step_open_view")}
            aria-label={
              canEdit
                ? t("flows_step_open_edit_named", { step: label })
                : t("flows_step_open_view_named", { step: label })
            }
            size="sm"
            onClick={() => actions.onOpen(step)}
          />
          {canEdit ? (
            <>
              <IconButton
                id={stepControlId(id, "up")}
                label={t("flows_step_move_up", { step: label })}
                icon={<ArrowUp aria-hidden="true" />}
                variant="ghost"
                size="sm"
                isDisabled={index === 0}
                onClick={() => actions.onMove(step, -1)}
              />
              <IconButton
                id={stepControlId(id, "down")}
                label={t("flows_step_move_down", { step: label })}
                icon={<ArrowDown aria-hidden="true" />}
                variant="ghost"
                size="sm"
                isDisabled={index === steps.length - 1}
                onClick={() => actions.onMove(step, 1)}
              />
              <DropdownMenu
                placement="below"
                alignment="end"
                hasChevron={false}
                button={{
                  label: t("flows_step_more", { step: label }),
                  variant: "ghost",
                  size: "sm",
                  icon: <Ellipsis aria-hidden="true" />,
                  isIconOnly: true
                }}
                items={[
                  {
                    id: "before",
                    label: t("flows_step_add_before"),
                    onClick: () => actions.onAdd(step.step_order)
                  },
                  {
                    id: "after",
                    label: t("flows_step_add_after"),
                    onClick: () => actions.onAdd(step.step_order + 1)
                  },
                  { type: "divider" },
                  {
                    id: "remove",
                    label: t("flows_step_remove"),
                    variant: "destructive",
                    onClick: () => actions.onAskRemove(step)
                  }
                ]}
              />
            </>
          ) : null}
        </div>
      </div>
      <MetadataList label={{ position: "start", width: "7rem" }}>
        <MetadataListItem label={t("flows_step_reads")}>
          <span className="flex flex-wrap gap-1">
            {reads.map((read) => (
              <Token
                key={read.kind === "step" ? `step-${read.order}` : read.kind}
                size="sm"
                color={read.kind === "step" && read.step === null ? "red" : "default"}
                label={readLabel(read, t)}
              />
            ))}
          </span>
        </MetadataListItem>
        <MetadataListItem label={t("flows_step_takes")}>
          {inputTypeLabel(step.input_type, t)}
        </MetadataListItem>
        <MetadataListItem label={t("flows_step_produces")}>
          {producesLabel(step, t)}
        </MetadataListItem>
      </MetadataList>
      {speakerOffer && speakerOffer.stepId === step.id ? (
        <QuietBanner
          status="info"
          title={t("flows_speaker_offer_title")}
          description={t("flows_speaker_offer_description")}
          collapsible={false}
          endContent={
            <Button
              label={t("flows_add_step")}
              aria-label={t("flows_speaker_offer_add", { step: label })}
              size="sm"
              isLoading={speakerOffer.pending}
              isInterruptible
              onClick={() => {
                if (!speakerOffer.pending) speakerOffer.onAccept();
              }}
            />
          }
        />
      ) : null}
    </article>
  );
}

/** The prompts of the flow's AI steps, read through the step assistants as they arrive. */
function useStepPrompts(flowId: string, steps: readonly FlowStep[]): StepPrompts {
  const assistants = useQueries({
    queries: steps
      .filter((step) => stepUsesModel(step))
      .map((step) => flowAssistantQueryOptions(flowId, step.assistant_id))
  });
  return new Map(
    assistants.flatMap((query) =>
      query.data ? [[query.data.id, query.data.prompt?.text ?? ""] as [string, string]] : []
    )
  );
}

/**
 * The flow's steps in run order, each with what it reads (its material and
 * its prompt), what it takes and what it produces. Editors open a step, move it up or down with buttons
 * (there is no drag), add a step before or after it and remove it after a
 * confirmation that names the steps that read it. After the step that
 * transcribes, `speakerOffer` offers the step that names the speakers. For
 * editors, a step the core has suggestions about carries a quiet marker with
 * their count; it reads the draft check's query (same key, one request).
 */
export function FlowStepList({
  flowId,
  draftRevision,
  steps,
  canEdit,
  headingRef,
  speakerOffer = null,
  ...actions
}: StepActions & {
  flowId: string;
  /** The draft revision on screen, which keys the suggestions. */
  draftRevision: number;
  steps: readonly FlowStep[];
  canEdit: boolean;
  headingRef: React.Ref<HTMLHeadingElement>;
  speakerOffer?: SpeakerStepOffer | null;
}) {
  const t = useTranslations();
  const headingId = useId();
  const [removing, setRemoving] = useState<FlowStep | null>(null);
  const [removePending, setRemovePending] = useState(false);
  const prompts = useStepPrompts(flowId, steps);
  const suggestions = useQuery({
    ...flowSuggestionsQueryOptions(flowId, draftRevision),
    enabled: canEdit
  });
  const counts = canEdit
    ? suggestionCounts(shownSuggestions(suggestions.data?.items, steps))
    : new Map<string, number>();
  const readers = removing ? stepReaders(removing, steps, prompts) : [];

  const addButton = (
    <Button
      label={t("flows_add_step")}
      icon={<Plus aria-hidden="true" />}
      size="sm"
      onClick={() => actions.onAdd(steps.length + 1)}
    />
  );

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Heading
          level={2}
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          weight="semibold"
          className="focus-visible:outline-ring rounded-ax-inner text-lg focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("flows_steps_heading")}
        </Heading>
        {canEdit && steps.length > 0 ? addButton : null}
      </div>
      {steps.length === 0 ? (
        <EmptyState
          icon={<Workflow />}
          hue="purple"
          headingLevel={3}
          isCompact
          title={t("flows_steps_empty_title")}
          description={
            canEdit ? t("flows_steps_empty_description") : t("flows_steps_empty_read_only")
          }
          actions={canEdit ? addButton : undefined}
        />
      ) : (
        <ol className="flex flex-col gap-2">
          {steps.map((step, index) => (
            <li key={step.id ?? step.step_order}>
              <StepCard
                step={step}
                steps={steps}
                prompts={prompts}
                index={index}
                canEdit={canEdit}
                suggestionCount={step.id ? (counts.get(step.id) ?? 0) : 0}
                speakerOffer={speakerOffer}
                actions={{ ...actions, onAskRemove: setRemoving }}
              />
            </li>
          ))}
        </ol>
      )}
      <ConfirmDialogControlled
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("flows_remove_step_title")}
        description={
          removing === null
            ? ""
            : readers.length > 0
              ? t("flows_remove_step_read_by", {
                  step: stepLabel(removing, t),
                  readers: readers.map((reader) => stepLabel(reader, t)).join(", ")
                })
              : t("flows_remove_step_description", { step: stepLabel(removing, t) })
        }
        confirmLabel={t("flows_step_remove")}
        variant="destructive"
        pending={removePending}
        onConfirm={() => {
          if (!removing) return;
          setRemovePending(true);
          // The dialog stays until the core has answered; a refusal is shown
          // above the definition.
          void actions.onRemove(removing).finally(() => {
            setRemovePending(false);
            setRemoving(null);
          });
        }}
      />
    </section>
  );
}

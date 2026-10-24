"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { Heading } from "@astryxdesign/core/Heading";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Token } from "@astryxdesign/core/Token";
import { ArrowDown, ArrowUp, Ellipsis, Plus, Workflow } from "lucide-react";
import { useQueries } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { flowAssistantQueryOptions } from "./editor/editor-api";
import { stepUsesModel } from "./editor/step-rules";
import type { FlowStep } from "./flows-api";
import type { StepChange } from "./flow-changes";
import { inputTypeLabel, producesLabel, readLabel, stepLabel } from "./flow-labels";
import { stepName, stepReaders, stepReads, type StepPrompts } from "./flow-steps";

/** The id of a step's control, so focus can be put back on it after the list re-renders. */
export function stepControlId(stepId: string, control: "open" | "up" | "down"): string {
  return `flow-step-${stepId}-${control}`;
}

export function stepCardId(stepId: string): string {
  return `flow-step-${stepId}`;
}

/**
 * Brings a step's card into view and marks it for a moment, for a pill in
 * the chat that names the step. Focus stays where it is. False when the
 * card is not on the page (the step list is on another tab on a phone).
 */
export function showStepCard(stepId: string): boolean {
  const card = document.getElementById(stepCardId(stepId));
  if (!card) return false;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  card.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
  card.setAttribute("data-highlight", "");
  window.setTimeout(() => card.removeAttribute("data-highlight"), 1800);
  return true;
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
  speakerOffer,
  change,
  actions
}: {
  step: FlowStep;
  steps: readonly FlowStep[];
  prompts: StepPrompts;
  index: number;
  canEdit: boolean;
  speakerOffer: SpeakerStepOffer | null;
  /** What the chat just did to this step, while the mark lasts. */
  change: StepChange | null;
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
      id={stepCardId(id)}
      aria-labelledby={titleId}
      data-highlight={change ? "" : undefined}
      // Named for the view transition that moves, shows and hides the cards
      // when the chat's tools change the flow.
      style={id ? { viewTransitionName: `flow-step-${id}` } : undefined}
      className="border-ax-border bg-ax-card rounded-ax-container data-[highlight]:border-ax-accent flex flex-col gap-3 border p-4 transition-colors"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-[1_1_14rem] flex-col gap-1">
          <Heading level={3} id={titleId} weight="semibold" wordBreak="break-word">
            <span className="text-ax-text-secondary block text-xs font-medium">
              {t("flows_step_label_unnamed", { order: step.step_order })}
            </span>
            <span className="text-base">{stepName(step) ?? t("flows_step_unnamed")}</span>
          </Heading>
          {review || change ? (
            <span className="flex flex-wrap gap-1.5">
              {review ? (
                <Badge
                  variant="warning"
                  label={review === "edit" ? t("flows_review_edit") : t("flows_review_view")}
                />
              ) : null}
              {change ? (
                <Token
                  size="sm"
                  color="blue"
                  label={t(`flows_step_change_${change}`)}
                  className="motion-safe:animate-in motion-safe:fade-in"
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
        <Banner
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

/**
 * The prompts of the flow's AI steps, read through the step assistants as
 * they arrive. Only an editor may read the assistants (`enabled`).
 */
function useStepPrompts(flowId: string, steps: readonly FlowStep[], enabled: boolean): StepPrompts {
  const assistants = useQueries({
    queries: steps
      .filter((step) => stepUsesModel(step))
      .map((step) => ({ ...flowAssistantQueryOptions(flowId, step.assistant_id), enabled }))
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
 * transcribes, `speakerOffer` offers the step that names the speakers.
 */
export function FlowStepList({
  flowId,
  steps,
  canEdit,
  mayEdit,
  headingRef,
  speakerOffer = null,
  changes = null,
  ...actions
}: StepActions & {
  flowId: string;
  steps: readonly FlowStep[];
  canEdit: boolean;
  /** The caller may edit the flow, published or not: only then are the prompts read. */
  mayEdit: boolean;
  headingRef: React.Ref<HTMLHeadingElement>;
  speakerOffer?: SpeakerStepOffer | null;
  /** The steps the chat just added, changed or moved, by id, while the mark lasts. */
  changes?: ReadonlyMap<string, StepChange> | null;
}) {
  const t = useTranslations();
  const headingId = useId();
  const [removing, setRemoving] = useState<FlowStep | null>(null);
  const [removePending, setRemovePending] = useState(false);
  const prompts = useStepPrompts(flowId, steps, mayEdit);
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
                speakerOffer={speakerOffer}
                change={(step.id && changes?.get(step.id)) || null}
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

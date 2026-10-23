"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { ReferenceText } from "./chat/reference-text";
import type { FlowPublic, FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import {
  FlowSuggestionItem,
  useSuggestionFix,
  type SuggestionActions,
  type SuggestionFix
} from "./flow-suggestion-item";
import {
  flowSuggestionsQueryOptions,
  isPatchable,
  shownSuggestions,
  suggestionText,
  type FlowSuggestion,
  type ShownSuggestion
} from "./flow-suggestions";

type ListActions = Pick<SuggestionActions, "onAskChat" | "onRemoveStep" | "fixBlockedBy"> & {
  /** Fixes the suggestions by fingerprint (see `useSuggestionFix`). */
  onFix?: (fingerprints: string[]) => void;
  fixPending?: boolean;
};

/** The suggestions of one step (or of the run form), as a list. */
function SuggestionList({
  items,
  steps,
  onAskChat,
  onFix,
  fixPending,
  fixBlockedBy,
  onRemoveStep
}: ListActions & {
  items: readonly { suggestion: FlowSuggestion; step: FlowStep | null }[];
  steps: readonly FlowStep[];
}) {
  return (
    <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {items.map(({ suggestion, step }) => (
        <FlowSuggestionItem
          key={suggestion.fingerprint}
          suggestion={suggestion}
          step={step}
          steps={steps}
          onAskChat={onAskChat}
          onFix={onFix ? (item) => onFix([item.fingerprint]) : undefined}
          fixPending={fixPending}
          fixBlockedBy={fixBlockedBy}
          onRemoveStep={onRemoveStep}
        />
      ))}
    </ul>
  );
}

/**
 * A step card's suggestions, below what the step reads and produces: the
 * step's own, with their actions. Nothing is rendered while it has none.
 */
export function StepCardSuggestions({
  items,
  steps,
  ...actions
}: ListActions & { items: readonly ShownSuggestion[]; steps: readonly FlowStep[] }) {
  const t = useTranslations();
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border flex flex-col gap-2 border-t pt-3"
    >
      <Heading level={4} id={headingId} weight="semibold" className="text-sm">
        {t("flow_suggestions_heading", { count: items.length })}
      </Heading>
      <SuggestionList items={items} steps={steps} {...actions} />
    </section>
  );
}

/**
 * The top of the step list while the core has suggestions: how many there
 * are, "Åtgärda alla" for those with a patch (after a confirmation that
 * lists them step by step), and the suggestions about the run form, which
 * no step card can hold. Nothing is rendered while there are none.
 */
export function SuggestionsSummary({
  shown,
  formItems,
  steps,
  fix,
  onAskChat,
  rescueTarget
}: {
  /** The suggestions on the step cards. */
  shown: readonly ShownSuggestion[];
  /** The suggestions about the run form (an unused field). */
  formItems: readonly FlowSuggestion[];
  steps: readonly FlowStep[];
  fix?: SuggestionFix;
  onAskChat?: (text: string) => void;
  /** Where focus goes once fixed suggestions have left the page. */
  rescueTarget: () => HTMLElement | null;
}) {
  const t = useTranslations();
  const [confirming, setConfirming] = useState(false);
  const runFix = useSuggestionFix(fix, rescueTarget);
  const count = shown.length + formItems.length;
  if (count === 0) return null;

  const patchable = [
    ...shown.filter(({ suggestion }) => isPatchable(suggestion)),
    ...formItems.filter(isPatchable).map((suggestion) => ({ suggestion, step: null }))
  ];
  // What "Åtgärda alla" changes, by step in run order, the run form last.
  const byStep = new Map<string, { step: FlowStep | null; titles: string[] }>();
  for (const { suggestion, step } of patchable) {
    const key = step?.id ?? "";
    const group = byStep.get(key) ?? { step, titles: [] };
    group.titles.push(suggestionText(suggestion, t, step ?? undefined, steps).title);
    byStep.set(key, group);
  }
  const groups = [...byStep.values()].sort(
    (left, right) =>
      (left.step?.step_order ?? Number.MAX_SAFE_INTEGER) -
      (right.step?.step_order ?? Number.MAX_SAFE_INTEGER)
  );

  return (
    <>
      <Banner
        status="info"
        title={t("flow_suggestions_summary", { count })}
        description={t("flow_suggestions_summary_description")}
        collapsible={false}
        endContent={
          runFix && patchable.length > 0 ? (
            <Button
              label={t("flow_suggestions_fix_all", { count: patchable.length })}
              size="sm"
              icon={<Wrench aria-hidden="true" className="size-4" />}
              isLoading={fix?.pending}
              isInterruptible
              onClick={() => {
                if (!fix?.pending) setConfirming(true);
              }}
            />
          ) : undefined
        }
      >
        {formItems.length > 0 ? (
          <SuggestionList
            items={formItems.map((suggestion) => ({ suggestion, step: null }))}
            steps={steps}
            onAskChat={onAskChat}
            onFix={runFix}
            fixPending={fix?.pending}
          />
        ) : null}
      </Banner>
      {runFix ? (
        <ConfirmDialogControlled
          open={confirming}
          onOpenChange={setConfirming}
          title={t("flow_suggestions_fix_all_title", { count: patchable.length })}
          description={t("flow_suggestions_fix_all_description")}
          confirmLabel={t("flow_suggestions_fix_all_confirm")}
          variant="default"
          pending={fix?.pending}
          onConfirm={() => {
            setConfirming(false);
            runFix(patchable.map(({ suggestion }) => suggestion.fingerprint));
          }}
        >
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {groups.map(({ step, titles }) => (
              <li key={step?.id ?? "form"} className="flex flex-col gap-1">
                <span className="text-ax-text text-sm font-semibold">
                  {step ? stepLabel(step, t) : t("flow_suggestions_fix_all_form")}
                </span>
                <ul className="text-ax-text m-0 flex list-disc flex-col gap-1 pl-5 text-sm leading-7">
                  {titles.map((title, index) => (
                    <li key={index}>
                      <ReferenceText text={title} interactive={false} />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </ConfirmDialogControlled>
      ) : null}
    </>
  );
}

/**
 * The open step's suggestions at the top of the step editor, which takes
 * the step list's place while a step is open: compact, with the same
 * actions as the step's card. It reads the same query as the step list.
 * Nothing is rendered while the step has none, or while they load or fail
 * (the step list says so).
 */
export function StepSuggestions({
  flow,
  stepId,
  onAskChat,
  fix,
  fixBlocked = false,
  rescueTarget
}: {
  flow: FlowPublic;
  stepId: string;
  onAskChat?: (text: string) => void;
  fix?: SuggestionFix;
  /**
   * The editor has unsaved changes: a fix would be made on the saved draft
   * beneath them, so "Åtgärda" waits, and says why, until they are saved or
   * undone.
   */
  fixBlocked?: boolean;
  /** Where focus goes once a fixed suggestion has left the editor. */
  rescueTarget: () => HTMLElement | null;
}) {
  const t = useTranslations();
  const headingId = useId();
  const blockedId = useId();
  const query = useQuery(flowSuggestionsQueryOptions(flow.id, flow.draft_revision));
  const runFix = useSuggestionFix(fix, rescueTarget);
  const shown = shownSuggestions(query.data?.items, flow.steps).filter(
    ({ step }) => step.id === stepId
  );
  if (shown.length === 0) return null;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <Banner
        status="info"
        title={
          <Heading level={3} id={headingId} weight="semibold" className="text-sm">
            {t("flow_suggestions_step_heading", { count: shown.length })}
          </Heading>
        }
        description={
          runFix && fixBlocked && shown.some(({ suggestion }) => isPatchable(suggestion)) ? (
            <span id={blockedId}>{t("flow_suggestions_fix_blocked_unsaved")}</span>
          ) : undefined
        }
        collapsible={false}
      >
        <SuggestionList
          items={shown}
          steps={flow.steps}
          onAskChat={onAskChat}
          onFix={runFix}
          fixPending={fix?.pending}
          fixBlockedBy={fixBlocked ? blockedId : undefined}
        />
      </Banner>
    </section>
  );
}

"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { List } from "@astryxdesign/core/List";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, History, Lightbulb, Undo2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useId, useState, type ReactNode } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { ReferenceText } from "./chat/reference-text";
import type { FlowPublic, FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import {
  SuggestionRow,
  useSuggestionFix,
  type SuggestionActions,
  type SuggestionFix
} from "./flow-suggestion-item";
import {
  flowSuggestionsQueryOptions,
  inSuggestionOrder,
  isPatchable,
  measuredBasisText,
  shownSuggestions,
  suggestionText,
  type FlowSuggestion,
  type FlowSuggestionRuns,
  type ShownSuggestion
} from "./flow-suggestions";

type ListActions = Pick<SuggestionActions, "onAskChat" | "onRemoveStep" | "fixBlockedBy"> & {
  /** Fixes the suggestions by fingerprint (see `useSuggestionFix`). */
  onFix?: (fingerprints: string[]) => void;
  fixPending?: boolean;
};

/**
 * Which disclosures are open, by key (a step's list by `step:<id>`, a row
 * by its fingerprint). Held by the component that outlives the cards, so a
 * refetch or a fix that re-renders a card keeps what the person opened.
 */
export type OpenKeys = {
  isOpen: (key: string) => boolean;
  setOpen: (key: string, open: boolean) => void;
};

export function useOpenKeys(openByDefault = false): OpenKeys {
  const [chosen, setChosen] = useState<ReadonlyMap<string, boolean>>(new Map());
  const isOpen = useCallback(
    (key: string) => chosen.get(key) ?? openByDefault,
    [chosen, openByDefault]
  );
  const setOpen = useCallback(
    (key: string, open: boolean) => setChosen((current) => new Map(current).set(key, open)),
    []
  );
  return { isOpen, setOpen };
}

/**
 * Suggestions behind one quiet disclosure (the APG accordion pattern: a
 * heading holding the button): "3 förslag · 2 kan åtgärdas" with a
 * chevron, and open, a compact list with dividers, in the core's order
 * (`inSuggestionOrder`). Nothing is rendered while there are none.
 */
export function SuggestionSection({
  items,
  steps,
  headingLevel,
  openKey,
  open,
  rows,
  summary,
  note,
  onAskChat,
  onFix,
  fixPending,
  fixBlockedBy,
  onRemoveStep
}: ListActions & {
  items: readonly { suggestion: FlowSuggestion; step: FlowStep | null }[];
  steps: readonly FlowStep[];
  headingLevel: 3 | 4;
  /** This section's key in `open`. */
  openKey: string;
  open: OpenKeys;
  /** The rows' own disclosures, by fingerprint. */
  rows: OpenKeys;
  /** What the button says instead of "3 förslag" (the run form's). */
  summary?: string;
  /** Shown above the rows (why "Åtgärda" waits). */
  note?: ReactNode;
}) {
  const t = useTranslations();
  const buttonId = useId();
  const panelId = useId();
  if (items.length === 0) return null;
  const isOpen = open.isOpen(openKey);
  const fixable = items.filter(({ suggestion }) => isPatchable(suggestion)).length;
  const count = summary ?? t("flow_suggestions_count", { count: items.length });
  const fixableText = fixable > 0 ? t("flow_suggestions_fixable", { count: fixable }) : null;

  return (
    <div className="flex flex-col gap-1">
      <Heading level={headingLevel} className="m-0 text-sm font-normal">
        <Button
          id={buttonId}
          label={
            fixableText
              ? t("flow_suggestions_count_fixable", { count, fixable: fixableText })
              : count
          }
          aria-expanded={isOpen}
          aria-controls={panelId}
          variant="ghost"
          size="sm"
          icon={<Lightbulb aria-hidden="true" className="size-4" />}
          endContent={
            isOpen ? (
              <ChevronDown aria-hidden="true" className="size-4" />
            ) : (
              <ChevronRight aria-hidden="true" className="size-4" />
            )
          }
          onClick={() => open.setOpen(openKey, !isOpen)}
          className="-ml-2"
        >
          <span>
            {count}
            {fixableText ? (
              <span className="text-ax-text-secondary font-normal"> · {fixableText}</span>
            ) : null}
          </span>
        </Button>
      </Heading>
      <div id={panelId} hidden={!isOpen} className="flex flex-col gap-1">
        {note}
        <List hasDividers density="compact" edge="flush">
          {inSuggestionOrder(items).map(({ suggestion, step }) => (
            <SuggestionRow
              key={suggestion.fingerprint}
              suggestion={suggestion}
              step={step}
              steps={steps}
              isOpen={rows.isOpen(suggestion.fingerprint)}
              onOpenChange={(next) => rows.setOpen(suggestion.fingerprint, next)}
              onAskChat={onAskChat}
              onFix={onFix ? (item) => onFix([item.fingerprint]) : undefined}
              fixPending={fixPending}
              fixBlockedBy={fixBlockedBy}
              onRemoveStep={onRemoveStep}
            />
          ))}
        </List>
      </div>
    </div>
  );
}

/**
 * A step card's suggestions, below the card's facts and its divider,
 * collapsed until the person opens them.
 */
export function StepCardSuggestions({
  stepId,
  items,
  steps,
  open,
  rows,
  ...actions
}: ListActions & {
  stepId: string;
  items: readonly ShownSuggestion[];
  steps: readonly FlowStep[];
  open: OpenKeys;
  rows: OpenKeys;
}) {
  if (items.length === 0) return null;
  return (
    <div className="border-ax-border border-t pt-2">
      <SuggestionSection
        items={items}
        steps={steps}
        headingLevel={4}
        openKey={`step:${stepId}`}
        open={open}
        rows={rows}
        {...actions}
      />
    </div>
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
  // The run form's suggestions start collapsed, and stay as the person left them.
  const open = useOpenKeys(false);
  const rows = useOpenKeys(false);
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
        <SuggestionSection
          items={formItems.map((suggestion) => ({ suggestion, step: null }))}
          steps={steps}
          headingLevel={3}
          openKey="form"
          open={open}
          rows={rows}
          summary={t("flow_suggestions_form_count", { count: formItems.length })}
          onAskChat={onAskChat}
          onFix={runFix}
          fixPending={fix?.pending}
        />
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
 * Measuring the suggestions over the latest runs, for someone who may view
 * flow traces. The page holds the choice for the visit; a measured read
 * writes an audit entry on the flow, so it is made only when the person
 * asks and for each new draft revision while the choice holds.
 */
export type SuggestionMeasure = {
  /** The runs the answers on screen are measured over; 0 for the definition alone. */
  runs: number;
  /** "Räkna med de senaste körningarna": the page reads and says what the answer is based on. */
  onMeasure: () => void;
  /** Back to the answers from the definition alone. */
  onPlain: () => void;
};

/**
 * Below the summary: "Räkna med de senaste körningarna" while the
 * suggestions judge the definition alone; once measured, what the numbers
 * are based on ("Baserat på 8 körningar.") and the way back. It is one
 * button whose label changes in place, so focus stays on it; while the
 * first measured answer loads it shows that it is busy and ignores another
 * press.
 */
export function SuggestionsMeasure({
  measure,
  runs,
  found,
  failed
}: {
  measure: SuggestionMeasure;
  /** What the answer on screen measured; null or absent for one from the definition alone. */
  runs: FlowSuggestionRuns | null | undefined;
  /** How many suggestions the answer on screen gives. */
  found: number;
  /** The measured read failed (the list says why and offers to try again). */
  failed: boolean;
}) {
  const t = useTranslations();
  const measured = measure.runs > 0;
  const answered = measured && runs != null;
  const pending = measured && !answered && !failed;
  const backToPlain = measured && !pending;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {answered ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 leading-6">
          {measuredBasisText(runs, found, t)}
        </Text>
      ) : null}
      <Button
        label={backToPlain ? t("flow_suggestions_runs_plain") : t("flow_suggestions_runs_measure")}
        size="sm"
        icon={
          backToPlain ? (
            <Undo2 aria-hidden="true" className="size-4" />
          ) : (
            <History aria-hidden="true" className="size-4" />
          )
        }
        isLoading={pending}
        isInterruptible
        onClick={() => {
          if (pending) return;
          if (backToPlain) measure.onPlain();
          else measure.onMeasure();
        }}
      />
    </div>
  );
}

/**
 * The open step's suggestions at the top of the step editor: the step
 * card's section, open from the start. It reads the same query as the step
 * list, measured while the list's are. Nothing is rendered while the step
 * has none, or while they load or fail (the step list says so).
 */
export function StepSuggestions({
  flow,
  stepId,
  runs = 0,
  onAskChat,
  fix,
  fixBlocked = false,
  rescueTarget
}: {
  flow: FlowPublic;
  stepId: string;
  /** The runs the step list's answers are measured over (`SuggestionMeasure`); 0 for none. */
  runs?: number;
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
  const blockedId = useId();
  const query = useQuery(flowSuggestionsQueryOptions(flow.id, flow.draft_revision, runs));
  const runFix = useSuggestionFix(fix, rescueTarget);
  // The person opened the step on purpose: its suggestions start open.
  const open = useOpenKeys(true);
  const rows = useOpenKeys(false);
  const shown = shownSuggestions(query.data?.items, flow.steps).filter(
    ({ step }) => step.id === stepId
  );
  const blocked =
    runFix !== undefined && fixBlocked && shown.some(({ suggestion }) => isPatchable(suggestion));

  return (
    <SuggestionSection
      items={shown}
      steps={flow.steps}
      headingLevel={3}
      openKey={`step:${stepId}`}
      open={open}
      rows={rows}
      note={
        blocked ? (
          <Text id={blockedId} type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_suggestions_fix_blocked_unsaved")}
          </Text>
        ) : null
      }
      onAskChat={onAskChat}
      onFix={runFix}
      fixPending={fix?.pending}
      fixBlockedBy={blocked ? blockedId : undefined}
    />
  );
}

"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Heading } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import type { FlowPublic, FlowStep } from "./flows-api";
import { FlowSuggestionItem, type SuggestionActions } from "./flow-suggestion-item";
import { flowSuggestionsQueryOptions, shownSuggestions } from "./flow-suggestions";

/**
 * "Förslag": what the core says the draft could do cheaper or simpler, below
 * the publish blockers and apart from them (a neutral banner, never a
 * warning). Each suggestion shows the step it is about, a title, its
 * explanation behind a disclosure, a button that opens the step and, while
 * the flow chat is available, "Fråga assistenten". Nothing is rendered while
 * the draft gives no suggestion. The query is keyed by the draft revision,
 * so a save or a chat tool call refetches.
 */
export function FlowSuggestionsSection({
  flow,
  onOpenStep,
  onAskChat
}: {
  flow: FlowPublic;
  onOpenStep: (step: FlowStep) => void;
  onAskChat?: SuggestionActions["onAskChat"];
}) {
  const t = useTranslations();
  const headingId = useId();
  const query = useQuery(flowSuggestionsQueryOptions(flow.id, flow.draft_revision));

  if (query.isPending) {
    return <LoadingState rows={1} label={t("flow_suggestions_loading")} />;
  }
  if (query.isError) {
    return (
      <ListError
        error={query.error}
        title={t("flow_suggestions_error_title")}
        isRetrying={query.isFetching}
        onRetry={() => void query.refetch()}
      />
    );
  }
  const shown = shownSuggestions(query.data.items, flow.steps);
  if (shown.length === 0) return null;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <Heading level={3} id={headingId} weight="semibold" className="text-base">
        {t("flow_suggestions_heading", { count: shown.length })}
      </Heading>
      <Banner
        status="info"
        title={t("flow_suggestions_banner_title")}
        description={t("flow_suggestions_banner_description")}
        collapsible={false}
      >
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {shown.map(({ suggestion, step }) => (
            <FlowSuggestionItem
              key={suggestion.fingerprint}
              suggestion={suggestion}
              step={step}
              steps={flow.steps}
              showStep
              onOpenStep={onOpenStep}
              onAskChat={onAskChat}
            />
          ))}
        </ul>
      </Banner>
    </section>
  );
}

/**
 * The open step's suggestions at the top of the step editor, compact and
 * with the same actions as the draft check (the step is open already, so
 * no "Öppna steget"). It reads the same query as the draft check and the
 * step list's marker. Nothing is rendered while the step has none, or while
 * they load or fail (the draft check says so).
 */
export function StepSuggestions({
  flow,
  stepId,
  onAskChat
}: {
  flow: FlowPublic;
  stepId: string;
  onAskChat?: SuggestionActions["onAskChat"];
}) {
  const t = useTranslations();
  const headingId = useId();
  const query = useQuery(flowSuggestionsQueryOptions(flow.id, flow.draft_revision));
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
        collapsible={false}
      >
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {shown.map(({ suggestion, step }) => (
            <FlowSuggestionItem
              key={suggestion.fingerprint}
              suggestion={suggestion}
              step={step}
              steps={flow.steps}
              showStep={false}
              onAskChat={onAskChat}
            />
          ))}
        </ul>
      </Banner>
    </section>
  );
}

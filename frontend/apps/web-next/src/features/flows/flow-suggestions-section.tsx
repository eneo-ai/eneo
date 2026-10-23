"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import type { FlowPublic, FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import {
  flowSuggestionsQueryOptions,
  suggestionText,
  type FlowSuggestion
} from "./flow-suggestions";

// A compact Astryx Collapsible for the "why" of one suggestion.
const WHY_COLLAPSIBLE_CLASS =
  "[&_.astryx-collapsible-trigger]:text-ax-text-secondary [&_.astryx-collapsible-trigger]:min-h-8 [&_.astryx-collapsible-trigger]:text-sm [&_.astryx-collapsible-trigger]:font-medium";

type Shown = { suggestion: FlowSuggestion; step: FlowStep };

/**
 * "Förslag": what the core says the draft could do cheaper or simpler, below
 * the publish blockers and apart from them (a neutral banner, never a
 * warning). Display only: each suggestion shows the step it is about, a
 * title, its explanation behind a disclosure and a button that opens the
 * step. Nothing is rendered while the draft gives no suggestion. The query
 * is keyed by the draft revision, so a save or a chat tool call refetches.
 */
export function FlowSuggestionsSection({
  flow,
  onOpenStep
}: {
  flow: FlowPublic;
  onOpenStep: (step: FlowStep) => void;
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
  // A suggestion whose step the draft no longer has cannot be shown on it.
  const shown = (query.data?.items ?? []).flatMap((suggestion): Shown[] => {
    const step = flow.steps.find((candidate) => candidate.id === suggestion.steps[0]);
    return step ? [{ suggestion, step }] : [];
  });
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
          {shown.map(({ suggestion, step }) => {
            const label = stepLabel(step, t);
            const text = suggestionText(suggestion, t, step);
            return (
              <li key={suggestion.fingerprint} className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-ax-text text-sm font-semibold break-words">{label}</span>
                  <Button
                    label={t("flow_editor_tools_check_open_step")}
                    aria-label={t("flow_editor_tools_check_open_step_named", { step: label })}
                    size="sm"
                    variant="ghost"
                    onClick={() => onOpenStep(step)}
                  />
                </div>
                <Text size="sm" as="p" display="block" className="m-0">
                  {text.title}
                </Text>
                <div className={WHY_COLLAPSIBLE_CLASS}>
                  <Collapsible
                    trigger={
                      <>
                        {t("flow_suggestion_why")}
                        <span className="sr-only">
                          {t("flow_suggestion_why_about", { title: text.title })}
                        </span>
                      </>
                    }
                    chevronPosition="start"
                    defaultIsOpen={false}
                  >
                    <Text type="supporting" size="sm" as="p" display="block" className="m-0">
                      {text.explanation}
                    </Text>
                  </Collapsible>
                </div>
              </li>
            );
          })}
        </ul>
      </Banner>
    </section>
  );
}

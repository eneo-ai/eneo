import { Card } from "@astryxdesign/core/Card";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "use-intl";
import Link from "@/lib/link";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { tokenUsageQueryOptions } from "@/features/admin/usage/usage";
import { ActivityCard } from "@/features/insights/activity-card";
import { countChange, INSIGHT_SOURCES } from "@/features/insights/insight-figures";
import { Tile } from "@/features/insights/insight-tile";
import { InsightsFilterRow } from "@/features/insights/insights-filter-row";
import type { InsightRange } from "@/features/insights/insights-range";
import { PeriodChange } from "@/features/insights/period-change";
import { useSourceSplit } from "@/features/insights/source-tag";
import {
  insightPeriod,
  insightTargetsActivityQueryOptions,
  insightTargetsSummaryQueryOptions
} from "./insights";
import { InsightTargets } from "./insight-targets";
import {
  insightsPageSearch,
  readInsightsPageSearch,
  type InsightsPageState
} from "./insights-page-search";

/**
 * "Nyckeltal" for the whole organisation: conversations by source,
 * questions, the signed-in users who asked and the assistants and group
 * chats that were used, each change against the previous period when
 * compared (not the used ones). Read from the target list unfiltered, so the
 * table's search, filter and sort never move them; they count by the
 * table's rules.
 */
function OrganisationTiles({ range, compare }: { range: InsightRange; compare: boolean }) {
  const t = useTranslations();
  const format = useFormatter();
  const sourceSplit = useSourceSplit();
  // A new period or comparison keeps the figures on screen until the new ones are in.
  const summary = useQuery({
    ...insightTargetsSummaryQueryOptions(browserApi, range, compare),
    placeholderData: keepPreviousData
  });
  return (
    <QueryStateBoundary query={summary} rows={2}>
      {({ totals, users, counts }) => {
        const previous = compare ? totals.previous : null;
        const conversations = totals.conversations.total;
        const perConversation = conversations > 0 ? totals.questions / conversations : null;
        const change = (current: number, before: number | null | undefined) =>
          compare ? <PeriodChange change={countChange(current, before)} unit="percent" /> : null;
        return (
          // Columns by the page's own width: four across where each keeps room
          // for its lines, else two by two; one per row on a phone.
          <section aria-label={t("insights_tiles_label")} className="@container">
            <dl className="grid grid-cols-1 gap-3 @min-[26rem]:grid-cols-2 @min-[48rem]:grid-cols-4">
              <Tile
                label={t("insights_tile_conversations")}
                value={{ text: format.number(conversations) }}
                change={change(conversations, previous?.conversations.total)}
                details={[sourceSplit(totals.conversations)]}
              />
              <Tile
                label={t("questions")}
                value={{ text: format.number(totals.questions) }}
                change={change(totals.questions, previous?.questions)}
                details={[
                  perConversation === null
                    ? null
                    : t.markup("insights_shape_questions_per_conversation", {
                        value: format.number(perConversation, { maximumFractionDigits: 1 }),
                        strong: (chunks) => chunks
                      })
                ]}
              />
              <Tile
                label={t("active_users")}
                value={{ text: format.number(users.current) }}
                change={change(users.current, users.previous)}
                details={[t("insights_org_users_detail")]}
              />
              <Tile
                label={t("active_assistants")}
                value={{
                  text: t("insights_org_active_targets", {
                    active: counts.all - counts.unused,
                    total: counts.all
                  })
                }}
                details={[
                  t("insights_org_unused_targets", { count: counts.unused }),
                  t("insights_org_targets_note")
                ]}
              />
            </dl>
          </section>
        );
      }}
    </QueryStateBoundary>
  );
}

function TokensCard({ range }: { range: InsightRange }) {
  const t = useTranslations();
  const format = useFormatter();
  const query = useQuery(
    tokenUsageQueryOptions(browserApi, {
      startTime: insightPeriod(range).start,
      endTime: insightPeriod(range).end
    })
  );
  return (
    <Card className="flex flex-col gap-3 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">{t("tokens")}</h2>
        <Link
          className="text-ax-text-accent inline-flex min-h-6 items-center underline underline-offset-4 pointer-coarse:min-h-11"
          href={`/admin/usage?tab=tokens&from=${range.start}&to=${range.end}`}
        >
          {t("insights_token_usage_link")}
        </Link>
      </div>
      <QueryStateBoundary query={query} rows={1}>
        {(data) => (
          <dl className="grid gap-4 sm:grid-cols-3">
            {(
              [
                ["total_token_usage", "usage_total_tokens"],
                ["total_input_token_usage", "input_tokens"],
                ["total_output_token_usage", "output_tokens"]
              ] as const
            ).map(([key, label]) => (
              <div key={key}>
                <dt className="text-ax-text-secondary text-sm">{t(label)}</dt>
                <dd className="text-2xl font-semibold tabular-nums">{format.number(data[key])}</dd>
              </div>
            ))}
          </dl>
        )}
      </QueryStateBoundary>
    </Card>
  );
}

/**
 * The organisation's insights: its figures, its activity per day and every
 * assistant and group chat with its use in the period ("Assistenter och
 * gruppchattar"), counted by one set of rules, and the tokens for an admin.
 * The period and the comparison drive all of it. They, "Oanvända", the name
 * search and the table's sort are kept in the address in place (no history
 * entries), so the way back from an assistant's insights finds the page as
 * it was.
 */
export function InsightsPage() {
  const t = useTranslations();
  const { can } = useAppContext();
  const searchParams = useSearchParams();
  const state = readInsightsPageSearch(searchParams);
  const { range, compare } = state;
  const update = (next: Partial<InsightsPageState>) =>
    replaceUrl(insightsPageSearch({ ...state, ...next }));
  const activity = useQuery({
    ...insightTargetsActivityQueryOptions(browserApi, range),
    placeholderData: keepPreviousData
  });

  return (
    <div className="flex w-full min-w-0 flex-col gap-6">
      <PageHeader title={t("insights")} description={t("insights_org_description")} />
      <section aria-label={t("insights_filters_label")}>
        <InsightsFilterRow
          range={range}
          onRangeChange={(next) => update({ range: next })}
          compare={compare}
          onCompareChange={(next) => update({ compare: next })}
        />
      </section>
      <OrganisationTiles range={range} compare={compare} />
      <ActivityCard activity={activity} range={range} sources={INSIGHT_SOURCES} />
      <InsightTargets
        range={range}
        compare={compare}
        sort={state.sort}
        onSortChange={(sort) => update({ sort })}
        unusedOnly={state.unusedOnly}
        onUnusedOnlyChange={(unusedOnly) => update({ unusedOnly })}
        search={state.search}
        onSearchChange={(search) => update({ search })}
      />
      {can("admin") ? <TokensCard range={range} /> : null}
    </div>
  );
}

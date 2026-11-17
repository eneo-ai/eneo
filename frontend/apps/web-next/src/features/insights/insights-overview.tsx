import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Token } from "@astryxdesign/core/Token";
import type { UseQueryResult } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { lazy, Suspense, useId, type ReactNode } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import {
  activityDays,
  answeredShare,
  countChange,
  goodAnswerShare,
  INSIGHT_SOURCES,
  knowledgeHitShare,
  questionsPerConversation,
  ratedAnswerShare,
  returningUserShare,
  shareChange,
  singleQuestionShare,
  sourceParts,
  type InsightActivity,
  type InsightFilters,
  type InsightPeriodSummary,
  type InsightSource,
  type InsightSummary,
  type PeriodChange as Change
} from "./insight-figures";
import { PeriodChange } from "./period-change";

const ActivityChart = lazy(() =>
  import("./insights-activity-chart").then((module) => ({ default: module.ActivityChart }))
);
/** The chart's height (`ACTIVITY_CHART_HEIGHT`) and its legend, for the skeleton. */
const ACTIVITY_SKELETON_HEIGHT = 272;

/** A conversation split's parts, by source: "742 användare, 468 widget, 74 API". */
const SPLIT_KEY = {
  user: "insights_split_user",
  widget: "insights_split_widget",
  api_key: "insights_split_api_key"
} as const satisfies Record<InsightSource, string>;

/** "Indikativt": the figure comes from patterns in the answers' text, not a measurement. */
function IndicativeTag() {
  const t = useTranslations();
  return (
    <Token
      label={t("insights_indicative")}
      size="sm"
      description={t("insights_indicative_description")}
    />
  );
}

/**
 * One figure: its name, its value (or why there is none) with its change
 * when compared, and a line or two on what it is made of.
 */
function Tile({
  label,
  isIndicative = false,
  value,
  change,
  details
}: {
  label: string;
  isIndicative?: boolean;
  /** The figure as text, or `empty`: why there is none ("Inga betyg"). */
  value: { text: string } | { empty: string };
  change: ReactNode;
  details: (string | null)[];
}) {
  return (
    <div className="border-ax-border rounded-ax-container flex min-w-0 flex-col gap-1 border p-4">
      <dt className="text-ax-text-secondary flex flex-wrap items-center gap-2 text-sm">
        {label}
        {isIndicative ? <IndicativeTag /> : null}
      </dt>
      <dd className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {"text" in value ? (
          <span className="text-3xl font-semibold tabular-nums">{value.text}</span>
        ) : (
          <span className="text-ax-text-secondary py-1.5 text-lg font-medium">{value.empty}</span>
        )}
        {change}
      </dd>
      {details
        .filter((detail): detail is string => Boolean(detail))
        .map((detail) => (
          <dd key={detail} className="text-ax-text-secondary text-sm">
            {detail}
          </dd>
        ))}
    </div>
  );
}

/**
 * "Nyckeltal": conversations, answered questions, good answers by rating and
 * knowledge hits, each with its change when compared. Every share guards its
 * division: without questions, ratings or searches it says so instead of 0 %.
 */
function SummaryTiles({ summary, compare }: { summary: InsightSummary; compare: boolean }) {
  const t = useTranslations();
  const format = useFormatter();
  const { period } = summary;
  const previous: InsightPeriodSummary | null = summary.previous;
  const percent = (value: number) => format.number(value, { style: "percent" });
  const shown = (change: Change, unit: "percent" | "points") =>
    compare ? <PeriodChange change={change} unit={unit} /> : null;
  const shareValue = (value: number | null, empty: string) =>
    value === null ? { empty } : { text: percent(value) };

  const answered = answeredShare(period);
  const good = goodAnswerShare(period);
  const rated = ratedAnswerShare(period);
  const hits = knowledgeHitShare(period);
  const { answer_ratings: answers, conversation_ratings: conversations } = period;

  return (
    <section aria-label={t("insights_tiles_label")}>
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-3">
        <Tile
          label={t("insights_tile_conversations")}
          value={{ text: format.number(period.conversations.total) }}
          change={shown(
            countChange(period.conversations.total, previous?.conversations.total),
            "percent"
          )}
          details={[
            sourceParts(period.conversations)
              .map(({ source, count }) => t(SPLIT_KEY[source], { count }))
              .join(", ") || null
          ]}
        />
        <Tile
          label={t("insights_tile_answered")}
          isIndicative
          value={shareValue(answered, t("insights_no_questions"))}
          change={shown(shareChange(answered, previous && answeredShare(previous)), "points")}
          details={[
            period.questions.total > 0
              ? t("insights_tile_answered_detail", {
                  unanswered: period.unanswered,
                  total: period.questions.total
                })
              : null
          ]}
        />
        <Tile
          label={t("insights_tile_ratings")}
          value={shareValue(good, t("insights_no_ratings"))}
          change={shown(shareChange(good, previous && goodAnswerShare(previous)), "points")}
          details={[
            good !== null && rated !== null
              ? t("insights_tile_ratings_detail", {
                  positive: answers.positive,
                  negative: answers.negative,
                  rated: percent(rated)
                })
              : null,
            // A rating of a whole conversation (where widget votes land) is its own figure.
            conversations.positive + conversations.negative > 0
              ? t("insights_tile_conversation_ratings", {
                  positive: conversations.positive,
                  negative: conversations.negative
                })
              : null
          ]}
        />
        {period.knowledge ? (
          <Tile
            label={t("insights_tile_knowledge")}
            isIndicative
            value={shareValue(hits, t("insights_no_knowledge_searches"))}
            change={shown(shareChange(hits, previous && knowledgeHitShare(previous)), "points")}
            details={[
              hits !== null
                ? t("insights_tile_knowledge_detail", { missed: period.knowledge.missed })
                : null
            ]}
          />
        ) : null}
      </dl>
    </section>
  );
}

/** How conversations go: questions per conversation, one-question ones, users who came back. */
function ConversationShape({ period }: { period: InsightPeriodSummary }) {
  const t = useTranslations();
  const format = useFormatter();
  const strong = (chunks: ReactNode) => (
    <strong className="text-ax-text font-semibold tabular-nums">{chunks}</strong>
  );
  const percent = (value: number) => format.number(value, { style: "percent" });
  const perConversation = questionsPerConversation(period);
  const single = singleQuestionShare(period);
  const returning = returningUserShare(period);
  const items = [
    perConversation === null
      ? null
      : t.rich("insights_shape_questions_per_conversation", {
          value: format.number(perConversation, { maximumFractionDigits: 1 }),
          strong
        }),
    single === null
      ? null
      : t.rich("insights_shape_single_question", { share: percent(single), strong }),
    returning === null
      ? null
      : t.rich("insights_shape_returning_users", { share: percent(returning), strong })
  ].filter((item) => item !== null);
  if (items.length === 0) return null;
  return (
    <ul
      aria-label={t("insights_shape_label")}
      className="text-ax-text-secondary flex flex-wrap gap-x-6 gap-y-1 text-sm"
    >
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}

/** "Aktivitet per dag": the chart of the period's days, and under it how conversations go. */
function ActivityCard({
  activity,
  summary,
  filters
}: {
  activity: UseQueryResult<InsightActivity>;
  summary: UseQueryResult<InsightSummary>;
  filters: InsightFilters;
}) {
  const t = useTranslations();
  const headingId = useId();
  const sources = filters.source ? [filters.source] : INSIGHT_SOURCES;
  return (
    <Card>
      <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-4">
        <h2 id={headingId} className="text-base font-semibold">
          {t("insights_activity_heading")}
        </h2>
        <QueryStateBoundary query={activity} rows={1} height={ACTIVITY_SKELETON_HEIGHT}>
          {(data) => (
            <Suspense fallback={<LoadingState rows={1} height={ACTIVITY_SKELETON_HEIGHT} />}>
              <ActivityChart
                key={`${filters.range.start}|${filters.range.end}`}
                days={activityDays(data.days, filters.range)}
                sources={sources}
              />
            </Suspense>
          )}
        </QueryStateBoundary>
        {summary.data ? <ConversationShape period={summary.data.period} /> : null}
      </section>
    </Card>
  );
}

/**
 * The period's figures (the summary tiles), its activity per day and the
 * conversations themselves behind "Utforska konversationer".
 */
export function InsightsOverview({
  summary,
  activity,
  filters,
  onExplore
}: {
  summary: UseQueryResult<InsightSummary>;
  activity: UseQueryResult<InsightActivity>;
  filters: InsightFilters;
  onExplore: () => void;
}) {
  const t = useTranslations();

  return (
    <div className="flex flex-col gap-5">
      <QueryStateBoundary query={summary} rows={2}>
        {(data) => <SummaryTiles summary={data} compare={filters.compare} />}
      </QueryStateBoundary>

      <ActivityCard activity={activity} summary={summary} filters={filters} />

      <div className="border-ax-border rounded-ax-container flex flex-wrap items-center justify-between gap-3 border p-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{t("explore_conversations")}</p>
          <p className="text-ax-text-secondary text-sm">{t("view_all_conversations_users_had")}</p>
        </div>
        <Button
          label={t("explore_conversations")}
          variant="secondary"
          icon={<History className="size-4" aria-hidden="true" />}
          onClick={onExplore}
        />
      </div>
    </div>
  );
}

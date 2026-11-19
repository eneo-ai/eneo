import type { Schema } from "@/lib/api/models";
import type { IsoDate } from "@/lib/calendar-date";
import {
  DEFAULT_INSIGHT_DAYS,
  insightRangeOfDays,
  nextDay,
  type InsightRange
} from "./insights-range";

/** Who a conversation is with: a signed-in user, a service API key or a widget visitor. */
export type InsightSource = Schema<"InsightRating">["source"];

/** The sources in the order the page lists them (filter, splits, legend, tags). */
export const INSIGHT_SOURCES = [
  "user",
  "widget",
  "api_key"
] as const satisfies readonly InsightSource[];

export type SourceCounts = Schema<"SourceCounts">;
export type InsightSummary = Schema<"InsightSummary">;
export type InsightPeriodSummary = Schema<"InsightPeriodSummary">;
export type InsightActivity = Schema<"InsightActivity">;
export type InsightRating = Schema<"InsightRating">;
export type InsightFinding = Schema<"InsightFinding">;
export type InsightFindingKind = InsightFinding["kind"];
export type InsightFindingCases = Schema<"InsightFindingCasePage">;
export type InsightFindingCase = InsightFindingCases["items"][number];
export type InsightQuestionGroup = Schema<"InsightQuestionGroup">;
export type InsightKnowledgeSource = Schema<"InsightKnowledgeSource">;
export type InsightToolUse = Schema<"InsightToolUse">;

/** The findings with cases to list: each opens a view of its own with examples. */
export type OpenableFindingKind = InsightFindingCases["kind"];

export const OPENABLE_FINDINGS = [
  "knowledge_missed",
  "unanswered",
  "rephrasing"
] as const satisfies readonly OpenableFindingKind[];

/** A finding that opens a view of its own; anything else (an unknown address value) is none. */
export function parseOpenableFinding(value: string | null | undefined): OpenableFindingKind | null {
  return OPENABLE_FINDINGS.find((kind) => kind === value) ?? null;
}

/** The feedback inbox's filter: every rating, the bad ones someone explained, or the good ones. */
export type FeedbackFilter = "all" | "bad_commented" | "good";

const FEEDBACK_FILTERS = [
  "all",
  "bad_commented",
  "good"
] as const satisfies readonly FeedbackFilter[];

/** The inbox's filter from an address or a control's value; anything unknown is every rating. */
export function parseFeedbackFilter(value: string | null | undefined): FeedbackFilter {
  return FEEDBACK_FILTERS.find((filter) => filter === value) ?? "all";
}

/**
 * What the insights view shows: the period, one source or all of them (null),
 * and whether each figure is set beside the previous period of equal length.
 */
export type InsightFilters = {
  range: InsightRange;
  source: InsightSource | null;
  compare: boolean;
};

/** The last 30 days, every source, no comparison. */
export function defaultInsightFilters(): InsightFilters {
  return { range: insightRangeOfDays(DEFAULT_INSIGHT_DAYS), source: null, compare: false };
}

/** A source from an address or a control's value; anything else is every source (null). */
export function parseInsightSource(value: string | null | undefined): InsightSource | null {
  return INSIGHT_SOURCES.find((source) => source === value) ?? null;
}

/** The `source` parameter of the insight endpoints: left out for every source. */
export function insightSourceQuery(source: InsightSource | null): { source?: InsightSource } {
  return source ? { source } : {};
}

/** `part` of `whole` as 0 to 1, or null without a whole to take it of. */
export function share(part: number, whole: number): number | null {
  if (!(whole > 0) || !Number.isFinite(part)) return null;
  return Math.min(1, Math.max(0, part / whole));
}

/** The questions whose answer does not say it cannot answer. Indicative. */
export function answeredShare(period: InsightPeriodSummary): number | null {
  const unanswered = share(period.unanswered, period.questions.total);
  return unanswered === null ? null : 1 - unanswered;
}

/** Good answer ratings of all answer ratings; null without ratings. */
export function goodAnswerShare(period: InsightPeriodSummary): number | null {
  const { positive, negative } = period.answer_ratings;
  return share(positive, positive + negative);
}

/** The answers that were rated at all. */
export function ratedAnswerShare(period: InsightPeriodSummary): number | null {
  const { positive, negative } = period.answer_ratings;
  return share(positive + negative, period.questions.total);
}

/**
 * The answers that searched the knowledge and found something usable.
 * Indicative; null when nothing searched (and for a target without knowledge).
 */
export function knowledgeHitShare(period: InsightPeriodSummary): number | null {
  if (!period.knowledge) return null;
  const missed = share(period.knowledge.missed, period.knowledge.searched);
  return missed === null ? null : 1 - missed;
}

/**
 * The feedback inbox's filters as the summary counts them: every rating of
 * answers and whole conversations, the bad ones with a comment, the good ones.
 * The inbox's list counts the same ratings in the same period and source.
 */
export function feedbackCounts(period: InsightPeriodSummary): {
  all: number;
  bad_commented: number;
  good: number;
} {
  const { answer_ratings: answers, conversation_ratings: conversations } = period;
  return {
    all: answers.positive + answers.negative + conversations.positive + conversations.negative,
    bad_commented: answers.negative_with_comment + conversations.negative_with_comment,
    good: answers.positive + conversations.positive
  };
}

/**
 * What a finding is a share of, and how many cases it has, as the server
 * counts them: answers that searched the knowledge and those without a usable
 * hit; all answers and those that say they cannot answer; all conversations
 * and those with similar questions in a row (`cases`, the cases' total: the
 * summary does not count them). Null without the figures it needs.
 */
export function findingEvidence(
  kind: OpenableFindingKind,
  period: InsightPeriodSummary,
  cases: number | null
): { affected: number; base: number } | null {
  switch (kind) {
    case "knowledge_missed":
      return period.knowledge
        ? { affected: period.knowledge.missed, base: period.knowledge.searched }
        : null;
    case "unanswered":
      return { affected: period.unanswered, base: period.questions.total };
    case "rephrasing":
      return cases === null ? null : { affected: cases, base: period.conversations.total };
  }
}

/** Why an answer that searched the knowledge found nothing usable. */
export type KnowledgeMissReason = Extract<
  InsightFindingCase,
  { kind: "knowledge_missed" }
>["reason"];

/**
 * The knowledge misses by reason, in a fixed order, leaving out reasons
 * without any. Only from every case: null while more pages are to load.
 */
export function knowledgeMissReasons(
  cases: readonly InsightFindingCase[],
  complete: boolean
): { reason: KnowledgeMissReason; count: number }[] | null {
  if (!complete) return null;
  const order: KnowledgeMissReason[] = ["no_results", "uncited", "weak_score"];
  const counts = new Map<KnowledgeMissReason, number>();
  for (const item of cases) {
    if (item.kind === "knowledge_missed") {
      counts.set(item.reason, (counts.get(item.reason) ?? 0) + 1);
    }
  }
  return order
    .map((reason) => ({ reason, count: counts.get(reason) ?? 0 }))
    .filter(({ count }) => count > 0);
}

/** A common question's answers that did not say they cannot answer. Indicative. */
export function groupAnsweredShare(group: InsightQuestionGroup): number | null {
  const unanswered = share(group.unanswered, group.occurrences);
  return unanswered === null ? null : 1 - unanswered;
}

/**
 * A common question's answers that searched the knowledge and found something
 * usable. Indicative; null when none of them searched or without knowledge.
 */
export function groupKnowledgeHitShare(group: InsightQuestionGroup): number | null {
  if (!group.knowledge) return null;
  const missed = share(group.knowledge.missed, group.knowledge.searched);
  return missed === null ? null : 1 - missed;
}

/** Questions per conversation; null without conversations. */
export function questionsPerConversation(period: InsightPeriodSummary): number | null {
  return period.conversations.total > 0
    ? period.questions.total / period.conversations.total
    : null;
}

/** Conversations that ended after the first answer. */
export function singleQuestionShare(period: InsightPeriodSummary): number | null {
  return share(period.single_question_conversations, period.conversations.total);
}

/** Signed-in users who asked on more than one day; null without users. */
export function returningUserShare(period: InsightPeriodSummary): number | null {
  return share(period.returning_users, period.users);
}

/**
 * A figure against the previous period, as the page shows it: rounded to a
 * whole percent or percentage point. "none": nothing to compare with (no
 * previous figure, or a count that was 0); "same": no change at that
 * precision.
 */
export type PeriodChange = { kind: "none" } | { kind: "same" } | { kind: "change"; value: number };

function rounded(value: number): PeriodChange {
  const whole = Math.round(value);
  return whole === 0 ? { kind: "same" } : { kind: "change", value: whole };
}

/** A count's change in percent: 12 is +12 %. */
export function countChange(current: number, previous: number | null | undefined): PeriodChange {
  if (previous == null || !(previous > 0)) return { kind: "none" };
  return rounded(((current - previous) / previous) * 100);
}

/** A share's change in percentage points: shares of 0.78 and 0.74 are +4. */
export function shareChange(
  current: number | null,
  previous: number | null | undefined
): PeriodChange {
  if (current === null || previous == null) return { kind: "none" };
  return rounded((current - previous) * 100);
}

/** The sources with a count, in the page's order. */
export function sourceParts(counts: SourceCounts): { source: InsightSource; count: number }[] {
  return INSIGHT_SOURCES.filter((source) => counts[source] > 0).map((source) => ({
    source,
    count: counts[source]
  }));
}

/** One local day of the activity chart: conversations per source. */
export type ActivityDay = { date: IsoDate } & Record<InsightSource | "total", number>;

/**
 * Every day of the period, oldest first, with its conversations per source.
 * The endpoint leaves out days without any; they are 0 here, so the chart's
 * axis runs without gaps.
 */
export function activityDays(days: InsightActivity["days"], range: InsightRange): ActivityDay[] {
  const counts = new Map(days.map((day) => [day.date, day.conversations]));
  const filled: ActivityDay[] = [];
  for (let date = range.start; date <= range.end; date = nextDay(date)) {
    const day = counts.get(date);
    filled.push({
      date,
      user: day?.user ?? 0,
      widget: day?.widget ?? 0,
      api_key: day?.api_key ?? 0,
      total: day?.total ?? 0
    });
  }
  return filled;
}

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activityDays,
  answeredShare,
  countChange,
  feedbackCounts,
  findingEvidence,
  goodAnswerShare,
  groupAnsweredShare,
  groupKnowledgeHitShare,
  knowledgeHitShare,
  knowledgeMissReasons,
  parseInsightSource,
  parseOpenableFinding,
  questionsPerConversation,
  ratedAnswerShare,
  returningUserShare,
  shareChange,
  singleQuestionShare,
  sourceParts,
  type InsightPeriodSummary
} from "./insight-figures";
import type { InsightRange } from "./insights-range";

const counts = (user: number, widget: number, api_key: number) => ({
  total: user + widget + api_key,
  user,
  widget,
  api_key
});

function period(overrides: Partial<InsightPeriodSummary> = {}): InsightPeriodSummary {
  return {
    start: "2026-10-01T00:00:00Z",
    end: "2026-11-01T00:00:00Z",
    conversations: counts(742, 468, 74),
    questions: counts(1700, 1000, 246),
    followups: 1662,
    users: 300,
    single_question_conversations: 488,
    returning_users: 123,
    unanswered: 265,
    knowledge: { searched: 2900, missed: 464 },
    answer_ratings: { positive: 165, negative: 47, with_comment: 19, negative_with_comment: 12 },
    conversation_ratings: { positive: 4, negative: 6, with_comment: 3, negative_with_comment: 2 },
    ...overrides
  };
}

describe("insight figures", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("derives the tiles' shares and the conversations' shape", () => {
    const figures = period();
    expect(answeredShare(figures)).toBeCloseTo(1 - 265 / 2946);
    expect(goodAnswerShare(figures)).toBeCloseTo(165 / 212);
    expect(ratedAnswerShare(figures)).toBeCloseTo(212 / 2946);
    expect(knowledgeHitShare(figures)).toBeCloseTo(1 - 464 / 2900);
    expect(questionsPerConversation(figures)).toBeCloseTo(2946 / 1284);
    expect(singleQuestionShare(figures)).toBeCloseTo(488 / 1284);
    expect(returningUserShare(figures)).toBeCloseTo(123 / 300);
  });

  it("guards every division: nothing to divide by is no figure, not 0 %", () => {
    const empty = period({
      conversations: counts(0, 0, 0),
      questions: counts(0, 0, 0),
      users: 0,
      unanswered: 0,
      knowledge: { searched: 0, missed: 0 },
      answer_ratings: { positive: 0, negative: 0, with_comment: 0, negative_with_comment: 0 }
    });
    expect(answeredShare(empty)).toBeNull();
    expect(goodAnswerShare(empty)).toBeNull();
    expect(ratedAnswerShare(empty)).toBeNull();
    expect(knowledgeHitShare(empty)).toBeNull();
    expect(questionsPerConversation(empty)).toBeNull();
    expect(singleQuestionShare(empty)).toBeNull();
    expect(returningUserShare(empty)).toBeNull();
    // A target without knowledge has no knowledge figure at all.
    expect(knowledgeHitShare(period({ knowledge: null }))).toBeNull();
    // More "cannot answer" matches than questions still reads as a share.
    expect(answeredShare(period({ unanswered: 5000 }))).toBe(0);
  });

  it("compares counts in percent and shares in points, rounded as shown", () => {
    expect(countChange(1284, 1146)).toEqual({ kind: "change", value: 12 });
    expect(countChange(90, 100)).toEqual({ kind: "change", value: -10 });
    expect(countChange(100, 100)).toEqual({ kind: "same" });
    expect(countChange(1001, 1000)).toEqual({ kind: "same" });
    // No previous count, or one of 0, has no percentage.
    expect(countChange(5, 0)).toEqual({ kind: "none" });
    expect(countChange(5, undefined)).toEqual({ kind: "none" });
    expect(shareChange(0.78, 0.74)).toEqual({ kind: "change", value: 4 });
    expect(shareChange(0.89, 0.91)).toEqual({ kind: "change", value: -2 });
    expect(shareChange(0.84, 0.84)).toEqual({ kind: "same" });
    expect(shareChange(0.5, null)).toEqual({ kind: "none" });
    expect(shareChange(null, 0.5)).toEqual({ kind: "none" });
  });

  it("counts the feedback inbox's filters from answer and conversation ratings", () => {
    expect(feedbackCounts(period())).toEqual({
      all: 165 + 47 + 4 + 6,
      bad_commented: 14,
      good: 169
    });
  });

  it("takes a finding's cases and base from the figures the server flags it by", () => {
    const figures = period();
    expect(findingEvidence("knowledge_missed", figures, 999)).toEqual({
      affected: 464,
      base: 2900
    });
    expect(findingEvidence("knowledge_missed", period({ knowledge: null }), 3)).toBeNull();
    expect(findingEvidence("unanswered", figures, null)).toEqual({ affected: 265, base: 2946 });
    // Rephrasing is counted by its cases; until they are in there is no figure.
    expect(findingEvidence("rephrasing", figures, 74)).toEqual({ affected: 74, base: 1284 });
    expect(findingEvidence("rephrasing", figures, null)).toBeNull();
    expect(parseOpenableFinding("rephrasing")).toBe("rephrasing");
    expect(parseOpenableFinding("tool_failures")).toBeNull();
  });

  it("splits knowledge misses by reason only once every case is loaded", () => {
    const miss = (reason: "no_results" | "uncited" | "weak_score", id: string) => ({
      kind: "knowledge_missed" as const,
      reason,
      question_id: id,
      question: "Vad kostar bygglov?",
      session_id: "s",
      source: "user" as const,
      created_at: "2026-10-01T10:00:00Z",
      best_score: null,
      rating: null
    });
    const cases = [miss("weak_score", "1"), miss("no_results", "2"), miss("no_results", "3")];
    expect(knowledgeMissReasons(cases, true)).toEqual([
      { reason: "no_results", count: 2 },
      { reason: "weak_score", count: 1 }
    ]);
    expect(knowledgeMissReasons(cases, false)).toBeNull();
  });

  it("derives a common question's answered and knowledge shares", () => {
    const group = {
      question: "Behöver jag bygglov för altan?",
      occurrences: 40,
      share: 0.1,
      conversations: 38,
      unanswered: 10,
      ratings: { positive: 3, negative: 1 },
      knowledge: { searched: 20, missed: 5 },
      sample_session_id: "s"
    };
    expect(groupAnsweredShare(group)).toBeCloseTo(0.75);
    expect(groupKnowledgeHitShare(group)).toBeCloseTo(0.75);
    // Nothing searched, or no knowledge at all: no share.
    expect(groupKnowledgeHitShare({ ...group, knowledge: { searched: 0, missed: 0 } })).toBeNull();
    expect(groupKnowledgeHitShare({ ...group, knowledge: null })).toBeNull();
  });

  it("lists the sources with conversations and reads a source from an address", () => {
    expect(sourceParts(counts(742, 0, 74))).toEqual([
      { source: "user", count: 742 },
      { source: "api_key", count: 74 }
    ]);
    expect(parseInsightSource("widget")).toBe("widget");
    expect(parseInsightSource("all")).toBeNull();
    expect(parseInsightSource(null)).toBeNull();
  });

  it("fills the days without activity so the chart's axis is continuous", () => {
    vi.stubEnv("TZ", "Europe/Stockholm");
    const range = { start: "2026-10-24", end: "2026-10-27" } as InsightRange;
    const days = activityDays(
      [
        { date: "2026-10-25", conversations: counts(2, 1, 0), questions: counts(5, 1, 0) },
        { date: "2026-10-27", conversations: counts(0, 0, 3), questions: counts(0, 0, 3) }
      ],
      range
    );
    expect(days).toEqual([
      { date: "2026-10-24", user: 0, widget: 0, api_key: 0, total: 0 },
      // The day the clocks go back (25 hours long) is still one day.
      { date: "2026-10-25", user: 2, widget: 1, api_key: 0, total: 3 },
      { date: "2026-10-26", user: 0, widget: 0, api_key: 0, total: 0 },
      { date: "2026-10-27", user: 0, widget: 0, api_key: 3, total: 3 }
    ]);
  });
});

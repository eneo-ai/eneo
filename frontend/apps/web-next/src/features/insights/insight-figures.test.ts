import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activityDays,
  answeredShare,
  countChange,
  goodAnswerShare,
  knowledgeHitShare,
  parseInsightSource,
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
    answer_ratings: { positive: 165, negative: 47, with_comment: 19 },
    conversation_ratings: { positive: 0, negative: 0 },
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
      answer_ratings: { positive: 0, negative: 0, with_comment: 0 }
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

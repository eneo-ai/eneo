import { describe, expect, it } from "vitest";
import { analysisAnswerText, assistantActivityRows, mergeInsightSeries } from "./insights";

describe("mergeInsightSeries", () => {
  it("merges the three per-day series, fills gaps with 0, and sorts by day", () => {
    const rows = mergeInsightSeries({
      assistants: [{ created_at: "2026-06-02T00:00:00Z", count: 2 }],
      sessions: [
        { created_at: "2026-06-01T08:00:00Z", count: 5 },
        { created_at: "2026-06-02T09:00:00Z", count: 3 }
      ],
      questions: [{ created_at: "2026-06-01T10:00:00Z", count: 9 }]
    });

    expect(rows).toEqual([
      { date: "2026-06-01", assistants: 0, sessions: 5, questions: 9 },
      { date: "2026-06-02", assistants: 2, sessions: 3, questions: 0 }
    ]);
  });

  it("collapses multiple same-day buckets into one row", () => {
    const rows = mergeInsightSeries({
      assistants: [],
      sessions: [
        { created_at: "2026-06-01T01:00:00Z", count: 1 },
        { created_at: "2026-06-01T20:00:00Z", count: 4 }
      ],
      questions: []
    });
    expect(rows).toEqual([{ date: "2026-06-01", assistants: 0, sessions: 5, questions: 0 }]);
  });

  it("returns an empty array when all series are empty", () => {
    expect(mergeInsightSeries({ assistants: [], sessions: [], questions: [] })).toEqual([]);
  });
});

describe("assistantActivityRows", () => {
  it("aggregates session and question metadata by assistant id and sorts by activity", () => {
    const rows = assistantActivityRows({
      assistants: [],
      sessions: [
        {
          id: "session-1",
          assistant_id: "assistant-a",
          group_chat_id: null,
          created_at: "2026-06-01T08:00:00Z"
        },
        {
          id: "session-2",
          assistant_id: "assistant-b",
          group_chat_id: null,
          created_at: "2026-06-01T09:00:00Z"
        },
        {
          id: "session-3",
          assistant_id: null,
          group_chat_id: "group-1",
          created_at: "2026-06-01T10:00:00Z"
        }
      ],
      questions: [
        {
          id: "question-1",
          assistant_id: "assistant-b",
          session_id: "session-2",
          created_at: "2026-06-01T09:10:00Z"
        },
        {
          id: "question-2",
          assistant_id: "assistant-a",
          session_id: "session-1",
          created_at: "2026-06-01T08:10:00Z"
        },
        {
          id: "question-3",
          assistant_id: "assistant-a",
          session_id: "session-1",
          created_at: "2026-06-01T08:20:00Z"
        },
        {
          id: "question-4",
          assistant_id: null,
          session_id: "session-3",
          created_at: "2026-06-01T10:10:00Z"
        }
      ]
    });

    expect(rows).toEqual([
      {
        assistantId: "assistant-a",
        sessions: 1,
        questions: 2,
        latestAt: "2026-06-01T08:20:00Z"
      },
      {
        assistantId: "assistant-b",
        sessions: 1,
        questions: 1,
        latestAt: "2026-06-01T09:10:00Z"
      }
    ]);
  });

  it("respects the requested row limit", () => {
    const rows = assistantActivityRows(
      {
        assistants: [],
        sessions: [
          {
            id: "session-1",
            assistant_id: "assistant-a",
            group_chat_id: null,
            created_at: "2026-06-01T08:00:00Z"
          },
          {
            id: "session-2",
            assistant_id: "assistant-b",
            group_chat_id: null,
            created_at: "2026-06-01T09:00:00Z"
          }
        ],
        questions: []
      },
      1
    );

    expect(rows).toHaveLength(1);
  });
});

describe("analysisAnswerText", () => {
  it("extracts the backend answer string from unknown JSON", () => {
    expect(analysisAnswerText({ answer: "Use fewer follow-up prompts." })).toBe(
      "Use fewer follow-up prompts."
    );
  });

  it("returns null for unsupported payload shapes", () => {
    expect(analysisAnswerText(null)).toBeNull();
    expect(analysisAnswerText({ answer: 12 })).toBeNull();
    expect(analysisAnswerText(["answer"])).toBeNull();
  });
});

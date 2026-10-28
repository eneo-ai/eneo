import { describe, expect, it } from "vitest";
import {
  CHAT_ROUTE,
  compareRuns,
  parseRuns,
  quantile,
  summarize,
  worstInteractionMs
} from "../../tests/perf/metrics";

describe("perf baseline metrics", () => {
  it("counts only interactions that started at or after the measurement start", () => {
    const entries = [
      { interactionId: 7, startTime: 1_000, duration: 24 },
      // pointerover and other non-interaction events carry interactionId 0
      { interactionId: 0, startTime: 1_100, duration: 200 },
      // the chat submission before the measurement started
      { interactionId: 3, startTime: 400, duration: 120 },
      { interactionId: 8, startTime: 1_200, duration: 32 }
    ];
    expect(worstInteractionMs(entries, 1_000)).toBe(32);
    expect(worstInteractionMs([], 0)).toBe(0);
  });

  it("rejects RUNS that is not a positive integer", () => {
    expect(parseRuns(undefined)).toBe(10);
    expect(parseRuns("3")).toBe(3);
    for (const bad of ["0", "-1", "2.5", "abc", ""]) {
      expect(() => parseRuns(bad)).toThrow(/RUNS must be a positive integer/);
    }
  });

  it("summarizes medians and p75 per route and metric", () => {
    expect(quantile([4, 1, 3, 2], 0.5)).toBe(2.5);
    expect(summarize({ "/a": { lcp: [1, 2, 3, 4, 5] } })).toEqual({
      "/a": { lcp: { median: 3, p75: 4 } }
    });
  });

  it("judges two consecutive runs by the stability rule", () => {
    const medians = (values: Record<string, Record<string, number>>) =>
      Object.fromEntries(
        Object.entries(values).map(([route, byMetric]) => [
          route,
          Object.fromEntries(
            Object.entries(byMetric).map(([metric, median]) => [metric, { median, p75: median }])
          )
        ])
      );
    const first = medians({
      [CHAT_ROUTE]: {
        coldLcpMs: 324,
        warmLcpMs: 436,
        coldChatReadyMs: 200,
        chatTtftMs: 100,
        inpMs: 24,
        coldCls: 0.005,
        warmCls: 0
      },
      "/spaces/list": { coldLcpMs: 100, htmlEncodedBytes: 1_000, warmCls: 0 },
      "/admin/users": { coldLcpMs: 100 }
    });
    const second = medians({
      [CHAT_ROUTE]: {
        coldLcpMs: 460,
        warmLcpMs: 304,
        coldChatReadyMs: 235,
        chatTtftMs: 118,
        inpMs: 32,
        coldCls: 0.014,
        warmCls: 0.011
      },
      "/spaces/list": { coldLcpMs: 85, htmlEncodedBytes: 1_000, warmCls: 0 }
    });
    const verdicts = Object.fromEntries(
      compareRuns(first, second).map(({ route, metric, stable }) => [`${route} ${metric}`, stable])
    );
    expect(verdicts).toEqual({
      // Informational: the greeting h1 paints after a post-hydration render.
      [`${CHAT_ROUTE} coldLcpMs`]: null,
      [`${CHAT_ROUTE} warmLcpMs`]: null,
      // Medians within 15% of the larger one: 35 / 235 = 14.9%, 18 / 118 = 15.3%.
      [`${CHAT_ROUTE} coldChatReadyMs`]: true,
      [`${CHAT_ROUTE} chatTtftMs`]: false,
      // INP within one 8 ms step, CLS within 0.01 (absolute, not a percentage).
      [`${CHAT_ROUTE} inpMs`]: true,
      [`${CHAT_ROUTE} coldCls`]: true,
      [`${CHAT_ROUTE} warmCls`]: false,
      "/spaces/list coldLcpMs": true,
      "/spaces/list htmlEncodedBytes": true,
      "/spaces/list warmCls": true,
      // A metric the second run lacks is not stable.
      "/admin/users coldLcpMs": false
    });
  });
});

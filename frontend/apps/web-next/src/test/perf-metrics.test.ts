import { describe, expect, it } from "vitest";
import {
  CHAT_ROUTE,
  compareRuns,
  parseRuns,
  quantile,
  summarize,
  worstInteractionMs,
  type Metrics
} from "../../tests/perf/metrics";

/** Summaries whose every statistic is the given value, so the rule's choice of statistic does not matter. */
function summaries(values: Record<string, Record<string, number>>): Metrics {
  return Object.fromEntries(
    Object.entries(values).map(([route, byMetric]) => [
      route,
      Object.fromEntries(
        Object.entries(byMetric).map(([metric, value]) => [
          metric,
          { median: value, p75: value, mean: value }
        ])
      )
    ])
  );
}

function verdicts(first: Metrics, second: Metrics) {
  return Object.fromEntries(
    compareRuns(first, second).map(({ route, metric, stable }) => [`${route} ${metric}`, stable])
  );
}

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
    expect(parseRuns(undefined)).toBe(30);
    expect(parseRuns("3")).toBe(3);
    for (const bad of ["0", "-1", "2.5", "abc", ""]) {
      expect(() => parseRuns(bad)).toThrow(/RUNS must be a positive integer/);
    }
  });

  it("summarizes median and p75, plus the mean where the stability rule uses it", () => {
    expect(quantile([4, 1, 3, 2], 0.5)).toBe(2.5);
    expect(
      summarize({ "/a": { lcp: [1, 2, 3, 4, 5], coldChatReadyMs: [1, 2, 3, 4, 10] } })
    ).toEqual({
      "/a": { lcp: { median: 3, p75: 4 }, coldChatReadyMs: { median: 3, p75: 4, mean: 4 } }
    });
  });

  it("judges two consecutive runs by the stability rule", () => {
    const first = summaries({
      [CHAT_ROUTE]: {
        coldLcpMs: 324,
        warmLcpMs: 436,
        coldChatReadyMs: 200,
        chatTtftMs: 100,
        inpMs: 24,
        coldCls: 0.005,
        warmCls: 0
      },
      "/spaces/list": { coldLcpMs: 100, htmlEncodedBytes: 1_000, warmCls: 0 }
    });
    const second = summaries({
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
    expect(verdicts(first, second)).toEqual({
      // Informational: the greeting h1 paints after a post-hydration render.
      [`${CHAT_ROUTE} coldLcpMs`]: null,
      [`${CHAT_ROUTE} warmLcpMs`]: null,
      // Within 15% of the larger one: 35 / 235 = 14.9%, 18 / 118 = 15.3%.
      [`${CHAT_ROUTE} coldChatReadyMs`]: true,
      [`${CHAT_ROUTE} chatTtftMs`]: false,
      // INP within one 8 ms step, CLS within 0.01 (absolute, not a percentage).
      [`${CHAT_ROUTE} inpMs`]: true,
      [`${CHAT_ROUTE} coldCls`]: true,
      [`${CHAT_ROUTE} warmCls`]: false,
      "/spaces/list coldLcpMs": true,
      "/spaces/list htmlEncodedBytes": true,
      "/spaces/list warmCls": true
    });
  });

  it("treats a measurement only one run has as unstable, whichever run lacks it", () => {
    const full = summaries({
      [CHAT_ROUTE]: { coldChatReadyMs: 200, warmChatReadyMs: 150, coldLcpMs: 300 },
      "/admin/users": { coldLcpMs: 100 }
    });
    const partial = summaries({ [CHAT_ROUTE]: { coldChatReadyMs: 200 } });
    const expected = {
      [`${CHAT_ROUTE} coldChatReadyMs`]: true,
      [`${CHAT_ROUTE} warmChatReadyMs`]: false,
      // Missing is a gap even for the informational chat LCP.
      [`${CHAT_ROUTE} coldLcpMs`]: false,
      "/admin/users coldLcpMs": false
    };
    expect(verdicts(full, partial)).toEqual(expected);
    expect(verdicts(partial, full)).toEqual(expected);
  });

  it("compares chat readiness by its mean and the other timing metrics by their median", () => {
    const fast = (count: number) => Array<number>(count).fill(180);
    const slow = (count: number) => Array<number>(count).fill(450);
    const first = summarize({
      [CHAT_ROUTE]: {
        // Two modes: the mode share moves the median from one mode to the other.
        coldChatReadyMs: [...fast(5), ...slow(5)],
        // One mode: an outlier moves the mean, not the median.
        chatTtftMs: Array<number>(10).fill(150)
      }
    });
    const second = summarize({
      [CHAT_ROUTE]: {
        coldChatReadyMs: [...fast(4), ...slow(6)],
        chatTtftMs: [...Array<number>(9).fill(150), 1_500]
      }
    });
    // Readiness medians 315 vs 450 (30% apart), means 315 vs 342 (8%); TTFT
    // medians 150 vs 150, means 150 vs 285 (47%).
    expect(compareRuns(first, second)).toEqual([
      {
        route: CHAT_ROUTE,
        metric: "coldChatReadyMs",
        statistic: "mean",
        values: [315, 342],
        stable: true
      },
      {
        route: CHAT_ROUTE,
        metric: "chatTtftMs",
        statistic: "median",
        values: [150, 150],
        stable: true
      }
    ]);
    // A readiness summary without its mean is a gap.
    const withoutMean = { [CHAT_ROUTE]: { warmChatReadyMs: { median: 150, p75: 150 } } };
    expect(verdicts(withoutMean, withoutMean)).toEqual({
      [`${CHAT_ROUTE} warmChatReadyMs`]: false
    });
  });
});

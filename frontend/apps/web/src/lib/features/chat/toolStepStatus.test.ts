import { expect, it } from "vitest";
import { previousToolAttemptIndexes, toolStepStatus } from "./toolStepStatus";

it.each(["pending", "approved", "deferred"])(
  "does not claim success for interrupted %s calls",
  (status) => {
    expect(toolStepStatus(status, false, false)).toBe("failed");
  }
);
it("tracks admission and execution separately", () => {
  expect(toolStepStatus("pending", false, true)).toBe("preparing");
  expect(toolStepStatus("approved", false, true)).toBe("running");
});
it("keeps explicit outcomes and legacy history", () => {
  expect(toolStepStatus("succeeded", false, true, true)).toBe("complete");
  expect(toolStepStatus("failed", false, false)).toBe("failed");
  expect(toolStepStatus("approved", true, false)).toBe("denied");
  expect(toolStepStatus(undefined, false, false)).toBe("complete");
});

const chartCall = (result_status?: string, overrides = {}) => ({
  server_name: "charts",
  tool_name: "create_chart",
  result_status,
  ...overrides
});

it("softens an oversized chart attempt when split charts succeed", () => {
  const calls = [
    chartCall("failed", { arguments: { series: Array(10).fill({}) } }),
    chartCall("succeeded", { arguments: { series: Array(5).fill({}) } }),
    chartCall("succeeded", { arguments: { series: Array(5).fill({}) } })
  ];
  expect([...previousToolAttemptIndexes(calls)]).toEqual([0]);
  expect(calls[0].result_status).toBe("failed");
});

it("requires a later success, including after several failed attempts", () => {
  expect(previousToolAttemptIndexes([chartCall("succeeded"), chartCall("failed")]).size).toBe(0);
  expect(
    previousToolAttemptIndexes([chartCall("failed"), chartCall("failed"), chartCall("completed")])
  ).toEqual(new Set([0, 1]));
});

it("keeps a new failure visible after an earlier retry succeeded", () => {
  expect(
    previousToolAttemptIndexes([chartCall("failed"), chartCall("succeeded"), chartCall("failed")])
  ).toEqual(new Set([0]));
});

it.each([{ server_name: "other charts" }, { tool_name: "export_chart" }, { approved: false }])(
  "does not soften failures after an unrelated or denied success: %o",
  (overrides) => {
    expect(
      previousToolAttemptIndexes([chartCall("failed"), chartCall("succeeded", overrides)]).size
    ).toBe(0);
  }
);

it.each([undefined, "pending", "approved", "deferred", "failed", "denied", "timeout_denied"])(
  "does not infer a successful retry from %s",
  (status) => {
    expect(previousToolAttemptIndexes([chartCall("failed"), chartCall(status)]).size).toBe(0);
  }
);

it.each([undefined, "pending", "approved", "deferred", "denied", "timeout_denied"])(
  "preserves interrupted, denied and legacy %s calls",
  (status) => {
    expect(previousToolAttemptIndexes([chartCall(status), chartCall("succeeded")]).size).toBe(0);
  }
);

it("does not soften locally rejected calls", () => {
  expect(
    previousToolAttemptIndexes([chartCall("failed", { approved: false }), chartCall("succeeded")])
      .size
  ).toBe(0);
});

it("tracks multiple tools independently within the reply", () => {
  expect(
    previousToolAttemptIndexes([
      chartCall("failed"),
      chartCall("failed", { tool_name: "query_table" }),
      chartCall("succeeded")
    ])
  ).toEqual(new Set([0]));
  expect(previousToolAttemptIndexes([]).size).toBe(0);
});

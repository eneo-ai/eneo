import { describe, expect, test } from "vitest";

import {
  canRedispatchFlowRun,
  FLOW_RUN_STATUS_FILTER_OPTIONS,
  isFlowRunActive,
  isFlowRunAwaitingReview,
  isFlowRunCancellable,
  isFlowRunTerminal
} from "./flowRunStatusSets";

describe("flowRunStatusSets", () => {
  test("keeps awaiting review outside active and terminal sets", () => {
    expect(isFlowRunActive("awaiting_review")).toBe(false);
    expect(isFlowRunTerminal("awaiting_review")).toBe(false);
    expect(isFlowRunCancellable("awaiting_review")).toBe(true);
    expect(isFlowRunAwaitingReview("awaiting_review")).toBe(true);
  });

  test("identifies active, terminal, cancellable, and redispatchable run states", () => {
    expect(isFlowRunActive("queued")).toBe(true);
    expect(isFlowRunActive("running")).toBe(true);
    expect(isFlowRunActive("completed")).toBe(false);

    expect(isFlowRunTerminal("completed")).toBe(true);
    expect(isFlowRunTerminal("failed")).toBe(true);
    expect(isFlowRunTerminal("cancelled")).toBe(true);
    expect(isFlowRunTerminal("running")).toBe(false);

    expect(isFlowRunCancellable("queued")).toBe(true);
    expect(isFlowRunCancellable("cancelled")).toBe(false);
    expect(canRedispatchFlowRun("queued")).toBe(true);
    expect(canRedispatchFlowRun("running")).toBe(false);
  });

  test("includes awaiting review in the status filter options", () => {
    expect(FLOW_RUN_STATUS_FILTER_OPTIONS).toContain("awaiting_review");
  });
});

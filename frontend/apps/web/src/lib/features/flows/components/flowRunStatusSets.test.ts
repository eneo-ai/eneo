import { describe, expect, test } from "vitest";
import { FLOW_RUN_STATUS_CAPABILITIES, FLOW_RUN_STATUS_FILTER_ORDER } from "@eneo/eneo-js";

import {
  canRedispatchFlowRun,
  FLOW_RUN_STATUS_FILTER_OPTIONS,
  FLOW_RUN_STATUS_VALUES,
  isFlowRunActive,
  isFlowRunAwaitingReview,
  isFlowRunCancellable,
  shouldPollFlowRunStatus
} from "./flowRunStatusSets";

describe("flowRunStatusSets", () => {
  test("uses the generated backend capability table as the status source", () => {
    expect(FLOW_RUN_STATUS_VALUES).toEqual(
      FLOW_RUN_STATUS_CAPABILITIES.map((capability) => capability.status)
    );
    expect(FLOW_RUN_STATUS_FILTER_OPTIONS).toBe(FLOW_RUN_STATUS_FILTER_ORDER);
  });

  test("derives state helpers from generated backend capabilities", () => {
    for (const capability of FLOW_RUN_STATUS_CAPABILITIES) {
      expect(isFlowRunActive(capability.status)).toBe(capability.is_active);
      expect(shouldPollFlowRunStatus(capability.status)).toBe(capability.should_poll);
      expect(isFlowRunCancellable(capability.status)).toBe(capability.is_cancellable);
      expect(isFlowRunAwaitingReview(capability.status)).toBe(capability.is_awaiting_review);
      expect(canRedispatchFlowRun(capability.status)).toBe(capability.can_request_redispatch);
    }
  });

  test("keeps awaiting review outside the active set while still polling it", () => {
    expect(isFlowRunActive("awaiting_review")).toBe(false);
    expect(shouldPollFlowRunStatus("awaiting_review")).toBe(true);
    expect(isFlowRunCancellable("awaiting_review")).toBe(true);
    expect(isFlowRunAwaitingReview("awaiting_review")).toBe(true);
  });

  test("identifies active, cancellable, and redispatchable run states", () => {
    expect(isFlowRunActive("queued")).toBe(true);
    expect(isFlowRunActive("running")).toBe(true);
    expect(isFlowRunActive("completed")).toBe(false);

    expect(shouldPollFlowRunStatus("queued")).toBe(true);
    expect(shouldPollFlowRunStatus("running")).toBe(true);
    expect(shouldPollFlowRunStatus("completed")).toBe(false);

    expect(isFlowRunCancellable("queued")).toBe(true);
    expect(isFlowRunCancellable("cancelled")).toBe(false);
    expect(canRedispatchFlowRun("queued")).toBe(true);
    expect(canRedispatchFlowRun("running")).toBe(false);
  });

  test("includes awaiting review in the status filter options", () => {
    expect(FLOW_RUN_STATUS_FILTER_OPTIONS).toContain("awaiting_review");
    for (const status of FLOW_RUN_STATUS_VALUES) {
      expect(FLOW_RUN_STATUS_FILTER_OPTIONS).toContain(status);
    }
  });
});

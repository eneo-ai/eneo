import { expect, test } from "vitest";

import { getFlowRunStatusLabel } from "./flowRunStatusLabel";

const translations = {
  completed: () => "Completed",
  failed: () => "Failed",
  queued: () => "Queued",
  running: () => "Running",
  cancelled: () => "Cancelled",
};

test("maps known statuses to translated labels", () => {
  expect(getFlowRunStatusLabel("completed", translations)).toBe("Completed");
  expect(getFlowRunStatusLabel("cancelled", translations)).toBe("Cancelled");
});

test("maps pending status to queued translation", () => {
  expect(getFlowRunStatusLabel("pending", translations)).toBe("Queued");
});

test("falls back to raw status when unknown", () => {
  expect(getFlowRunStatusLabel("mystery-status", translations)).toBe("mystery-status");
});

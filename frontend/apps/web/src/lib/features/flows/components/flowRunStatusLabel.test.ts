import { expect, test } from "vitest";

import { getFlowRunStatusLabel } from "./flowRunStatusLabel";

const translations = {
  completed: () => "Completed",
  failed: () => "Failed",
  queued: () => "Queued",
  running: () => "Running",
  awaiting_review: () => "Awaiting review",
  cancelled: () => "Cancelled",
  unknown: () => "Unknown status"
};

test("maps known statuses to translated labels", () => {
  expect(getFlowRunStatusLabel("completed", translations)).toBe("Completed");
  expect(getFlowRunStatusLabel("cancelled", translations)).toBe("Cancelled");
  expect(getFlowRunStatusLabel("awaiting_review", translations)).toBe("Awaiting review");
});

test("maps pending status to queued translation", () => {
  expect(getFlowRunStatusLabel("pending", translations)).toBe("Queued");
});

test("names an unknown status in words instead of showing the raw value", () => {
  expect(getFlowRunStatusLabel("mystery-status", translations)).toBe("Unknown status");
});

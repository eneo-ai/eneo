import { expect, test } from "vitest";
import { shouldRefreshAfterJobUpdate } from "./JobManager";

test("job refresh is triggered when an active job completes", () => {
  const previous = new Map([["job-1", { status: "in progress" }]]);
  const updated = new Map([["job-1", { status: "complete" }]]);

  expect(shouldRefreshAfterJobUpdate(previous, updated)).toBe(true);
});

test("job refresh is triggered when an active job fails", () => {
  const previous = new Map([["job-1", { status: "queued" }]]);
  const updated = new Map([["job-1", { status: "failed" }]]);

  expect(shouldRefreshAfterJobUpdate(previous, updated)).toBe(true);
});

test("job refresh is triggered when an active job disappears from the running list", () => {
  const previous = new Map([["job-1", { status: "in progress" }]]);
  const updated = new Map<string, { status: string }>();

  expect(shouldRefreshAfterJobUpdate(previous, updated)).toBe(true);
});

test("job refresh is not triggered for unchanged active jobs", () => {
  const previous = new Map([["job-1", { status: "queued" }]]);
  const updated = new Map([["job-1", { status: "in progress" }]]);

  expect(shouldRefreshAfterJobUpdate(previous, updated)).toBe(false);
});

test("job refresh is not retriggered for already terminal jobs", () => {
  const previous = new Map([["job-1", { status: "failed" }]]);
  const updated = new Map([["job-1", { status: "failed" }]]);

  expect(shouldRefreshAfterJobUpdate(previous, updated)).toBe(false);
});

import { describe, expect, it } from "vitest";
import { makeRunGraph, makeRunStep, makeRunSummary } from "./run-fixtures";
import {
  outputStructured,
  outputText,
  progressSignature,
  runStepViews,
  tokenTotal
} from "./run-progress";

describe("runStepViews", () => {
  it("orders the run's steps with the graph's labels and fresher statuses", () => {
    const graph = makeRunGraph([
      { order: 2, label: "Skriv svar", status: "running" },
      { order: 1, label: "Sammanfatta", status: "completed" }
    ]);
    const steps = [makeRunStep(1), makeRunStep(2, { status: "pending" })];

    const views = runStepViews(graph, steps);

    expect(views.map((view) => [view.order, view.label, view.status])).toEqual([
      [1, "Sammanfatta", "completed"],
      [2, "Skriv svar", "running"]
    ]);
    expect(views[0]?.result?.id).toBe("result-1");
  });

  it("keeps a step result the graph does not name, and a step that has no result yet", () => {
    const graph = makeRunGraph([{ order: 1, label: "Sammanfatta", status: "pending" }]);
    const views = runStepViews(graph, [makeRunStep(3)]);
    expect(views.map((view) => [view.order, view.result?.id ?? null])).toEqual([
      [1, null],
      [3, "result-3"]
    ]);
  });
});

describe("progressSignature", () => {
  it("changes when the run's revision or a step's status moves, and only then", () => {
    const graph = makeRunGraph([{ order: 1, label: "A", status: "running" }]);
    const run = makeRunSummary({ status: "running", revision: 2 });
    const same = progressSignature(run, graph);

    expect(
      progressSignature({ ...run }, makeRunGraph([{ order: 1, label: "B", status: "running" }]))
    ).toBe(same);
    expect(progressSignature({ ...run, revision: 3 }, graph)).not.toBe(same);
    expect(
      progressSignature(run, makeRunGraph([{ order: 1, label: "A", status: "completed" }]))
    ).not.toBe(same);
  });
});

describe("step output", () => {
  it("reads the text or the structured value a step produced", () => {
    expect(outputText({ text: "Hej" })).toBe("Hej");
    expect(outputText({ structured: { a: 1 } })).toBeNull();
    expect(outputStructured({ structured: { a: 1 }, text: '{"a":1}' })).toEqual({ a: 1 });
    expect(outputStructured({ text: "Hej" })).toBeUndefined();
  });

  it("adds tokens up only when the core counted any", () => {
    expect(tokenTotal(600, 150)).toBe(750);
    expect(tokenTotal(null, 150)).toBe(150);
    expect(tokenTotal(null, undefined)).toBeNull();
  });
});

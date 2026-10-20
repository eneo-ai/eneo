import { describe, expect, it } from "vitest";
import { flowFixture } from "./flow-fixtures";
import {
  flowOversight,
  schemaFieldRows,
  stepProduces,
  stepReads,
  stepUsedBy,
  templatesOf
} from "./flow-reads";
import { stepsOf } from "./types";

const definition = flowFixture.definition;
const steps = stepsOf(definition);
const byKey = (key: string) => steps.find((step) => step.key === key)!;

describe("stepReads", () => {
  it("lists a model step's references, files and knowledge once each, in order", () => {
    const reads = stepReads(byKey("summary"), definition);
    expect(
      reads.map((read) => (read.kind === "knowledge" ? read.id : `${read.kind}:${read.key}`))
    ).toEqual(["step:check", "form:kind", "form:recording", "collection-1", "website-1"]);
    const review = reads[0]!;
    expect(review.kind === "step" && review.step?.kind).toBe("review");
    expect(review.kind === "step" && review.index).toBe(1);
  });

  it("reads the step before as {{previous}} and a review's target as a step", () => {
    const minutes = stepReads(byKey("minutes"), definition);
    expect(minutes.find((read) => read.kind === "step")).toMatchObject({
      key: "intro",
      previous: true,
      index: 3
    });
    expect(stepReads(byKey("check"), definition)).toEqual([
      expect.objectContaining({ kind: "step", key: "transcript", previous: false })
    ]);
    expect(stepReads(byKey("transcript"), definition)).toEqual([
      expect.objectContaining({ kind: "form", key: "recording", file: true })
    ]);
  });

  it("collects the templates of a function step's arguments", () => {
    expect(templatesOf(byKey("chart"))).toEqual(["{{steps.summary.json.decisions}}", "bar"]);
    expect(stepReads(byKey("chart"), definition)).toEqual([
      expect.objectContaining({ kind: "step", key: "summary" })
    ]);
  });
});

describe("stepUsedBy", () => {
  it("names the later steps that read a step, and how", () => {
    expect(stepUsedBy("summary", definition).map((use) => [use.step.key, use.via])).toEqual([
      ["intro", "key"],
      ["chart", "key"]
    ]);
    expect(stepUsedBy("transcript", definition).map((use) => [use.step.key, use.via])).toEqual([
      ["check", "review"]
    ]);
    expect(stepUsedBy("intro", definition).map((use) => [use.step.key, use.via])).toEqual([
      ["minutes", "previous"]
    ]);
    expect(stepUsedBy("chart", definition)).toEqual([]);
  });
});

describe("stepProduces", () => {
  it("describes each kind's output", () => {
    expect(stepProduces(byKey("summary"))).toEqual({
      kind: "json",
      fields: ["decisions", "actions", "kind"]
    });
    expect(stepProduces(byKey("intro"))).toEqual({ kind: "text" });
    expect(stepProduces(byKey("minutes"))).toEqual({
      kind: "file",
      format: "template",
      filename: "protokoll-{{form.meeting_date}}"
    });
    expect(stepProduces(byKey("chart"))).toEqual({
      kind: "function",
      purpose: "charts",
      tool: "render_chart"
    });
    expect(stepProduces(byKey("transcript"))).toEqual({ kind: "transcript" });
  });
});

describe("schemaFieldRows", () => {
  it("reads each top-level field's shape and whether it is required", () => {
    const step = byKey("summary");
    const schema = step.kind === "llm" && step.output?.type === "json" ? step.output.schema : {};
    expect(schemaFieldRows(schema)).toEqual([
      { name: "decisions", shape: "list", detail: ["text"], required: true },
      { name: "actions", shape: "list", detail: ["text"], required: false },
      { name: "kind", shape: "one_of", detail: ["Nämnd", "AU"], required: false }
    ]);
    expect(schemaFieldRows({})).toEqual([]);
  });
});

describe("flowOversight", () => {
  it("counts the kinds and finds the review gate and the steps after it", () => {
    expect(flowOversight(definition)).toEqual({
      counts: { transcribe: 1, review: 1, llm: 1, compose: 1, document: 1, function: 1 },
      gate: { index: 1, targetIndex: 0, afterFrom: 3, afterTo: 6 }
    });
    expect(flowOversight({ steps: steps.filter((step) => step.kind !== "review") }).gate).toBe(
      null
    );
  });
});

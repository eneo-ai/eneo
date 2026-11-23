import { describe, expect, it } from "vitest";
import type { OutputMode, OutputType } from "./editor/step-types";
import { flowDeliverables } from "./flow-deliverables";
import { makeStep } from "./flow-fixtures";
import type { FlowStep } from "./flows-api";

type Facts = { type: OutputType; mode?: OutputMode; marked?: boolean; sends?: boolean };

/** Steps in order from their facts, as the core's rule reads them. */
function stepsOf(facts: readonly Facts[]): FlowStep[] {
  return facts.map(({ type, mode = "pass_through", marked = false, sends = false }, index) =>
    makeStep(index + 1, {
      output_type: type,
      output_mode: sends ? "http_post" : mode,
      output_config: {
        ...(marked ? { deliverable: { label: `Resultat ${index + 1}` } } : {}),
        ...(mode === "http_post" || sends
          ? {
              url: "https://mottagare.example/in",
              auth: { mode: "none" },
              body: { mode: sends ? "run_result" : "auto" }
            }
          : {})
      }
    })
  );
}

const positions = (facts: readonly Facts[]) => {
  const steps = stepsOf(facts);
  return flowDeliverables(steps).deliverables.map((step) => steps.indexOf(step));
};

const text: Facts = { type: "text" };
const word: Facts = { type: "docx", mode: "render_verbatim" };
const send: Facts = { type: "text", sends: true };
const post: Facts = { type: "text", mode: "http_post" };

// The same table as the core's (test_run_deliverables.py), so the editor and
// publishing choose alike.
describe("flowDeliverables, the core's table", () => {
  it.each<[string, Facts[], number[]]>([
    ["no steps", [], []],
    ["one text", [text], [0]],
    ["one JSON", [{ type: "json" }], []],
    ["the last document", [text, { type: "pdf", mode: "render_verbatim" }], [1]],
    ["a marked document and the last text", [{ type: "docx", marked: true }, text], [0, 1]],
    ["a marked and the last document", [{ type: "docx", marked: true }, { type: "docx" }], [0, 1]],
    ["a document before JSON", [{ type: "pdf" }, { type: "json" }], []],
    ["a marked text before JSON", [{ type: "text", marked: true }, { type: "json" }], [0]],
    ["a marked document request", [{ type: "docx", mode: "http_post", marked: true }], []],
    ["a marked text request", [{ type: "text", mode: "http_post", marked: true }], []]
  ])("%s", (_, facts, expected) => {
    expect(positions(facts)).toEqual(expected);
  });

  it.each<[string, Facts[], number[]]>([
    ["text before the send", [text, send], [0]],
    ["a document before the send", [word, send], [0]],
    ["JSON before the send is passed over", [text, { type: "json" }, send], []],
    ["a marked text before JSON", [{ type: "text", marked: true }, { type: "json" }, send], [0]],
    ["a plain request is last and sends itself", [word, post], []],
    ["the send alone", [send], []],
    [
      "marked documents once, in order",
      [{ ...word, marked: true }, { ...word, marked: true }, send],
      [0, 1]
    ]
  ])("%s", (_, facts, expected) => {
    expect(positions(facts)).toEqual(expected);
  });

  it.each([
    [false, 2],
    [true, 3]
  ])("markdown, Word 1 kept, Word 2, send (text kept: %s) gives %i", (textMarked, count) => {
    const facts = [{ ...text, marked: textMarked }, { ...word, marked: true }, word, send];
    expect(positions(facts)).toHaveLength(count);
    expect(positions(facts)).toEqual(textMarked ? [0, 1, 2] : [1, 2]);
  });
});

describe("flowDeliverables, the editor's cases", () => {
  it.each<[string, Facts[], number[]]>([
    ["text, Word 1 kept, Word 2, send", [text, { ...word, marked: true }, word, send], [1, 2]],
    ["text, send", [text, send], [0]],
    ["text, Word, no send", [text, word], [1]],
    [
      "text 1 kept, text 2 kept, Word, send",
      [{ ...text, marked: true }, { ...text, marked: true }, word, send],
      [0, 1, 2]
    ],
    ["text, JSON, send", [text, { type: "json" }, send], []],
    ["text kept, JSON, send", [{ ...text, marked: true }, { type: "json" }, send], [0]]
  ])("%s", (_, facts, expected) => {
    expect(positions(facts)).toEqual(expected);
  });
});

describe("flowDeliverables, why and what else", () => {
  it("names the step included by its place and the send step", () => {
    const steps = stepsOf([text, word, send]);
    const plan = flowDeliverables(steps);
    expect(plan.byPlace).toEqual({ step: steps[1], place: "before_send" });
    expect(plan.sender).toBe(steps[2]);
    expect(plan.candidates).toEqual([steps[0]]);
  });

  it("calls the last step's place last when nothing sends", () => {
    const steps = stepsOf([word, text]);
    expect(flowDeliverables(steps).byPlace).toEqual({ step: steps[1], place: "last" });
    expect(flowDeliverables(steps).sender).toBeNull();
  });

  it("has no step by its place when the step there cannot be delivered", () => {
    const steps = stepsOf([text, { type: "json" }, send]);
    const plan = flowDeliverables(steps);
    expect(plan.byPlace).toBeNull();
    expect(plan.candidates).toEqual([steps[0]]);
  });

  it("reads the steps in step order, whatever order they come in", () => {
    const steps = stepsOf([text, word, send]);
    const plan = flowDeliverables([steps[2]!, steps[0]!, steps[1]!]);
    expect(plan.deliverables).toEqual([steps[1]]);
    expect(plan.sender).toBe(steps[2]);
  });
});

import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import {
  getRecommendedTemplates,
  filterTemplates,
  templateToAddStepOptions,
  resolveTemplateSeed,
  FLOW_STEP_TEMPLATES
} from "./flowStepTemplates";
import {
  getFlowStepValidationIssues,
  mapOutputToInputType,
  type FlowStepLike
} from "./flowStepTypes";

describe("getRecommendedTemplates", () => {
  it("recommends content templates and defers the JSON renderer when the previous output is text", () => {
    const { recommended, more } = getRecommendedTemplates("text");
    expect(recommended.some((t) => t.id === "summarize")).toBe(true);
    expect(recommended.some((t) => t.id === "render_text")).toBe(false);
    expect(more.some((t) => t.id === "render_text")).toBe(true);
  });

  it("recommends the JSON renderer only when the previous output is json", () => {
    const { recommended } = getRecommendedTemplates("json");
    expect(recommended.some((t) => t.id === "render_text")).toBe(true);
  });

  it("keeps the blank step out of recommendations for every previous output type", () => {
    for (const prev of ["text", "json", "pdf", "docx", null] as const) {
      const { recommended, more } = getRecommendedTemplates(prev);
      expect(recommended.some((t) => t.blank)).toBe(false);
      expect(more.some((t) => t.blank)).toBe(true);
    }
  });

  it("treats the first step (null previous) like a text input", () => {
    const { recommended } = getRecommendedTemplates(null);
    expect(recommended.some((t) => t.id === "summarize")).toBe(true);
    expect(recommended.some((t) => t.id === "render_text")).toBe(false);
  });

  it("partitions the whole catalog with no template dropped or duplicated", () => {
    const { recommended, more } = getRecommendedTemplates("json");
    expect(recommended.length + more.length).toBe(FLOW_STEP_TEMPLATES.length);
  });
});

describe("filterTemplates", () => {
  it("returns everything for an empty query", () => {
    expect(filterTemplates(FLOW_STEP_TEMPLATES, "  ")).toHaveLength(FLOW_STEP_TEMPLATES.length);
  });

  it("matches on name case-insensitively", () => {
    const hits = filterTemplates(FLOW_STEP_TEMPLATES, "sammanfatta");
    expect(hits.some((t) => t.id === "summarize")).toBe(true);
    expect(hits.every((t) => t.id !== "review")).toBe(true);
  });

  it("matches on aliases so the document template surfaces for a 'pdf' search", () => {
    const hits = filterTemplates(FLOW_STEP_TEMPLATES, "pdf");
    expect(hits.some((t) => t.id === "document")).toBe(true);
  });
});

describe("resolveTemplateSeed", () => {
  const document = FLOW_STEP_TEMPLATES.find((t) => t.id === "document")!;

  it("creates a Word (docx) step when docx is chosen", () => {
    expect(resolveTemplateSeed(document, "docx")).toMatchObject({ output_type: "docx" });
  });

  it("creates a PDF step when pdf is chosen", () => {
    expect(resolveTemplateSeed(document, "pdf")).toMatchObject({ output_type: "pdf" });
  });

  it("ignores the format for non-document templates", () => {
    const summarize = FLOW_STEP_TEMPLATES.find((t) => t.id === "summarize")!;
    expect(resolveTemplateSeed(summarize, "pdf")).toMatchObject({ output_type: "text" });
  });

  it("returns null for the blank template regardless of format", () => {
    const blank = FLOW_STEP_TEMPLATES.find((t) => t.blank)!;
    expect(resolveTemplateSeed(blank, "pdf")).toBeNull();
  });
});

describe("templateToAddStepOptions", () => {
  it("returns null for the blank template so it can never be seeded as a named step", () => {
    const blank = FLOW_STEP_TEMPLATES.find((t) => t.blank);
    expect(blank).toBeDefined();
    expect(templateToAddStepOptions(blank!)).toBeNull();
  });

  it("returns the output shape + name for a configured template", () => {
    const extract = FLOW_STEP_TEMPLATES.find((t) => t.id === "extract")!;
    expect(templateToAddStepOptions(extract)).toMatchObject({
      output_type: "json",
      output_mode: "pass_through"
    });
  });
});

// Proves the central claim: seeding a step from any configured template yields
// a step that passes structural validation wherever it is inserted. Mirrors how
// FlowEditor.addStep derives the input side from position.
describe("configured templates produce valid steps at every insertion position", () => {
  const PREVIOUS_OUTPUTS: (FlowStep["output_type"] | null)[] = [
    null,
    "text",
    "json",
    "pdf",
    "docx"
  ];
  const configured = FLOW_STEP_TEMPLATES.filter((t) => !t.blank);

  for (const template of configured) {
    for (const previousOutput of PREVIOUS_OUTPUTS) {
      it(`${template.id} after ${previousOutput ?? "no"} previous output`, () => {
        const seed = templateToAddStepOptions(template);
        expect(seed).not.toBeNull();

        const isFirst = previousOutput === null;
        const steps: FlowStepLike[] = [];
        if (!isFirst) {
          steps.push({
            step_order: 1,
            input_source: "flow_input",
            input_type: "text",
            output_type: previousOutput
          });
        }
        steps.push({
          step_order: isFirst ? 1 : 2,
          input_source: isFirst ? "flow_input" : "previous_step",
          input_type: isFirst ? "text" : mapOutputToInputType(previousOutput ?? undefined),
          output_type: seed!.output_type ?? "text"
        });

        expect(getFlowStepValidationIssues(steps)).toHaveLength(0);
      });
    }
  }
});

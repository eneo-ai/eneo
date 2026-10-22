import { describe, expect, it } from "vitest";
import { makeFlow, makeStep } from "../flow-fixtures";
import {
  answerShape,
  modelParameters,
  previewParts,
  readMeaning,
  readTone
} from "./request-preview";

const flow = makeFlow({
  steps: [
    makeStep(1, { user_description: "Sammanfatta" }),
    makeStep(2, { user_description: "Bedöm", output_type: "json" }),
    makeStep(3, { user_description: "Svara" })
  ],
  metadata_json: {
    form_schema: { fields: [{ name: "diarienummer", label: "Diarienummer", type: "text" }] }
  }
});

describe("readMeaning", () => {
  it("names each reference for what it reads, with the step list's grammar", () => {
    expect(readMeaning("flow_input.diarienummer", 3, flow)).toEqual({
      kind: "form_field",
      label: "Diarienummer"
    });
    expect(readMeaning("step_input.text", 3, flow)).toEqual({ kind: "upload" });
    expect(readMeaning("step_1.output.text", 3, flow)).toEqual({ kind: "step_answer", order: 1 });
    expect(readMeaning("step_2.output.structured.beslut", 3, flow)).toEqual({
      kind: "step_field",
      order: 2,
      field: "beslut"
    });
    expect(readMeaning("Sammanfatta", 3, flow)).toEqual({ kind: "step_answer", order: 1 });
    expect(readMeaning("föregående_steg", 3, flow)).toEqual({ kind: "step_answer", order: 2 });
    expect(readMeaning("section_index", 3, flow, { sectionIndex: true })).toEqual({
      kind: "section_index"
    });
    expect(readMeaning("indata_text", 3, flow)).toEqual({ kind: "flow_input" });
  });

  it("marks a reference to a removed or later step as one the run cannot read", () => {
    expect(readMeaning("step_3.output.text", 2, flow)).toEqual({ kind: "missing", order: 3 });
    expect(readMeaning("step_1_deleted.output.text", 2, flow)).toEqual({
      kind: "missing",
      order: 1
    });
    expect(readMeaning("okänd_variabel", 2, flow)).toEqual({ kind: "other" });
  });

  it("warns about a reference that reads nothing where it stands", () => {
    const fields = readMeaning("step_1.output.structured.beslut", 3, flow);
    const whole = readMeaning("step_1.output.structured", 3, flow);
    const section = readMeaning("section_index", 3, flow);

    expect([fields, whole]).toEqual([
      { kind: "fields_of_text", order: 1 },
      { kind: "fields_of_text", order: 1 }
    ]);
    expect(section).toEqual({ kind: "section_index_unavailable" });
    expect([fields, section, readMeaning("okänd", 3, flow)].map(readTone)).toEqual([
      "warning",
      "warning",
      "warning"
    ]);
    expect(readTone(readMeaning("step_2.output.structured", 3, flow))).toBe("reads");
    expect(readTone(readMeaning("step_3.output.text", 2, flow))).toBe("missing");
  });

  it("keeps the text around the references", () => {
    expect(previewParts("Läs {{ step_1.output.text }} nu", 2, flow)).toEqual([
      { kind: "text", text: "Läs " },
      {
        kind: "read",
        token: "step_1.output.text",
        raw: "{{ step_1.output.text }}",
        meaning: { kind: "step_answer", order: 1 }
      },
      { kind: "text", text: " nu" }
    ]);
  });
});

describe("the answer and the model settings", () => {
  it("lists the contract's fields for a structured answer", () => {
    expect(
      answerShape({
        output_type: "json",
        output_contract: {
          properties: { beslut: { type: "string", description: " Bifall eller avslag " } }
        }
      })
    ).toEqual({ kind: "fields", fields: [{ name: "beslut", description: "Bifall eller avslag" }] });
    expect(answerShape({ output_type: "docx", output_contract: null })).toEqual({
      kind: "document",
      format: "docx"
    });
  });

  it("shows only the settings that are set", () => {
    expect(modelParameters({ temperature: 0.2, top_p: null, reasoning_effort: "low" })).toEqual([
      { name: "temperature", value: "0.2" },
      { name: "reasoning_effort", value: "low" }
    ]);
  });
});

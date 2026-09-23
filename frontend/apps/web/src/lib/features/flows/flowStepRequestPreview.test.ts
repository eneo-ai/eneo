import type { FlowStep } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { buildContext } from "./components/flowPromptVariables";
import { describeAnswerFields, describeTemplateSegments } from "./flowStepRequestPreview";

const step = (order: number, name: string | null, extra: Partial<FlowStep> = {}): FlowStep =>
  ({ step_order: order, user_description: name, output_type: "text", ...extra }) as FlowStep;

const sectioned = { input_config: { text_processing: { mode: "process_each_section" } } };
const steps = [
  step(1, "Transkribera"),
  step(2, "Plocka ut", { output_type: "json" }),
  step(3, "Sammanställ", { output_type: "json", ...sectioned })
];
const formSchema = {
  fields: [
    { name: "namn", label: "Brukarens namn", type: "text" },
    { name: "datum_mote", type: "date" }
  ]
};

function labels(text: string) {
  const context = buildContext(steps, formSchema, true, 3, true);
  return describeTemplateSegments(text, context, formSchema)
    .filter((segment) => segment.kind === "variable")
    .map((segment) => segment.label);
}

describe("describeTemplateSegments", () => {
  it("keeps the text around each variable in order", () => {
    const context = buildContext(steps, formSchema, false, 3);
    expect(describeTemplateSegments("Hej {{flow_input.namn}}!", context, formSchema)).toEqual([
      { kind: "text", value: "Hej " },
      { kind: "variable", token: "flow_input.namn", label: "Brukarens namn", category: "field" },
      { kind: "text", value: "!" }
    ]);
  });

  it("names form fields by their label, falling back to the field name", () => {
    expect(labels("{{flow_input.namn}} {{namn}} {{flow_input.datum_mote}}")).toEqual([
      "Brukarens namn",
      "Brukarens namn",
      "datum_mote"
    ]);
  });

  it("names run variables in words", () => {
    expect(
      labels("{{step_input.text}} {{section_index}} {{transkribering}} {{föregående_steg}}")
    ).toEqual([
      m.flow_variable_upload_label(),
      m.flow_variable_section_index_label(),
      m.flow_variable_transcription(),
      m.flow_variable_previous_step()
    ]);
  });

  it("names earlier step answers and their fields by step number", () => {
    expect(
      labels("{{Transkribera}} {{step_1.output.text}} {{step_2.output.structured.beslut}}")
    ).toEqual([
      m.flow_request_preview_step_answer({ step: 1 }),
      m.flow_request_preview_step_answer({ step: 1 }),
      m.flow_request_preview_step_field({ field: "beslut", step: 2 })
    ]);
  });

  it("leaves unknown and unavailable tokens raw", () => {
    expect(labels("{{okänd}} {{step_4.output.text}}")).toEqual(["okänd", "step_4.output.text"]);
  });
});

describe("describeAnswerFields", () => {
  it("describes text and document output without fields", () => {
    expect(describeAnswerFields(step(1, null))).toEqual({ kind: "free_text" });
    expect(describeAnswerFields(step(1, null, { output_type: "pdf" }))).toEqual({
      kind: "document",
      format: "pdf"
    });
  });

  it("lists top-level fields with title and description", () => {
    const answer = describeAnswerFields(
      step(1, null, {
        output_type: "json",
        output_contract: {
          type: "object",
          properties: {
            stod_i_vardagen: { type: "string", description: "Vilket stöd som behövs" },
            grund: { type: "string", title: "Grunduppgifter" }
          }
        }
      })
    );
    expect(answer).toEqual({
      kind: "fields",
      perSection: false,
      fields: [
        {
          name: "stod_i_vardagen",
          label: "Stod i vardagen",
          description: "Vilket stöd som behövs"
        },
        { name: "grund", label: "Grunduppgifter" }
      ]
    });
  });

  it("lists the item fields of a section-by-section list", () => {
    const contract = {
      type: "object",
      properties: {
        poster: {
          type: "array",
          items: { type: "object", properties: { uppgift: { type: "string" } } }
        }
      }
    };
    const fields = [{ name: "uppgift", label: "Uppgift" }];
    expect(
      describeAnswerFields(
        step(3, null, { output_type: "json", output_contract: contract, ...sectioned })
      )
    ).toEqual({ kind: "fields", perSection: true, fields });
    expect(
      describeAnswerFields(step(3, null, { output_type: "json", output_contract: contract }))
    ).toEqual({ kind: "fields", perSection: false, fields });
  });
});

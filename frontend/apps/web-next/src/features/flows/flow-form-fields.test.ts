import { describe, expect, it } from "vitest";
import {
  evidenceExportAllowed,
  fieldNameIssue,
  formFieldProblems,
  formFieldsOf,
  metadataWithSettings,
  persistedFormFields,
  renamedFormFields,
  suggestedFieldName,
  type FormFieldDraft
} from "./flow-form-fields";

const draft = (overrides: Partial<FormFieldDraft>): FormFieldDraft => ({
  key: overrides.name ?? "k",
  name: "arende",
  label: "Ärende",
  type: "text",
  required: false,
  options: [],
  nameEdited: true,
  ...overrides
});

describe("formFieldsOf", () => {
  it("reads the fields in their order, with legacy types as text", () => {
    const fields = formFieldsOf({
      form_schema: {
        fields: [
          { name: "b", label: "B", type: "select", options: [" ja ", "", "nej"], order: 2 },
          { name: " a ", type: "email", required: true, order: 1 },
          "not a field"
        ]
      }
    });
    expect(
      fields.map(({ name, label, type, required, options }) => ({
        name,
        label,
        type,
        required,
        options
      }))
    ).toEqual([
      { name: "a", label: "a", type: "text", required: true, options: [] },
      { name: "b", label: "B", type: "select", required: false, options: ["ja", "nej"] }
    ]);
    expect(formFieldsOf(null)).toEqual([]);
  });
});

describe("persistedFormFields", () => {
  it("numbers the fields and keeps options only for choices", () => {
    expect(
      persistedFormFields([
        draft({ name: " arende ", label: "" }),
        draft({ name: "val", label: "Val", type: "select", options: ["a", " "] }),
        draft({ name: "text", type: "text", options: ["ignored"] })
      ])
    ).toEqual([
      { name: "arende", label: "arende", type: "text", required: false, order: 1 },
      { name: "val", label: "Val", type: "select", required: false, order: 2, options: ["a"] },
      { name: "text", label: "Ärende", type: "text", required: false, order: 3 }
    ]);
  });
});

describe("field names", () => {
  it("refuses names a step reads in another way", () => {
    expect(fieldNameIssue("flow_input")).toBe("namespace_head");
    expect(fieldNameIssue("Text")).toBe("reserved");
    expect(fieldNameIssue("step_2")).toBe("step_alias");
    expect(fieldNameIssue("a.b")).toBe("dot");
    expect(fieldNameIssue("diarienummer")).toBeNull();
  });

  it("suggests a free name from the label", () => {
    expect(suggestedFieldName("Ärendets nummer", [])).toBe("ärendets_nummer");
    expect(suggestedFieldName("Text", [])).toBe("user_text");
    expect(suggestedFieldName("Namn", ["namn", "NAMN_2"])).toBe("namn_3");
    expect(suggestedFieldName("  ", [])).toBe("field");
  });

  it("names each problem at its field", () => {
    expect(
      formFieldProblems([
        draft({ key: "1", name: "" }),
        draft({ key: "2", name: "namn" }),
        draft({ key: "3", name: "Namn", type: "multiselect", options: [" "] }),
        draft({ key: "4", name: "step_1" })
      ])
    ).toEqual([
      { key: "1", part: "name", problem: "required" },
      { key: "3", part: "name", problem: "duplicate" },
      { key: "3", part: "options", problem: "options_required" },
      { key: "4", part: "name", problem: "step_alias" }
    ]);
  });
});

describe("metadataWithSettings", () => {
  it("writes the form and the export switch and keeps the rest", () => {
    const metadata = { wizard: { transcription_enabled: true }, evidence_policy: { note: 1 } };
    expect(metadataWithSettings(metadata, [draft({})], false)).toEqual({
      wizard: { transcription_enabled: true },
      evidence_policy: { note: 1, allow_export: false },
      form_schema: {
        fields: [{ name: "arende", label: "Ärende", type: "text", required: false, order: 1 }]
      }
    });
    expect(metadataWithSettings(null, [], false)).toEqual({});
    expect(evidenceExportAllowed(metadataWithSettings(null, [], true))).toBe(true);
    expect(evidenceExportAllowed({ evidence_policy: { allow_export: "yes" } })).toBe(false);
  });
});

describe("renamedFormFields", () => {
  it("maps each saved field whose name changed to its new name", () => {
    const saved = [
      draft({ key: "saved-0", name: "kommun" }),
      draft({ key: "saved-1", name: "namn" })
    ];
    const fields = [
      draft({ key: "saved-0", name: " ort " }),
      draft({ key: "saved-1", name: "namn" }),
      draft({ key: "new-1", name: "datum_for_besok" })
    ];
    expect(renamedFormFields(saved, fields)).toEqual({ kommun: "ort" });
  });

  it("names no rename for a removed field or a field still without a name", () => {
    const saved = [draft({ key: "saved-0", name: "kommun" })];
    expect(renamedFormFields(saved, [])).toEqual({});
    expect(renamedFormFields(saved, [draft({ key: "saved-0", name: "  " })])).toEqual({});
  });
});

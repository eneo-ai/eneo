import { describe, expect, it } from "vitest";

import {
  buildFlowFormSchemaMetadata,
  flowFormFieldHasOptions,
  getFlowFormFieldNameIssue,
  getFlowFormFieldRuntimeKey,
  getFlowFormFieldVariableToken,
  getFlowFormSchemaFields,
  getFlowFormSchemaMetadata,
  getFlowFormStats,
  isFlowFormFieldNameUsableAsVariable,
  normalizeFlowFormFieldType,
  normalizeFlowFormFields,
  toPersistedFlowFormFields
} from "./flowFormSchema";

describe("flowFormSchema", () => {
  it("normalizes legacy text-like field types to text", () => {
    expect(normalizeFlowFormFieldType("email")).toBe("text");
    expect(normalizeFlowFormFieldType("textarea")).toBe("text");
    expect(normalizeFlowFormFieldType("string")).toBe("text");
  });

  it("keeps supported field types and option support stable", () => {
    expect(normalizeFlowFormFieldType("select")).toBe("select");
    expect(normalizeFlowFormFieldType("multiselect")).toBe("multiselect");
    expect(flowFormFieldHasOptions("select")).toBe(true);
    expect(flowFormFieldHasOptions("multiselect")).toBe(true);
    expect(flowFormFieldHasOptions("text")).toBe(false);
  });

  it("normalizes options and field order for editing/runtime use", () => {
    const normalized = normalizeFlowFormFields([
      {
        name: " second ",
        type: "multiselect",
        required: true,
        options: [" A ", "", "B"],
        order: 2
      },
      { name: "first", type: "email", options: [" ignored "], order: 1 }
    ]);

    expect(normalized).toEqual([
      { name: "first", type: "text", required: false, options: ["ignored"], order: 1 },
      { name: " second ", type: "multiselect", required: true, options: ["A", "B"], order: 2 }
    ]);
  });

  it("counts draft fields and required fields from the current editor state", () => {
    expect(getFlowFormStats([{ required: false }, { required: true }, { required: true }])).toEqual(
      {
        definedCount: 3,
        requiredCount: 2
      }
    );
  });

  it("builds variable tokens only for named fields", () => {
    expect(getFlowFormFieldVariableToken("titel")).toBe("{{titel}}");
    expect(getFlowFormFieldVariableToken("   ")).toBe("");
  });

  it("rejects field names that the backend resolver does not expose as aliases", () => {
    expect(getFlowFormFieldNameIssue("flow_input")).toBe("reserved");
    expect(getFlowFormFieldNameIssue("step_1")).toBe("step_alias");
    expect(getFlowFormFieldNameIssue("step_2.output.text")).toBe("step_alias");
    expect(getFlowFormFieldNameIssue("titel.sv")).toBe("dot");
    expect(getFlowFormFieldNameIssue("titel")).toBeNull();
  });

  it("matches UI variable availability to backend-safe field names", () => {
    expect(isFlowFormFieldNameUsableAsVariable("titel")).toBe(true);
    expect(isFlowFormFieldNameUsableAsVariable("föregående_steg")).toBe(false);
    expect(isFlowFormFieldNameUsableAsVariable("step_3")).toBe(false);
    expect(isFlowFormFieldNameUsableAsVariable("del.1")).toBe(false);
  });

  it("persists and resolves runtime field keys using trimmed names", () => {
    expect(getFlowFormFieldRuntimeKey(" titel ")).toBe("titel");
    expect(
      toPersistedFlowFormFields([{ name: " titel ", type: "text", required: true, options: [] }])
    ).toEqual([{ name: "titel", type: "text", required: true, order: 1 }]);
  });

  it("builds metadata with explicit form schema fields while preserving unrelated keys", () => {
    const fields = toPersistedFlowFormFields([
      { name: " titel ", type: "email", required: true, options: ["ignored"] },
      { name: "val", type: "select", required: false, options: [" A ", ""] }
    ]);

    expect(
      buildFlowFormSchemaMetadata(
        {
          wizard: { transcription_enabled: true },
          form_schema: { fields: [{ name: "old", type: "text", order: 1 }] }
        },
        fields
      )
    ).toEqual({
      wizard: { transcription_enabled: true },
      form_schema: {
        fields: [
          { name: "titel", type: "text", required: true, order: 1 },
          { name: "val", type: "select", required: false, order: 2, options: ["A"] }
        ]
      }
    });
  });

  it("keeps an explicit empty form schema for empty fields", () => {
    expect(buildFlowFormSchemaMetadata(null, [])).toEqual({
      form_schema: { fields: [] }
    });
    expect(buildFlowFormSchemaMetadata(undefined, [])).toEqual({
      form_schema: { fields: [] }
    });
  });

  it("reads form schema metadata through one helper", () => {
    const metadata = {
      form_schema: {
        fields: [{ name: "titel", type: "text", required: true, order: 1 }]
      }
    };

    expect(getFlowFormSchemaMetadata(metadata)).toEqual(metadata.form_schema);
    expect(getFlowFormSchemaFields(metadata)).toEqual(metadata.form_schema.fields);
    expect(getFlowFormSchemaMetadata({ form_schema: { fields: "invalid" } })).toBeUndefined();
    expect(getFlowFormSchemaFields(null)).toEqual([]);
  });
});

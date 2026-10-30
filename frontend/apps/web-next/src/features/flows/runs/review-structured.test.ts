import { describe, expect, it } from "vitest";
import {
  changedPaths,
  emptyValue,
  fieldKind,
  fieldLabel,
  formFits,
  itemPreview,
  objectFields,
  propertyPath,
  valuesEqual,
  withProperty
} from "./review-structured";

const row = {
  type: "object",
  required: ["text", "prioritet", "antal"],
  properties: {
    text: { type: "string", title: "Text" },
    prioritet: { type: "string", enum: ["hög", "låg"] },
    antal: { type: "integer" },
    klar: { type: "boolean" }
  }
};

describe("fieldKind", () => {
  it("gives each part of the contract the control its type asks for", () => {
    expect(fieldKind(row, {})).toBe("object");
    expect(fieldKind({ type: "array", items: row }, [])).toBe("array");
    expect(fieldKind(row.properties.text, "a")).toBe("string");
    expect(fieldKind(row.properties.prioritet, "hög")).toBe("enum");
    expect(fieldKind(row.properties.antal, null)).toBe("number");
    expect(fieldKind(row.properties.klar, "")).toBe("boolean");
    expect(fieldKind({ const: "Rubrik" }, "Rubrik")).toBe("readonly");
  });

  it("keeps what the form cannot express visible instead of guessing", () => {
    expect(fieldKind({ anyOf: [{ type: "string" }] }, "a")).toBe("unsupported");
    expect(fieldKind({ type: "object" }, {})).toBe("unsupported");
    // A stored value of another kind than the contract says is not replaced.
    expect(fieldKind(row.properties.antal, "tre")).toBe("unsupported");
    expect(fieldKind(row.properties.text, "a", 21)).toBe("unsupported");
  });
});

describe("formFits", () => {
  it("fits an object or list the contract describes", () => {
    expect(formFits({ type: "array", items: row }, [{ text: "a" }])).toBe(true);
    expect(formFits(row, { text: "a" })).toBe(true);
    expect(formFits(row, ["a"])).toBe(false);
    expect(formFits(null, { text: "a" })).toBe(false);
    expect(formFits(row.properties.text, "a")).toBe(false);
  });
});

describe("rows and properties", () => {
  it("starts a new row with its required properties empty, choosing nothing", () => {
    expect(emptyValue(row)).toEqual({ text: "", prioritet: "", antal: null });
    expect(emptyValue({ type: "array", items: row })).toEqual([]);
  });

  it("keeps properties the contract does not name", () => {
    expect(objectFields(row, { text: "a", extra: 1 }).map((field) => field.key)).toEqual([
      "text",
      "prioritet",
      "antal",
      "klar",
      "extra"
    ]);
    expect(withProperty({ text: "a", extra: 1 }, "text", "b")).toEqual({ text: "b", extra: 1 });
  });

  it("labels by title, else by the key in words, and previews a row by its text", () => {
    expect(fieldLabel(row.properties.text, "text")).toBe("Text");
    expect(fieldLabel({}, "due_date")).toBe("Due date");
    expect(
      itemPreview(row, { text: "Ring Anna", prioritet: "hög", antal: 1, not: "Före fredag" })
    ).toBe("Ring Anna");
  });
});

describe("changedPaths", () => {
  it("names each changed property and the objects around it", () => {
    const before = { sammanfattning: "A", detaljer: { datum: "2026-10-01", ort: "Sundsvall" } };
    const after = { sammanfattning: "A", detaljer: { datum: "2026-10-02", ort: "Sundsvall" } };
    expect([...changedPaths(before, after)].sort()).toEqual(["", "/detaljer", "/detaljer/datum"]);
    expect(changedPaths(before, structuredClone(before)).size).toBe(0);
  });

  it("compares a list as a whole", () => {
    const changed = changedPaths(
      { rader: [{ text: "a" }, { text: "b" }] },
      { rader: [{ text: "b" }] }
    );
    expect([...changed].sort()).toEqual(["", "/rader"]);
  });

  it("escapes keys that hold the path separator", () => {
    expect(propertyPath("", "a/b~c")).toBe("/a~1b~0c");
  });
});

describe("valuesEqual", () => {
  it("ignores the order of an object's keys", () => {
    expect(valuesEqual({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 })).toBe(true);
    expect(valuesEqual({ a: 1 }, { a: 1, b: null })).toBe(false);
  });
});

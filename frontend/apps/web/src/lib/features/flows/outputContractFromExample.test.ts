import { describe, expect, it } from "vitest";
import {
  contractFromExample,
  EXAMPLE_MAX_CHARACTERS,
  EXAMPLE_MAX_FIELDS
} from "./outputContractFromExample";

const objectOfFields = (count: number) =>
  JSON.stringify(Object.fromEntries(Array.from({ length: count }, (_, i) => [`f${i}`, 1])));

describe("contractFromExample", () => {
  // Kills: a wrong JSON Schema type per value kind (a whole number read as
  // "integer", so a later 20.5 is refused; a boolean as "string"), `required`
  // left out or not the example's keys, and keys written by assignment
  // (`__proto__` lost).
  it("declares every key of the example as a required field of its value's type", () => {
    const reading = contractFromExample(
      '{"anomaly_days": 4, "ratio": 1.5, "label": "x", "ok": true, "__proto__": "y"}'
    );
    expect(reading).toMatchObject({
      ok: true,
      contract: {
        type: "object",
        properties: {
          anomaly_days: { type: "number" },
          ratio: { type: "number" },
          label: { type: "string" },
          ok: { type: "boolean" },
          ["__proto__"]: { type: "string" }
        },
        required: ["anomaly_days", "ratio", "label", "ok", "__proto__"]
      },
      notes: []
    });
    expect(reading.ok && Object.keys(reading.contract.properties as object)).toContain("__proto__");
  });

  // Kills: lists typed by a later element instead of the first, nested
  // objects and lists left untyped, and the level cap off by one (the root is
  // level 1; a container below level 4 keeps only its type).
  it("types a list by its first element and reads nested values down to four levels", () => {
    const reading = contractFromExample(
      JSON.stringify({
        days: [{ date: "2026-01-01", value: 3 }, "ignored"],
        tags: ["a"],
        a: { b: { c: { d: { e: 1 } }, list: [[1]] } }
      })
    );
    expect(reading.ok && reading.contract.properties).toEqual({
      days: {
        type: "array",
        items: {
          type: "object",
          properties: { date: { type: "string" }, value: { type: "number" } },
          required: ["date", "value"]
        }
      },
      tags: { type: "array", items: { type: "string" } },
      a: {
        type: "object",
        properties: {
          b: {
            type: "object",
            properties: {
              c: {
                type: "object",
                properties: { d: { type: "object" } },
                required: ["d"]
              },
              list: { type: "array", items: { type: "array" } }
            },
            required: ["c", "list"]
          }
        },
        required: ["b"]
      }
    });
  });

  // Kills: an empty list or a null given a guessed element or value type
  // silently, and a note shown for an example that has neither.
  it("leaves an empty list's elements open and a null as text or empty, and says so", () => {
    expect(contractFromExample('{"rows": [], "note": null}')).toEqual({
      ok: true,
      contract: {
        type: "object",
        properties: { rows: { type: "array" }, note: { type: ["string", "null"] } },
        required: ["rows", "note"]
      },
      fields: [
        { name: "rows", shape: { kind: "list", item: null }, variable: true },
        { name: "note", shape: { kind: "text_or_empty" }, variable: true }
      ],
      notes: ["empty_list", "null_value"]
    });
  });

  // Kills: a list whose elements differ in kind or keys typed by its first
  // element without a note, and a note for a list of like elements.
  it.each([
    ['{"a": [1, "x"]}', ["mixed_list"]],
    ['{"a": [{"x": 1}, {"y": 2}]}', ["mixed_list"]],
    ['{"a": [{"x": 1, "y": 2}, {"y": 3, "x": 4}], "b": [1, 2.5]}', []]
  ])("notes for %s: %j", (text, notes) => {
    expect(contractFromExample(text)).toMatchObject({ ok: true, notes });
  });

  // Kills: a contract written from text that is not an object with fields,
  // from a number reading rounded, or from an example beyond the size bounds
  // (a cap checked off by one is killed by the at-the-cap case below).
  it.each([
    ["{oops", "syntax"],
    ["[1, 2]", "not_object"],
    ['"text"', "not_object"],
    ["{}", "no_fields"],
    ['{"id": 9007199254740993}', "inexact_number"],
    ['{"rows": [{"big": 1e999}]}', "inexact_number"],
    [objectOfFields(EXAMPLE_MAX_FIELDS + 1), "too_large"],
    ['{"a": "' + "x".repeat(EXAMPLE_MAX_CHARACTERS) + '"}', "too_large"]
  ])("refuses %s as %s", (text, problem) => {
    expect(contractFromExample(text)).toEqual({ ok: false, problem });
  });

  it("reads an example of exactly the field cap", () => {
    expect(contractFromExample(objectOfFields(EXAMPLE_MAX_FIELDS)).ok).toBe(true);
  });
});

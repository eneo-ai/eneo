import { describe, expect, it } from "vitest";
import { contractFromExample, EXAMPLE_MAX_CHARACTERS } from "./contract-from-example";

describe("contractFromExample", () => {
  it("makes every field of the example a required field of its type", () => {
    const reading = contractFromExample(
      JSON.stringify({ beslut: "Bifall", belopp: 4500, klar: true, datum: ["2026-01-02"] })
    );
    expect(reading).toMatchObject({
      ok: true,
      contract: {
        type: "object",
        properties: {
          beslut: { type: "string" },
          belopp: { type: "number" },
          klar: { type: "boolean" },
          datum: { type: "array", items: { type: "string" } }
        },
        required: ["beslut", "belopp", "klar", "datum"]
      },
      notes: []
    });
  });

  it("notes what one example cannot decide", () => {
    const reading = contractFromExample('{"a": [], "b": null, "c": [1, "x"]}');
    if (!reading.ok) throw new Error("expected a contract");
    expect(reading.notes.sort()).toEqual(["empty_list", "mixed_list", "null_value"]);
    expect(reading.contract.properties).toMatchObject({ b: { type: ["string", "null"] } });
  });

  it("marks a field a later step cannot refer to", () => {
    const reading = contractFromExample('{"a.b": 1, "ok": 2}');
    if (!reading.ok) throw new Error("expected a contract");
    expect(reading.fields.map((field) => [field.name, field.variable])).toEqual([
      ["a.b", false],
      ["ok", true]
    ]);
  });

  it("refuses text that gives no contract, saying why", () => {
    expect(contractFromExample("{")).toEqual({ ok: false, problem: "syntax" });
    expect(contractFromExample("[1]")).toEqual({ ok: false, problem: "not_object" });
    expect(contractFromExample("{}")).toEqual({ ok: false, problem: "no_fields" });
    expect(contractFromExample('{"n": 12345678901234567890}')).toEqual({
      ok: false,
      problem: "inexact_number"
    });
    expect(contractFromExample(" ".repeat(EXAMPLE_MAX_CHARACTERS + 1))).toEqual({
      ok: false,
      problem: "too_large"
    });
  });
});

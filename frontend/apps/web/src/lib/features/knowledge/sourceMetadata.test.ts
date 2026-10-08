import { describe, expect, it } from "vitest";
import {
  formatSourceMetadataValue,
  hasSourceMetadata,
  type SourceMetadataEntry
} from "./sourceMetadata";

const labels = { yes: "Ja", no: "Nej" };

const entry = (overrides: Partial<SourceMetadataEntry>): SourceMetadataEntry => ({
  name: "col",
  label: "Column",
  value: "",
  kind: "text",
  ...overrides
});

describe("formatSourceMetadataValue", () => {
  it("returns text values as stored", () => {
    expect(formatSourceMetadataValue(entry({ value: "Rutin" }), labels)).toBe("Rutin");
  });

  it("joins multi-value entries with commas", () => {
    expect(
      formatSourceMetadataValue(
        entry({ value: ["Äldreomsorg", "Hemtjänst"], kind: "choice" }),
        labels
      )
    ).toBe("Äldreomsorg, Hemtjänst");
  });

  it("shows a date-only column as the day it was entered", () => {
    expect(
      formatSourceMetadataValue(entry({ value: "2027-01-31T00:00:00Z", kind: "date" }), labels)
    ).toBe("2027-01-31");
  });

  it("formats a timestamp column as a local date and time", () => {
    const value = new Date(2026, 2, 5, 14, 30).toISOString();
    expect(formatSourceMetadataValue(entry({ value, kind: "date" }), labels)).toBe(
      "2026-03-05 14:30"
    );
  });

  it("falls back to the raw text for an unparsable date", () => {
    expect(formatSourceMetadataValue(entry({ value: "soon", kind: "date" }), labels)).toBe("soon");
  });

  it("translates yes/no columns", () => {
    expect(formatSourceMetadataValue(entry({ value: "true", kind: "boolean" }), labels)).toBe("Ja");
    expect(formatSourceMetadataValue(entry({ value: "False", kind: "boolean" }), labels)).toBe(
      "Nej"
    );
  });

  it("treats a missing kind as text", () => {
    expect(formatSourceMetadataValue(entry({ value: "x", kind: undefined }), labels)).toBe("x");
  });
});

describe("hasSourceMetadata", () => {
  it("is true only for a non-empty list", () => {
    expect(hasSourceMetadata({ source_metadata: [entry({ value: "a" })] })).toBe(true);
    expect(hasSourceMetadata({ source_metadata: [] })).toBe(false);
    expect(hasSourceMetadata({ source_metadata: null })).toBe(false);
    expect(hasSourceMetadata({})).toBe(false);
    expect(hasSourceMetadata(undefined)).toBe(false);
  });

  it.each([
    ["wrong"],
    [null],
    [{}],
    [{ name: "t", label: "Type", value: 42 }],
    [{ name: "t", label: "Type", value: ["Policy", null] }],
    [{ name: "t", label: "Type", value: "Policy", kind: "unsupported" }],
    [{ name: "t", value: "Policy" }],
    [entry({ value: "Policy" }), "wrong"],
    [entry({ value: "Policy" }), entry({ value: "Other" })]
  ])(
    "rejects malformed MCP properties before they reach the formatter (%j)",
    (...entries: unknown[]) => {
      expect(hasSourceMetadata({ source_metadata: entries })).toBe(false);
    }
  );

  it("accepts valid external properties with scalar or list values and optional kind", () => {
    const properties = [
      { name: "type", label: "Type", value: "Policy" },
      { name: "topics", label: "Topics", value: ["A", "B"], kind: "choice" }
    ];
    expect(hasSourceMetadata({ source_metadata: properties })).toBe(true);
  });
});

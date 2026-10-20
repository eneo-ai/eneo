import { m } from "$lib/paraglide/messages";
import { describe, expect, test } from "vitest";
import type { SecurityClassification } from "@eneo/eneo-js";
import {
  parseMimeOverrideDraft,
  getMimePresetsForFormat,
  MIME_PRESETS_DOCUMENT,
  MIME_PRESETS_AUDIO,
  getTemplateAssetStatusLabel,
  getSecurityClassificationLabel,
  getSecurityInheritanceLabel,
  getSelectableSecurityClassifications
} from "./flowStepEditHelpers";

describe("step editor summaries", () => {
  test("shows the inherited space classification when it is available", () => {
    expect(getSecurityInheritanceLabel({ security_level: 2, name: "Intern" })).toBe(
      "Ärvs automatiskt — Intern"
    );
    expect(getSecurityInheritanceLabel(null)).toBe("Ärvs automatiskt");
  });

  test("uses configured organization classifications at or above the space level", () => {
    const classifications = [
      { id: "public", name: "Publik", security_level: 1 },
      { id: "restricted", name: "Begränsad", security_level: 3 },
      { id: "internal", name: "Intern", security_level: 2 }
    ] as SecurityClassification[];

    const selectable = getSelectableSecurityClassifications(classifications, {
      security_level: 2
    });

    expect(selectable.map((classification) => classification.id)).toEqual([
      "internal",
      "restricted"
    ]);
    expect(getSecurityClassificationLabel(selectable[0])).toBe("Intern");
  });
});

// ---------------------------------------------------------------------------
// parseMimeOverrideDraft
// ---------------------------------------------------------------------------

describe("parseMimeOverrideDraft", () => {
  test("splits comma-separated values and trims whitespace", () => {
    expect(parseMimeOverrideDraft("text/csv , application/pdf")).toEqual([
      "text/csv",
      "application/pdf"
    ]);
  });

  test("filters out empty strings", () => {
    expect(parseMimeOverrideDraft("text/csv,,")).toEqual(["text/csv"]);
  });

  test("returns empty array for empty input", () => {
    expect(parseMimeOverrideDraft("")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// getMimePresetsForFormat
// ---------------------------------------------------------------------------

describe("getMimePresetsForFormat", () => {
  test("returns audio presets for audio format", () => {
    expect(getMimePresetsForFormat("audio")).toBe(MIME_PRESETS_AUDIO);
  });

  test("returns document presets for document format", () => {
    expect(getMimePresetsForFormat("document")).toBe(MIME_PRESETS_DOCUMENT);
  });

  test("returns document presets for any other format", () => {
    expect(getMimePresetsForFormat("file")).toBe(MIME_PRESETS_DOCUMENT);
  });
});

// ---------------------------------------------------------------------------
// getTemplateAssetStatusLabel
// ---------------------------------------------------------------------------

describe("getTemplateAssetStatusLabel", () => {
  test("maps ready", () => {
    expect(getTemplateAssetStatusLabel("ready")).toBe(m.flow_template_fill_asset_ready());
  });

  test("maps needs_action", () => {
    expect(getTemplateAssetStatusLabel("needs_action")).toBe(
      m.flow_template_fill_asset_needs_action()
    );
  });

  test("maps read_only", () => {
    expect(getTemplateAssetStatusLabel("read_only")).toBe(m.flow_template_fill_asset_read_only());
  });

  test("defaults to Unavailable for unknown", () => {
    expect(getTemplateAssetStatusLabel(null)).toBe(m.flow_template_fill_asset_unavailable());
    expect(getTemplateAssetStatusLabel(undefined)).toBe(m.flow_template_fill_asset_unavailable());
  });
});

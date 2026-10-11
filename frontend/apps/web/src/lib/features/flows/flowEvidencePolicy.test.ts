import { describe, expect, it } from "vitest";

import { flowAllowsEvidenceExport, withEvidenceExportAllowed } from "./flowEvidencePolicy";

describe("flowAllowsEvidenceExport", () => {
  it("is off until the flow says yes", () => {
    expect(flowAllowsEvidenceExport(null)).toBe(false);
    expect(flowAllowsEvidenceExport({})).toBe(false);
    expect(flowAllowsEvidenceExport({ evidence_policy: {} })).toBe(false);
    expect(flowAllowsEvidenceExport({ evidence_policy: { allow_export: false } })).toBe(false);
    expect(flowAllowsEvidenceExport({ evidence_policy: { allow_export: true } })).toBe(true);
  });

  it.each(["true", 1, "yes", [], {}])(
    "does not read %j as a yes: the server would refuse the download anyway",
    (stored) => {
      expect(flowAllowsEvidenceExport({ evidence_policy: { allow_export: stored } })).toBe(false);
      expect(flowAllowsEvidenceExport({ evidence_policy: stored })).toBe(false);
    }
  );
});

describe("withEvidenceExportAllowed", () => {
  it("changes only the switch and keeps the rest of the flow's metadata", () => {
    const metadata = {
      form_schema: { fields: [{ name: "case_id", type: "text" }] },
      care_data_policy: { sensitive: true },
      wizard: { transcription_enabled: true }
    };

    const allowed = withEvidenceExportAllowed(metadata, true);

    expect(allowed).toEqual({ ...metadata, evidence_policy: { allow_export: true } });
    expect(withEvidenceExportAllowed(allowed, false)).toEqual({
      ...metadata,
      evidence_policy: { allow_export: false }
    });
    expect(metadata).not.toHaveProperty("evidence_policy");
  });
});

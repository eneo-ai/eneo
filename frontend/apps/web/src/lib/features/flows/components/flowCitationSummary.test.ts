import { describe, expect, it } from "vitest";

import { readAttachedCitationSummary, readFlowCitationSummary } from "./flowCitationSummary";

const VALID = {
  status: "observed",
  sources: [{ identity_resolved: true, display_name: "Doc", container_label: "Docs" }],
  matched_cited_source_count: 1,
  sources_truncated: false,
  stale_after_edit: false
};

describe("readFlowCitationSummary", () => {
  it("returns null when there is no summary to show", () => {
    expect(readFlowCitationSummary(null)).toBeNull();
    expect(readFlowCitationSummary(undefined)).toBeNull();
  });

  it("passes a well-formed payload through unchanged", () => {
    expect(readFlowCitationSummary(VALID)).toEqual(VALID);
  });

  it("maps a present-but-malformed payload to an explicit unavailable state", () => {
    // A contract breach must be visible — never indistinguishable from off.
    const malformed: unknown[] = [
      "not an object",
      {},
      { ...VALID, status: "invented_status" },
      { ...VALID, sources: "not-a-list" },
      { ...VALID, matched_cited_source_count: "3" },
      { ...VALID, sources_truncated: undefined },
      { ...VALID, stale_after_edit: "yes" },
      { ...VALID, sources: [{ identity_resolved: "true" }] },
      { ...VALID, sources: [{ identity_resolved: true, display_name: 7, container_label: null }] },
      // Invariant breaches: impossible counts and truncation shapes must not
      // render as data.
      { ...VALID, matched_cited_source_count: -1 },
      { ...VALID, matched_cited_source_count: 1.5 },
      { ...VALID, matched_cited_source_count: 3 },
      { ...VALID, sources_truncated: true },
      {
        ...VALID,
        sources: Array.from({ length: 21 }, () => VALID.sources[0]),
        matched_cited_source_count: 21
      }
    ];
    for (const payload of malformed) {
      expect(readFlowCitationSummary(payload)).toEqual({
        status: "unavailable",
        sources: [],
        matched_cited_source_count: 0,
        sources_truncated: false,
        stale_after_edit: false
      });
    }
  });
});

describe("readAttachedCitationSummary", () => {
  it("reads the attached field and keeps absence null", () => {
    expect(readAttachedCitationSummary({ citation_summary: VALID })).toEqual(VALID);
    expect(readAttachedCitationSummary({ citation_summary: null })).toBeNull();
    expect(readAttachedCitationSummary({})).toBeNull();
    expect(readAttachedCitationSummary(null)).toBeNull();
  });

  it("surfaces a malformed attached payload as unavailable", () => {
    const parsed = readAttachedCitationSummary({ citation_summary: { status: "nonsense" } });
    expect(parsed?.status).toBe("unavailable");
  });
});

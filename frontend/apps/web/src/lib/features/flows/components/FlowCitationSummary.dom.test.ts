import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";
import { getLocale, setLocale } from "$lib/paraglide/runtime";

import FlowCitationSummary from "./FlowCitationSummary.svelte";
import type { FlowCitationSummary as Summary } from "./flowCitationSummary";

afterEach(() => {
  cleanup();
});

function makeSummary(overrides: Partial<Summary> = {}): Summary {
  return {
    status: "observed",
    sources: [{ identity_resolved: true, display_name: "Riktlinjer.pdf", container_label: "Docs" }],
    matched_cited_source_count: 1,
    sources_truncated: false,
    stale_after_edit: false,
    ...overrides
  };
}

describe("FlowCitationSummary", () => {
  it("renders observed status with the matched count and resolved source identity", () => {
    render(FlowCitationSummary, { summary: makeSummary() });
    expect(screen.getByText(m.flow_citation_status_observed({ count: "1" }))).toBeTruthy();
    expect(screen.getByText("Riktlinjer.pdf")).toBeTruthy();
  });

  it("renders each non-observed status line", () => {
    const cases: Array<[Summary["status"], string]> = [
      ["missing_required_citations", m.flow_citation_status_missing()],
      ["unknown_citation_ids_present", m.flow_citation_status_unknown()],
      ["citations_on_without_sources", m.flow_citation_status_no_sources()],
      ["unavailable", m.flow_citation_status_unavailable()]
    ];
    for (const [status, expected] of cases) {
      const { unmount } = render(FlowCitationSummary, {
        summary: makeSummary({ status, sources: [], matched_cited_source_count: 0 })
      });
      expect(screen.getByText(expected)).toBeTruthy();
      unmount();
    }
  });

  it("falls back to the localized unidentified label for unresolved sources in both locales", () => {
    const previousLocale = getLocale();
    try {
      for (const locale of ["sv", "en"] as const) {
        setLocale(locale, { reload: false });
        const { unmount } = render(FlowCitationSummary, {
          summary: makeSummary({
            sources: [{ identity_resolved: false, display_name: null, container_label: null }]
          })
        });
        expect(screen.getByText(m.flow_citation_source_unidentified())).toBeTruthy();
        unmount();
      }
    } finally {
      setLocale(previousLocale, { reload: false });
    }
  });

  it("renders the container label when it is the only recovered identity", () => {
    render(FlowCitationSummary, {
      summary: makeSummary({
        sources: [{ identity_resolved: true, display_name: null, container_label: "HR-mappen" }]
      })
    });
    expect(screen.getByText("HR-mappen")).toBeTruthy();
    expect(screen.queryByText(m.flow_citation_source_unidentified())).toBeNull();
  });

  it("shows a possible truncation denominator and the stale note", () => {
    const sources = Array.from({ length: 20 }, (_, index) => ({
      identity_resolved: true,
      display_name: `Doc ${index}`,
      container_label: null
    }));
    render(FlowCitationSummary, {
      summary: makeSummary({
        sources,
        matched_cited_source_count: 21,
        sources_truncated: true,
        stale_after_edit: true
      })
    });
    // 20 shown of 21 matched — the denominator can never be below the count.
    expect(
      screen.getByText(m.flow_citation_sources_truncated({ shown: "20", count: "21" }))
    ).toBeTruthy();
    expect(screen.getByText(m.flow_citation_stale_after_edit())).toBeTruthy();
  });
});

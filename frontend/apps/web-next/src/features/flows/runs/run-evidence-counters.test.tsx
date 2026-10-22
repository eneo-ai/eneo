// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { renderInApp } from "@/test/render";
import { EvidenceOmissions, KnowledgeViewCounters } from "./run-evidence-counters";

afterEach(cleanup);

describe("EvidenceOmissions", () => {
  it("counts what the view left out per section and why", () => {
    renderInApp(
      <EvidenceOmissions
        summary={
          {
            omissions: [
              { section: "provider_calls", reason: "row_limit", rows_omitted: 40 },
              {
                section: "step_attempts",
                reason: "logical_bytes",
                rows_omitted: 12,
                count_truncated: true
              }
            ]
          } as unknown as Schema<"FlowRunDebugRunSummary">
        }
      />
    );
    expect(screen.getByText(/”leverantörsanrop” som inte visas här: 40/)).toBeTruthy();
    expect(screen.getByText(/”stegförsök” som inte visas här: ≥12/)).toBeTruthy();
  });
});

describe("KnowledgeViewCounters", () => {
  it("counts the passages and attempts the knowledge view left out", () => {
    renderInApp(
      <KnowledgeViewCounters
        view={
          {
            passages_omitted: 5,
            attempts_not_loaded: 2,
            current_attempts_not_loaded: 1,
            current_step_orders_not_loaded: [3],
            count_truncated: false
          } as unknown as Schema<"FlowRunDebugKnowledgeEvidenceView">
        }
      />
    );
    expect(screen.getByText(/Textavsnitt som inte visas här: 5/)).toBeTruthy();
    expect(screen.getByText(/Försök som inte lästes in i den här vyn: 2/)).toBeTruthy();
    expect(screen.getByText(/bland annat steg nummer 3/)).toBeTruthy();
  });

  it("says nothing when nothing was left out", () => {
    const { container } = renderInApp(
      <KnowledgeViewCounters
        view={
          {
            passages_omitted: 0,
            count_truncated: false
          } as unknown as Schema<"FlowRunDebugKnowledgeEvidenceView">
        }
      />
    );
    expect(container.querySelector("ul")).toBeNull();
  });
});

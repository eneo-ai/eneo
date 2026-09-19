import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import type { FlowRunDebugExport } from "@eneo/eneo-js";

import { m } from "$lib/paraglide/messages";
import FlowRunEvidenceToolbar from "./FlowRunEvidenceToolbar.svelte";

afterEach(cleanup);

function diagnostics(): FlowRunDebugExport {
  return {
    schema_version: "eneo.flow.debug-export.v3",
    generated_at: "2026-09-19T12:00:00Z",
    run: { run_id: "run-1", flow_id: "flow-1", flow_version: 1, status: "failed" },
    definition: { flow_id: "flow-1", version: 1, checksum: "abc", steps_count: 0 },
    steps: [],
    security: {
      content_included: false,
      redaction_applied: true,
      classification_field: "output_classification_override"
    }
  };
}

function actions() {
  return {
    onDownloadCanonicalEvidence: vi.fn().mockResolvedValue(undefined),
    onCopyPayload: vi.fn().mockResolvedValue(undefined),
    onDownloadJsonArtifact: vi.fn()
  };
}

it("exports only diagnostic data for sensitive flows and offers no full-content copy", async () => {
  const debugExport = diagnostics();
  const handlers = actions();
  render(FlowRunEvidenceToolbar, {
    debugExport,
    copiedKey: null,
    sensitiveCareDataFlow: true,
    ...handlers
  });

  await fireEvent.click(screen.getByRole("button", { name: m.flow_run_copy_debug_export() }));
  expect(handlers.onCopyPayload).toHaveBeenCalledWith(
    "debug-export",
    debugExport,
    m.flow_run_copy_debug_export_failed()
  );
  await fireEvent.click(screen.getByRole("button", { name: m.flow_run_download_debug_export() }));
  expect(handlers.onDownloadJsonArtifact).toHaveBeenCalledWith(
    "flow-debug-export-run-1.json",
    debugExport,
    m.flow_run_download_debug_export_failed()
  );
  expect(screen.getAllByRole("button")).toHaveLength(2);
  expect(screen.getByText(m.flow_sensitive_evidence_export_disabled())).toBeTruthy();
  expect(screen.queryByText(m.flow_run_evidence_content_heading())).toBeNull();
  expect(screen.queryByRole("button", { name: m.flow_run_download_evidence_export() })).toBeNull();
  expect(handlers.onDownloadCanonicalEvidence).not.toHaveBeenCalled();
});

it("withholds debug sharing until the server explicitly supplies a content-free version", () => {
  // Older servers used the same field for prompts, schema examples and source text.
  const legacy = { ...diagnostics(), schema_version: "eneo.flow.debug-export.v2" };
  const handlers = actions();
  render(FlowRunEvidenceToolbar, {
    debugExport: legacy as FlowRunDebugExport,
    copiedKey: null,
    sensitiveCareDataFlow: false,
    ...handlers
  });

  expect(screen.getByText(m.flow_run_debug_content_unavailable())).toBeTruthy();
  expect(screen.queryByRole("button", { name: m.flow_run_copy_debug_export() })).toBeNull();
  expect(screen.queryByRole("button", { name: m.flow_run_download_debug_export() })).toBeNull();
  expect(
    screen.getByRole("button", { name: m.flow_run_download_evidence_export(), hidden: true })
  ).toBeTruthy();
  expect(handlers.onCopyPayload).not.toHaveBeenCalled();
});

it("labels content-bearing evidence separately and keeps it collapsed initially", async () => {
  const handlers = actions();
  render(FlowRunEvidenceToolbar, { debugExport: diagnostics(), copiedKey: null, ...handlers });

  const heading = screen.getByText(m.flow_run_evidence_content_heading());
  const disclosure = heading.closest("details");
  expect(disclosure?.open).toBe(false);
  expect(screen.getByText(m.flow_run_evidence_content_notice())).toBeTruthy();
  if (!disclosure) throw new Error("Missing content disclosure");
  disclosure.open = true;
  await fireEvent.click(
    screen.getByRole("button", { name: m.flow_run_download_evidence_export() })
  );
  expect(handlers.onDownloadCanonicalEvidence).toHaveBeenCalledOnce();
  expect(handlers.onCopyPayload).not.toHaveBeenCalled();
});

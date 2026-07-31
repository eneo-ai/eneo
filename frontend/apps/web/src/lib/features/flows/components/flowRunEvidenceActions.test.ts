import { expect, test, vi } from "vitest";
import { EneoError, type Eneo } from "@eneo/eneo-js";

import {
  classifyExportFailure,
  downloadEvidenceExport,
  downloadJsonArtifact,
  serializeEvidencePayload
} from "./flowRunEvidenceActions";

test("serializeEvidencePayload preserves plain strings", () => {
  expect(serializeEvidencePayload("already-serialized")).toBe("already-serialized");
});

test("serializeEvidencePayload pretty-prints JSON payloads", () => {
  expect(serializeEvidencePayload({ step: 1, ok: true })).toBe('{\n  "step": 1,\n  "ok": true\n}');
});

test("serializeEvidencePayload normalizes nullish payloads", () => {
  expect(serializeEvidencePayload(undefined)).toBe("null");
  expect(serializeEvidencePayload(null)).toBe("null");
});

test("downloadJsonArtifact triggers anchor download and deferred URL revocation", () => {
  const click = vi.fn();
  const anchor = {
    href: "",
    download: "",
    click
  } as unknown as HTMLAnchorElement;
  const createObjectURL = vi.fn(() => "blob:test");
  const revokeObjectURL = vi.fn();
  const appendAnchor = vi.fn();
  const removeAnchor = vi.fn();
  const scheduleRevoke = vi.fn((callback: () => void) => callback());

  downloadJsonArtifact(
    "flow-export.json",
    { id: "run-1" },
    {
      createObjectURL,
      revokeObjectURL,
      createAnchor: () => anchor,
      appendAnchor,
      removeAnchor,
      scheduleRevoke
    }
  );

  expect(createObjectURL).toHaveBeenCalledOnce();
  expect(anchor.download).toBe("flow-export.json");
  expect(anchor.href).toBe("blob:test");
  expect(appendAnchor).toHaveBeenCalledWith(anchor);
  expect(click).toHaveBeenCalledOnce();
  expect(removeAnchor).toHaveBeenCalledWith(anchor);
  expect(scheduleRevoke).toHaveBeenCalledOnce();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:test");
});

test("downloadEvidenceExport fetches canonical evidence export before download", async () => {
  const exportEvidence = vi.fn(async () => ({
    schema_version: "flow-evidence-export.v16",
    content_hash: "abc123"
  }));
  const triggerDownload = vi.fn();

  await downloadEvidenceExport(
    {
      eneo: {
        flows: {
          runs: {
            exportEvidence
          }
        }
      } as unknown as Eneo,
      flowId: "flow-1",
      runId: "run-1"
    },
    { triggerDownload }
  );

  expect(exportEvidence).toHaveBeenCalledWith({ id: "run-1", flowId: "flow-1", format: "json" });
  expect(triggerDownload).toHaveBeenCalledWith("flow-run-evidence-run-1.json", {
    schema_version: "flow-evidence-export.v16",
    content_hash: "abc123"
  });
});

function exportTooLargeError(limit: string | undefined): EneoError {
  // A real client error: the parsed body rides on EneoError.response, which
  // is where the canonical adapter reads the typed code and context.
  return new EneoError(
    "Request failed",
    "SERVER",
    413,
    0,
    {
      code: "flow_evidence_export_too_large",
      context: limit ? { limit } : {}
    },
    { endpoint: "/export" }
  );
}

test("classifyExportFailure routes passage and provenance limits to the evidence view", () => {
  expect(classifyExportFailure(exportTooLargeError("recorded_passage_bytes"))).toBe(
    "evidence_view"
  );
  expect(classifyExportFailure(exportTooLargeError("stored_provenance_bytes"))).toBe(
    "evidence_view"
  );
  expect(classifyExportFailure(exportTooLargeError("corrupt_passage_evidence"))).toBe(
    "evidence_view"
  );
});

test("classifyExportFailure routes provider-call overflow to the paginated list", () => {
  expect(classifyExportFailure(exportTooLargeError("provider_call_events"))).toBe("provider_calls");
});

test("classifyExportFailure falls back for unknown limits and foreign errors", () => {
  expect(classifyExportFailure(exportTooLargeError(undefined))).toBe("generic");
  expect(classifyExportFailure(new Error("network down"))).toBeNull();
});

import { expect, test, vi } from "vitest";
import type { Eneo } from "@eneo/eneo-js";

import {
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
    schema_version: "flow-evidence-export.v9",
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
    schema_version: "flow-evidence-export.v9",
    content_hash: "abc123"
  });
});

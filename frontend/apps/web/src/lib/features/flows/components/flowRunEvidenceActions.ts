import type { components, Eneo } from "@eneo/eneo-js";
import { describeFlowApiError } from "$lib/features/flows/flowRuntimeErrorMapping";

export function serializeEvidencePayload(payload: unknown): string {
  if (typeof payload === "string") {
    return payload;
  }
  return JSON.stringify(payload, null, 2) ?? "null";
}

type DownloadDeps = {
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  createAnchor: () => HTMLAnchorElement;
  appendAnchor: (anchor: HTMLAnchorElement) => void;
  removeAnchor: (anchor: HTMLAnchorElement) => void;
  scheduleRevoke: (callback: () => void) => void;
};

const defaultDownloadDeps: DownloadDeps = {
  createObjectURL: (blob) => URL.createObjectURL(blob),
  revokeObjectURL: (url) => URL.revokeObjectURL(url),
  createAnchor: () => document.createElement("a"),
  appendAnchor: (anchor) => document.body.appendChild(anchor),
  removeAnchor: (anchor) => anchor.remove(),
  scheduleRevoke: (callback) => setTimeout(callback, 0)
};

export function downloadJsonArtifact(
  fileName: string,
  payload: unknown,
  deps: Partial<DownloadDeps> = {}
): void {
  const resolved: DownloadDeps = { ...defaultDownloadDeps, ...deps };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = resolved.createObjectURL(blob);
  const anchor = resolved.createAnchor();
  anchor.href = url;
  anchor.download = fileName;
  resolved.appendAnchor(anchor);
  anchor.click();
  resolved.removeAnchor(anchor);
  resolved.scheduleRevoke(() => {
    resolved.revokeObjectURL(url);
  });
}

export async function downloadEvidenceExport(
  params: {
    eneo: Eneo;
    flowId: string;
    runId: string;
  },
  deps: {
    triggerDownload?: typeof downloadJsonArtifact;
  } = {}
): Promise<void> {
  const exportPayload = await params.eneo.flows.runs.exportEvidence({
    id: params.runId,
    flowId: params.flowId,
    format: "json"
  });
  const triggerDownload = deps.triggerDownload ?? downloadJsonArtifact;
  triggerDownload(`flow-run-evidence-${params.runId}.json`, exportPayload);
}

export type ExportRecoveryKind = "evidence_view" | "provider_calls" | "generic" | null;

type EvidenceExportLimit = components["schemas"]["FlowEvidenceExportTooLargeContext"]["limit"];

const evidenceExportLimits = [
  "corrupt_passage_evidence",
  "recorded_passage_bytes",
  "stored_provenance_bytes",
  "section_rows",
  "aggregate_stored_json_bytes",
  "aggregate_logical_json_bytes",
  "provider_call_events"
] as const satisfies readonly EvidenceExportLimit[];

function evidenceExportLimit(value: unknown): EvidenceExportLimit | null {
  if (typeof value !== "string") return null;
  return evidenceExportLimits.includes(value as EvidenceExportLimit)
    ? (value as EvidenceExportLimit)
    : null;
}

export function classifyExportFailure(error: unknown): ExportRecoveryKind {
  // An oversized-export refusal names the exceeded limit in its typed
  // context; real client errors carry that context on the parsed response,
  // which the canonical adapter reads. The kind maps to localized recovery
  // copy at the call site — server-authored text is never echoed.
  const descriptor = describeFlowApiError(error);
  if (descriptor?.code !== "flow_evidence_export_too_large") return null;
  switch (evidenceExportLimit(descriptor.context.limit)) {
    case "recorded_passage_bytes":
    case "stored_provenance_bytes":
    case "corrupt_passage_evidence":
      return "evidence_view";
    case "provider_call_events":
      return "provider_calls";
    default:
      return "generic";
  }
}

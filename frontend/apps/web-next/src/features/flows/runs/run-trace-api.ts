import { browserApi } from "@/lib/api/browser";
import { apiErrorFromResponse, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { DEFAULT_EXPORT_REASON } from "./run-trace-rules";

/**
 * The run's trace beyond the evidence read the page already makes: its
 * provider calls page by page, and its evidence exported as a file. Every
 * one of these is an audited read, so each is made when the person asks.
 */

export type ProviderCallPage = Schema<"ProviderCallEvidencePage">;
export type ProviderCall = Schema<"ProviderCallEvidence">;

/** The run's provider calls after `afterEventId`, in the core's stable order. */
export function getProviderCalls(
  flowId: string,
  runId: string,
  afterEventId: string,
  signal?: AbortSignal
): Promise<ProviderCallPage> {
  return unwrap(
    browserApi.GET("/api/v1/flows/{id}/runs/{run_id}/provider-calls/", {
      params: {
        path: { id: flowId, run_id: runId },
        query: { after_event_id: afterEventId, limit: 100 }
      },
      signal
    })
  );
}

function filenameOf(contentDisposition: string | null): string | null {
  return contentDisposition
    ? (/filename="?([^";]+)"?/i.exec(contentDisposition)?.[1] ?? null)
    : null;
}

/**
 * The run's evidence as the JSON file the core exports: `redacted` is the
 * support export, `raw` the full one, which needs the person's own reason.
 */
export async function exportRunEvidence(
  flowId: string,
  runId: string,
  request: { detail: "redacted" } | { detail: "raw"; reason: string }
): Promise<{ blob: Blob; filename: string }> {
  const { data, error, response } = await browserApi.GET(
    "/api/v1/flows/{id}/runs/{run_id}/evidence/export",
    {
      params: {
        path: { id: flowId, run_id: runId },
        query: {
          format: "json",
          detail: request.detail,
          reason: request.detail === "raw" ? request.reason.trim() : DEFAULT_EXPORT_REASON
        }
      },
      parseAs: "blob"
    }
  );
  // A refusal comes back as JSON even though a success is a file.
  if (!response.ok || !data) throw apiErrorFromResponse(response, error);
  return {
    blob: data as Blob,
    filename:
      filenameOf(response.headers.get("content-disposition")) ?? `flow-run-evidence-${runId}.json`
  };
}

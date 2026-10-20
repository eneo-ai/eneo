import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { FlowRunFilePublic } from "./types";

/**
 * A short-lived URL for a run's file (an input it was given or a document it
 * produced), minted through the run so every reader of the flow can open
 * it, not only the person who uploaded or ran it. Consumed through the
 * same-origin proxy like `signedOriginalUrl`.
 */
export async function signedRunFileUrl(
  api: EneoClient,
  flowId: string,
  runId: string,
  file: Pick<FlowRunFilePublic, "id" | "role">
): Promise<string> {
  const path =
    file.role === "output"
      ? "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/"
      : "/api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/";
  const signed = await unwrap(
    api.POST(path, {
      params: { path: { id: flowId, run_id: runId, file_id: file.id } },
      body: { expires_in: 3600, content_disposition: "attachment" }
    })
  );
  const parsed = new URL(signed.url);
  if (
    parsed.pathname !== `/api/v1/files/${encodeURIComponent(file.id)}/original/download/` ||
    !parsed.searchParams.get("token")
  ) {
    throw new Error("Unexpected signed file URL");
  }
  return `/api/eneo${parsed.pathname}${parsed.search}`;
}

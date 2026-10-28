import { browserApi } from "@/lib/api/browser";
import { apiErrorFromResponse, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type DocumentExportAvailability = Schema<"DocumentExportAvailability">;
export type DocumentExportFormat = "docx" | "pdf";

/** The other formats a document can be handed over in. */
export type DocumentExport = {
  availability: () => Promise<DocumentExportAvailability>;
  exportAs: (format: DocumentExportFormat) => Promise<Blob>;
};

/**
 * How a Markdown document the assistant made in `sessionId` is exported: the
 * assistant's own document tool renders it, when it has one.
 */
export function documentExport(sessionId: string, fileId: string): DocumentExport {
  const params = { path: { session_id: sessionId, file_id: fileId } };
  return {
    availability: () =>
      unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/documents/{file_id}/export/", {
          params
        })
      ),
    async exportAs(format) {
      const { data, response } = await browserApi.POST(
        "/api/v1/conversations/{session_id}/documents/{file_id}/export/",
        { params, body: { format }, parseAs: "blob" }
      );
      if (!response.ok || !data) throw apiErrorFromResponse(response, undefined);
      return data;
    }
  };
}

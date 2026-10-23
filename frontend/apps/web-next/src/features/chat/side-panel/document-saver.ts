import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type SavedDocumentVersion = Schema<"FilePublic">;

/** How a reader's edit of a document is kept: as the document's next version. */
export type DocumentSaver = {
  save: (markdown: string) => Promise<SavedDocumentVersion>;
};

/**
 * Saves the reader's edited Markdown of a document in `sessionId` as the
 * next version of `fileId`. The version joins the turn that made the document;
 * the backend hands back the version edited from when nothing changed.
 */
export function saveDocumentVersion(
  sessionId: string,
  fileId: string,
  content: string
): Promise<SavedDocumentVersion> {
  return unwrap(
    browserApi.POST("/api/v1/conversations/{session_id}/documents/{file_id}/versions/", {
      params: { path: { session_id: sessionId, file_id: fileId } },
      body: { content }
    })
  );
}

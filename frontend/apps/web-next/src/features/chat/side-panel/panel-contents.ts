import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import type { EneoUIMessage } from "@/lib/chat/types";
import type { ConversationDocument } from "./document-versions";
import { messageGeneratedFiles } from "./message-tool-calls";

/** Something other than a file that the panel can show: an interactive tool view. */
export type PanelView = {
  id: string;
  title: string;
  /** What this view is about, when its call says; tells two views of one tool apart. */
  subject: string | null;
  /** Whether the panel shows this view now. */
  shown: boolean;
  open: () => void;
};

/** Everything of a conversation that the panel can show. */
export type PanelContents = {
  views: PanelView[];
  documents: ConversationDocument[];
  uploads: PreviewFile[];
};

export function panelContentsCount(contents: PanelContents | null | undefined): number {
  if (!contents) return 0;
  return contents.views.length + contents.documents.length + contents.uploads.length;
}

/**
 * Uploaded files in this conversation, once per id, separate from generated
 * outputs. History keeps a question's files on the user message; a live turn
 * lists them in the answer's session data.
 */
export function conversationUploads(messages: readonly EneoUIMessage[]): PreviewFile[] {
  const generated = new Set(
    messages.flatMap((message) => messageGeneratedFiles(message).map((file) => file.id))
  );
  const uploads = new Map<string, PreviewFile>();
  const add = (file: PreviewFile) => {
    if (file.id && !generated.has(file.id)) uploads.set(file.id, file);
  };
  for (const message of messages) {
    for (const file of message.metadata?.files ?? []) add(file);
    for (const part of message.parts) {
      if (part.type === "data-session") part.data.files.forEach(add);
    }
  }
  return [...uploads.values()];
}

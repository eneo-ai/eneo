import type { UploadGroup } from "$lib/features/chat/conversationUploads";
import type { ConversationDocument } from "$lib/features/chat/documentVersions";

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
  /** The uploads, by the question they were sent with. */
  uploads: UploadGroup[];
};

/** How many things the panel has to show. */
export function panelContentsCount(contents: PanelContents | null | undefined): number {
  if (!contents) return 0;
  return (
    contents.views.length +
    contents.documents.length +
    contents.uploads.reduce((sum, group) => sum + group.files.length, 0)
  );
}

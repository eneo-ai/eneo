import type { ConversationDocument } from "$lib/features/chat/documentVersions";
import type { PreviewFile } from "./previewKind";

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

import { File as FileIcon, FileHeadphone, FileImage, FileText } from "@lucide/svelte";

/**
 * Maps a MIME type to a representative Lucide file icon.
 *
 * Shared between {@link ConversationAttachments} (upload chips) and
 * {@link MessageFiles} (message-bubble chips) so the icon library stays in
 * lock-step across both surfaces — adding a new file family is a single edit.
 */
export function pickFileIcon(mimetype: string) {
  const general = mimetype.split("/")[0];
  if (general === "image") return FileImage;
  if (general === "audio" || general === "video") return FileHeadphone;
  if (
    general === "text" ||
    mimetype.includes("pdf") ||
    mimetype.includes("word") ||
    mimetype.includes("document") ||
    mimetype.includes("sheet") ||
    mimetype.includes("excel")
  ) {
    return FileText;
  }
  return FileIcon;
}

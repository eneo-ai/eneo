import FileIcon from "@lucide/svelte/icons/file";
import FileHeadphone from "@lucide/svelte/icons/file-headphone";
import FileImage from "@lucide/svelte/icons/file-image";
import FileText from "@lucide/svelte/icons/file-text";

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

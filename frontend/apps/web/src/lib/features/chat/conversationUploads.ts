import type { PreviewFile } from "$lib/features/file-preview/previewKind";

/** Uploaded files in this conversation, once per ID, separate from generated outputs. */
export function conversationUploads(
  messages: { files?: PreviewFile[] | null; generated_files?: PreviewFile[] | null }[]
): PreviewFile[] {
  const generated = new Set(
    messages.flatMap((message) => (message.generated_files ?? []).map((file) => file.id))
  );
  const uploads = new Map<string, PreviewFile>();
  for (const message of messages) {
    for (const file of message.files ?? []) {
      if (file.id && !generated.has(file.id)) uploads.set(file.id, file);
    }
  }
  return [...uploads.values()];
}

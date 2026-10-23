import type { PreviewFile } from "$lib/features/file-preview/previewKind";

type UploadMessage = {
  id?: string | null;
  files?: PreviewFile[] | null;
  generated_files?: PreviewFile[] | null;
};

/** The files a question was sent with, as one group of the conversation's uploads. */
export type UploadGroup = {
  /** Identifies the question; a message's bundle names its group by this. */
  key: string;
  /** The question's place in the conversation, from 1. */
  ordinal: number;
  files: PreviewFile[];
};

/**
 * What identifies a question's upload group: the message's id, or its first
 * file while the message has no id yet (a question still being answered).
 */
export function uploadGroupKey(message: { id?: string | null; files?: PreviewFile[] | null }) {
  if (message.id) return message.id;
  const first = message.files?.find((file) => file.id);
  return first ? `file:${first.id}` : null;
}

/**
 * Uploaded files in this conversation, grouped by the question they were
 * sent with, once per ID and separate from generated outputs. A file sent
 * again later stays with the question that brought it.
 */
export function conversationUploadGroups(messages: UploadMessage[]): UploadGroup[] {
  const generated = new Set(
    messages.flatMap((message) => (message.generated_files ?? []).map((file) => file.id))
  );
  const seen = new Set<string>();
  const groups: UploadGroup[] = [];
  messages.forEach((message, index) => {
    const files: PreviewFile[] = [];
    for (const file of message.files ?? []) {
      if (!file.id || generated.has(file.id) || seen.has(file.id)) continue;
      seen.add(file.id);
      files.push(file);
    }
    const key = uploadGroupKey(message);
    if (files.length > 0 && key) groups.push({ key, ordinal: index + 1, files });
  });
  return groups;
}

/** Uploaded files in this conversation, once per ID, separate from generated outputs. */
export function conversationUploads(messages: UploadMessage[]): PreviewFile[] {
  return conversationUploadGroups(messages).flatMap((group) => group.files);
}

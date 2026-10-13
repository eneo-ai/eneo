import { referencedFileId } from "./fileReference";

/** A file the assistant created; satisfied by `FilePublic`. */
export type GeneratedDocument = {
  id: string;
  name: string;
  mimetype: string;
  size: number;
  original_size?: number | null;
};

type ToolCall = {
  tool_call_id?: string | null;
  arguments?: Record<string, unknown> | null;
  generated_file_ids?: string[] | null;
};

type Message = {
  generated_files?: GeneratedDocument[] | null;
  /** Tool calls of an answer loaded from history. */
  tool_calls?: ToolCall[] | null;
  /** Tool calls of the answer being streamed. */
  mcp_tool_calls?: ToolCall[] | null;
};

/** One document of a conversation: every version the assistant made of it. */
export type ConversationDocument = {
  latest: GeneratedDocument;
  /** Oldest first; the last one is `latest`. */
  versions: GeneratedDocument[];
};

/** Whether a generated file is a document rather than an image (or one still being made). */
export function isDocument(file: { id: string; mimetype: string }): boolean {
  return file.id !== "" && file.mimetype !== "" && !file.mimetype.startsWith("image/");
}

/** The earlier file a tool call replaces: the one its `revises` argument links to. */
export function revisedFileId(args: Record<string, unknown> | null | undefined): string | null {
  const revises = args?.revises;
  if (typeof revises !== "object" || revises === null) return null;
  return referencedFileId((revises as { url?: unknown }).url);
}

/** The name of the earlier document a tool call changes, without its extension. */
export function revisedDocumentName(
  args: Record<string, unknown> | null | undefined
): string | null {
  const revises = args?.revises;
  if (typeof revises !== "object" || revises === null) return null;
  const filename = (revises as { filename?: unknown }).filename;
  if (typeof filename !== "string" || !filename) return null;
  return filename.replace(/\.[^.]+$/, "");
}

/**
 * A passage to point out in the new version of an edited document: the first
 * line of the first replacement, as it reads once rendered. Null when the
 * call replaced nothing with text worth pointing at.
 */
export function editedPassage(args: Record<string, unknown> | null | undefined): string | null {
  const edits = args?.edits;
  if (!Array.isArray(edits)) return null;
  for (const edit of edits) {
    const replace = (edit as { replace?: unknown } | null)?.replace;
    if (typeof replace !== "string") continue;
    for (const line of replace.split("\n")) {
      const text = line
        // Block marks at the start of a line: headings, quotes, list items, task boxes.
        .replace(/^\s*(#{1,6}\s+|>\s?|[-*+]\s+(\[[ xX]\]\s+)?|\d+[.)]\s+)*/, "")
        // Links keep their text; emphasis and code marks are dropped.
        .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/[*_`~]+/g, "")
        .trim();
      // A table row or a line that is only marks has no single run of text.
      if (text.length >= 4 && !text.includes("|")) return text;
    }
  }
  return null;
}

const extension = (name: string) => name.slice(name.lastIndexOf(".") + 1).toLowerCase();

/**
 * The documents of a conversation, each with its versions in order.
 *
 * A call that revises an earlier file continues that file's document. The same
 * content in another format (a plan handed over as Word) is a document of its
 * own, since both are kept and used.
 */
export function conversationDocuments(
  messages: Message[],
  /** The files a call produced: recorded on the call in history, tracked live otherwise. */
  fileIdsOf: (call: ToolCall) => string[]
): {
  documents: ConversationDocument[];
  /** The newest version of the document `fileId` belongs to. */
  latestOf: (fileId: string) => GeneratedDocument | undefined;
  /** Every version of the document `fileId` belongs to, oldest first. */
  versionsOf: (fileId: string) => GeneratedDocument[];
} {
  const files = new Map<string, GeneratedDocument>();
  for (const message of messages) {
    for (const file of message.generated_files ?? []) {
      if (isDocument(file)) files.set(file.id, file);
    }
  }

  const earlierOf = new Map<string, string>();
  const laterOf = new Map<string, string>();
  for (const message of messages) {
    for (const call of message.mcp_tool_calls ?? message.tool_calls ?? []) {
      const earlier = files.get(revisedFileId(call.arguments) ?? "");
      if (!earlier) continue;
      for (const id of fileIdsOf(call)) {
        const file = files.get(id);
        if (!file || id === earlier.id || extension(file.name) !== extension(earlier.name)) {
          continue;
        }
        earlierOf.set(id, earlier.id);
        laterOf.set(earlier.id, id);
      }
    }
  }

  const documents: ConversationDocument[] = [];
  for (const file of files.values()) {
    if (laterOf.has(file.id)) continue;
    const versions = [file];
    for (let id = earlierOf.get(file.id); id; id = earlierOf.get(id)) {
      const earlier = files.get(id);
      if (!earlier || versions.includes(earlier)) break;
      versions.unshift(earlier);
    }
    documents.push({ latest: file, versions });
  }

  return {
    documents,
    latestOf(fileId) {
      let id = fileId;
      for (let steps = 0; laterOf.has(id) && steps < files.size; steps++) id = laterOf.get(id)!;
      return files.get(id);
    },
    versionsOf(fileId) {
      return (
        documents.find((document) => document.versions.some((file) => file.id === fileId))
          ?.versions ?? []
      );
    }
  };
}

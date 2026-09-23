import type { ConversationMessage } from "@eneo/eneo-js";
import { createContext } from "$lib/core/context";
import {
  canonicalDocKey,
  citedTextDocumentReferences,
  mergeAdjacentCitations,
  textDocumentReferences
} from "$lib/features/chat/mcpReferenceDocs";

export type WidgetMessageContext = {
  /** 0-based position of a cited id in the message's de-duplicated source list, or null. */
  referenceIndex: (citedId: string) => number | null;
  referenceAnchor: (index: number) => string;
  /** Expand the source list (if collapsed) and move focus to the given entry. */
  revealSource: (index: number) => void;
};

export const [getWidgetMessageContext, setWidgetMessageContext] =
  createContext<WidgetMessageContext>("Widget message");

export type WidgetSource = {
  id: string;
  title: string;
  url: string | null;
  /**
   * A document in the assistant's knowledge, which Eneo can look up by id; a
   * source from a tool (an MCP server or capability) has no such reference.
   */
  document: boolean;
};

type SourceMessage = Pick<ConversationMessage, "references" | "answer" | "mcp_tool_references">;
type KnowledgeReference = NonNullable<ConversationMessage["references"]>[number];
type ToolReference = NonNullable<ConversationMessage["mcp_tool_references"]>[number];

const HTTP_URL = /^https?:\/\//i;

function knowledgeKey(reference: KnowledgeReference): string {
  return reference.metadata.url ?? reference.metadata.title ?? reference.id;
}

// A tool result from a web page folds into a knowledge source with the same
// address; passages of one document (`#chunk-N`) fold into one entry.
function toolKey(reference: ToolReference): string {
  const meta = (reference.meta ?? {}) as { section?: unknown; pageRange?: unknown };
  if (meta.section || meta.pageRange) return canonicalDocKey(reference);
  return (reference.uri ?? "").split("#")[0] || reference.id;
}

function hostOf(uri: string): string {
  try {
    return new URL(uri).hostname || uri;
  } catch {
    return uri;
  }
}

function toolSource(reference: ToolReference): WidgetSource {
  const uri = reference.uri ?? "";
  const title = (reference.meta as { title?: unknown } | null | undefined)?.title;
  return {
    id: reference.id,
    title: typeof title === "string" && title ? title : hostOf(uri),
    url: HTTP_URL.test(uri) ? uri : null,
    document: false
  };
}

/**
 * Every source the answer can point to, one entry per document: the
 * assistant's knowledge first, then the tool results the answer cites.
 * Numbering matches the inline citations.
 */
function collect(message: SourceMessage) {
  const indexByKey = new Map<string, number>();
  const sources: WidgetSource[] = [];
  const add = (key: string, source: WidgetSource) => {
    if (indexByKey.has(key)) return;
    indexByKey.set(key, sources.length);
    sources.push(source);
  };
  for (const reference of message.references ?? []) {
    add(knowledgeKey(reference), {
      id: reference.id,
      title: reference.metadata.title ?? reference.metadata.url ?? "",
      url: reference.metadata.url ?? null,
      document: true
    });
  }
  const answer = message.answer ?? "";
  for (const reference of citedTextDocumentReferences(message.mcp_tool_references ?? [], answer)) {
    add(toolKey(reference), toolSource(reference));
  }
  return { sources, indexByKey };
}

/** Sources cited by a message, one entry per document, in citation order. */
export function messageSources(message: SourceMessage): WidgetSource[] {
  return collect(message).sources;
}

/** Map every cited id (incl. duplicates of the same document) to its source index. */
export function referenceIndexer(message: SourceMessage) {
  const { indexByKey } = collect(message);
  const tools = textDocumentReferences(message.mcp_tool_references ?? []);
  // A tool citation right beside another one to the same document would
  // repeat its number; the signed-in chat folds it away the same way.
  const { suppressed } = mergeAdjacentCitations(tools, message.answer ?? "");
  return (citedId: string): number | null => {
    const knowledge = (message.references ?? []).find((ref) => ref.id.startsWith(citedId));
    if (knowledge) return indexByKey.get(knowledgeKey(knowledge)) ?? null;
    if (suppressed.has(citedId)) return null;
    const tool = tools.find((ref) => ref.id.startsWith(citedId));
    return tool ? (indexByKey.get(toolKey(tool)) ?? null) : null;
  };
}

/**
 * What a visitor copies for a source without a link: the title plus a link
 * into Eneo that resolves the document for anyone with access to it, so the
 * reference can be forwarded to an administrator as is.
 */
export function sourceReferenceText(
  source: Pick<WidgetSource, "id" | "title">,
  appOrigin: string
): string {
  return `${source.title} – ${appOrigin}/documents/${source.id}`;
}

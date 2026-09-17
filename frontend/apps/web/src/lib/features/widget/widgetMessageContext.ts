import type { ConversationMessage } from "@eneo/eneo-js";
import { createContext } from "$lib/core/context";

export type WidgetMessageContext = {
  /** 0-based position of a reference in the message's de-duplicated source list, or null. */
  referenceIndex: (infoBlobId: string) => number | null;
  referenceAnchor: (index: number) => string;
};

export const [getWidgetMessageContext, setWidgetMessageContext] =
  createContext<WidgetMessageContext>("Widget message");

export type WidgetSource = {
  id: string;
  title: string;
  url: string | null;
};

/** Sources cited by a message, one entry per document, in citation order. */
export function messageSources(message: Pick<ConversationMessage, "references">): WidgetSource[] {
  const seen = new Set<string>();
  const sources: WidgetSource[] = [];
  for (const reference of message.references ?? []) {
    const key = reference.metadata.url ?? reference.metadata.title ?? reference.id;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push({
      id: reference.id,
      title: reference.metadata.title ?? reference.metadata.url ?? "",
      url: reference.metadata.url ?? null
    });
  }
  return sources;
}

/** Map every reference id (incl. duplicates of the same document) to its source index. */
export function referenceIndexer(message: Pick<ConversationMessage, "references">) {
  const sources = messageSources(message);
  const byKey = new Map(sources.map((source, index) => [source.url ?? source.title, index]));
  return (infoBlobId: string): number | null => {
    const reference = (message.references ?? []).find((ref) => ref.id.startsWith(infoBlobId));
    if (!reference) return null;
    const key = reference.metadata.url ?? reference.metadata.title ?? reference.id;
    return byKey.get(key) ?? null;
  };
}

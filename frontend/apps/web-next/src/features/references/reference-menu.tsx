import type { ChatComposerToken, ChatComposerTrigger } from "@astryxdesign/core/Chat";
import { IconButton } from "@astryxdesign/core/IconButton";
import { createStaticSource, type SearchableItem } from "@astryxdesign/core/Typeahead";
import { AtSign } from "lucide-react";
import type { ReactNode } from "react";
import type { ComposerInsert } from "@/features/chat/chat-references";

/**
 * The reference menu a chat's composer opens on "@": what it lists, how a
 * row looks and what a pick puts in the field. The menu itself (a combobox
 * on the text field: arrow keys, Enter, Escape, the groups' names, the
 * result count read out) is Astryx's.
 */

/** One row of the menu. */
export type ReferenceMenuItem<T> = {
  /** Unique in the menu: the reference as written. */
  id: string;
  /** What the row is called; typing after "@" finds it by this and by `keywords`. */
  label: string;
  /** The heading the row is listed under. */
  group: string;
  keywords: readonly string[];
  value: T;
};

type Item<T> = SearchableItem<{ value: T; group: string; keywords: readonly string[] }>;

export function referenceMenuTrigger<T>({
  items,
  menuLabel,
  emptyText,
  loadingText,
  renderItem,
  toToken
}: {
  items: readonly ReferenceMenuItem<T>[];
  /** The menu's name. */
  menuLabel: string;
  /** Said in the menu when nothing matches what was typed. */
  emptyText: string;
  loadingText: string;
  renderItem: (value: T) => ReactNode;
  /** The pill a pick puts in the field. */
  toToken: (value: T) => ChatComposerToken;
}): ChatComposerTrigger {
  const searchable: Item<T>[] = items.map((item) => ({
    id: item.id,
    label: item.label,
    // Astryx lists the rows under their `group`.
    auxiliaryData: { value: item.value, group: item.group, keywords: item.keywords }
  }));
  return {
    character: "@",
    searchSource: createStaticSource(searchable, {
      keywords: (item) => [...item.auxiliaryData!.keywords]
    }),
    hasMultiWordQuery: true,
    menuLabel,
    emptySearchText: emptyText,
    loadingText,
    renderItem: (item) => renderItem((item as Item<T>).auxiliaryData!.value),
    onSelect: (item) => toToken((item as Item<T>).auxiliaryData!.value)
  };
}

/** The button beside the text field that opens the reference menu, as typing "@" does. */
export function ReferenceMenuButton({ label, input }: { label: string; input: ComposerInsert }) {
  return (
    <IconButton
      label={label}
      icon={<AtSign aria-hidden="true" />}
      variant="ghost"
      size="sm"
      onClick={() => input.insertText("@")}
    />
  );
}

/** A part of a prepared message: text as typed, or a reference as its pill. */
export type InsertPart =
  { kind: "text"; text: string } | { kind: "token"; token: ChatComposerToken };

/**
 * Puts a prepared message into the composer at the caret, as if the person
 * had written it: its text as typed, each reference as the pill a pick from
 * the menu makes. Nothing is sent.
 */
export function insertParts(composer: ComposerInsert, parts: readonly InsertPart[]) {
  let afterPill = false;
  for (const part of parts) {
    if (part.kind === "text") {
      // A pill brings the space after it, as a pick from the menu does.
      const typed = afterPill && part.text.startsWith(" ") ? part.text.slice(1) : part.text;
      if (typed) composer.insertText(typed);
      afterPill = false;
    } else {
      composer.insertToken(part.token);
      afterPill = true;
    }
  }
}

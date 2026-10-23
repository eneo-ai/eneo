import type { ChatComposerToken, ChatComposerTrigger } from "@astryxdesign/core/Chat";
import type { ReactNode } from "react";
import type { MessageResponseProps } from "@/components/ai-elements/message";

/** A way to put text or a token (a pill) into the composer's field, at the caret. */
export type ComposerInsert = {
  insertText: (text: string) => void;
  insertToken: (token: ChatComposerToken) => void;
};

/**
 * What a page lets a conversation refer to (the flow chat's steps and
 * values): a menu the composer opens on a character, pills for the
 * references a question holds, and how an answer's references are drawn.
 */
export type ChatReferences = {
  /** Menus the text field opens as their character is typed. */
  triggers: ChatComposerTrigger[];
  /** The references a sent text holds, as tokens drawn in its place. */
  tokens: (text: string) => ChatComposerToken[];
  /** Turns an answer's references into links the components draw as pills. */
  remarkPlugins: NonNullable<MessageResponseProps["remarkPlugins"]>;
  components: NonNullable<MessageResponseProps["components"]>;
  /** A control above the text field that puts text in it (a "Referera" button). */
  headerActions?: (input: ComposerInsert) => ReactNode;
  /** The composer on screen, as something to insert into; null while there is none. */
  onComposer?: (input: ComposerInsert | null) => void;
};

import type { QueryKey } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ToolCards } from "@/features/chat/chat-message";
import type { ChatReferences } from "@/features/chat/chat-references";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";

/**
 * A person's helper chat about one target, as every target's endpoints
 * return it: the assistant that answers, the conversation on screen, the
 * mode (on a target with modes) and the person's model choice for this chat.
 */
export type HelperChat = {
  /** The chat's own assistant, hidden from lists, which answers its questions. */
  assistant_id: string;
  /**
   * The current conversation. Starting a new one (explicitly, Redigera after
   * a pause, or an opening with a fresh start) replaces it; earlier ones are
   * listed and read but never answered again.
   */
  session_id: string;
  /**
   * Redigera (the chat's tools may change the target) rather than Fråga.
   * A target without modes returns none: its chat is never in Redigera.
   */
  editing?: boolean;
  /** The person's model for this chat; null follows the default. */
  completion_model_id?: string | null;
  /** The person's reasoning effort; null uses the model's own default. */
  reasoning_effort?: string | null;
  /** The model the chat answers with while the person has chosen none. */
  default_completion_model_id?: string | null;
};

/** A change to the chat; a null model or effort returns to the default. */
export type HelperChatUpdate = {
  /** The mode, for a target with modes only. */
  editing?: boolean;
  completion_model_id?: string | null;
  reasoning_effort?: string | null;
  /** The target revision a mode change is fenced on, for a target that has one. */
  expected_revision?: number;
};

/**
 * One of the person's conversations in the chat that holds a question, as
 * every target's list returns it.
 */
export type HelperConversation = {
  session_id: string;
  /** The first question, cut to a length; its mentions as they were written. */
  title: string;
  started_at: string;
  last_asked_at: string;
  /** The conversation questions go to; every other one is read only. */
  current: boolean;
};

/** The chat's endpoints for one target. */
export type HelperChatApi = {
  /** Where the chat is cached; every change of it is written there. */
  key: QueryKey;
  /**
   * The person's chat for the target, created on first use. With `fresh`
   * it opens on a new, empty conversation; a current one that holds no
   * question yet is kept as it is, so asking twice starts one at most.
   */
  open: (options?: { fresh?: boolean }) => Promise<HelperChat>;
  /**
   * Each visit opens on a new, empty conversation: the panel's first read of
   * the chat asks for a fresh start, a later read (on the window's focus,
   * after an answer) never does, and what the panel read is forgotten when
   * it goes, so the next visit never shows it first.
   */
  freshPerVisit?: boolean;
  /** Changes the chat's mode, model or reasoning effort. */
  update: (sessionId: string, body: HelperChatUpdate) => Promise<HelperChat>;
  /** Leaves the conversation for a new, empty one with the same assistant. */
  startConversation: (sessionId: string) => Promise<HelperChat>;
  /**
   * The person's conversations in the chat that hold a question, the latest
   * question first. Without it the panel offers no earlier conversations.
   */
  listConversations?: () => Promise<HelperConversation[]>;
};

/**
 * The panel's words that name its target. The rest (the settings, "Ny
 * konversation", the mode's name, loading and failures) are the same for
 * every target and belong to the panel.
 */
export type HelperTexts = {
  /** The panel's heading. */
  heading: string;
  /** What the conversation calls its partner. */
  partnerName: string;
  /** The partner's welcome; in Fråga, for a target with modes. */
  partnerDescription: string;
  /** The composer's placeholder; in Fråga, for a target with modes. */
  placeholder: string;
  /** Why the server refused the chat for want of access (403), should the page's own reading be out of date. */
  noAccess: string;
  /** What starting a new conversation keeps and drops, in its confirmation. */
  newConversationDescription: string;
};

/**
 * A target's two modes, picked beside the send button: Fråga (the chat
 * reads the target and changes nothing) and Redigera (its tools may change
 * it). Fråga takes the panel's own texts; these are the picker's and
 * Redigera's words.
 */
export type HelperModes = {
  /** What each mode does, under its name in the picker. */
  description: { ask: string; edit: string };
  /** Redigera's welcome, placeholder and composer name (in Fråga the composer is named by its partner). */
  edit: { partnerDescription: string; placeholder: string; composerLabel: string };
  /** Said when the person turns Redigera on or off. */
  editingOn: string;
  editingOff: string;
  /** Said when a read of the chat finds the server left Redigera after a pause. */
  askAfterPause: string;
};

/**
 * The target cannot be changed now (a published flow): Redigera cannot be
 * picked, a mode saved before does not apply, and these say why.
 */
export type HelperLock = {
  /** Under Redigera in the picker. */
  reason: string;
  /** Under the panel's heading. */
  intro: string;
  /** The partner's welcome, in place of the mode's. */
  partnerDescription: string;
};

/**
 * What a page hands the helper panel about its target. Everything else (the
 * chat's loading, its conversation, the mode picker, the settings, a new
 * conversation, the announcements) is the panel's and the same for every
 * target.
 */
export type HelperAdapter = {
  api: HelperChatApi;
  /**
   * Why the person cannot use the chat on this target, in the target's words
   * (no edit access, no model for the chat); null when they can. While it is
   * set the chat is not asked for, and the panel says this instead.
   */
  unavailable: string | null;
  texts: HelperTexts;
  /**
   * The target's modes; null for a target with one, whose chat proposes
   * each change for the person to apply and never changes the target
   * itself: the panel shows no picker and announces no mode.
   */
  modes: HelperModes | null;
  /** Set while the target cannot be changed. */
  lock?: HelperLock | null;
  /**
   * The target revision on screen, for a target whose changes are fenced on
   * one: a mode change sends it, so one made against a changed target is
   * refused. Read when the change is saved.
   */
  revision?: () => number;
  /** The target's own words for a refusal to open the chat (the 400's `reason`), or null. */
  refusalText?: (reason: string | undefined) => string | null;
  /** Shows a refused change of the chat (mode, model, new conversation) with the page's other refusals. */
  onRefused: (error: unknown, title: string) => void;
  /** What the conversation can refer to. */
  references?: ChatReferences;
  /** Cards the page draws for the target's tool calls in answers. */
  toolCards?: ToolCards;
  /** The target's own actions in the panel's title row, before the chat's. */
  headerActions?: ReactNode;
  /** The target's own controls in the composer's footer, before any mode picker (an "@" button). */
  footerActions?: ReactNode;
  /** A tool call of this visit finished; the page knows whether it can have changed the target. */
  onToolCallFinished?: (call: ToolCallRecord) => void;
  /** An answer ended: the target may have changed. */
  onAnswerFinished?: () => void;
  /**
   * Why a message cannot go right now, in the target's words (edits on
   * screen that are not saved, which the chat cannot read); null when it
   * can. Read when a message goes, once its files are uploaded and before
   * `beforeSend`: while it is set the message is held, back in the
   * composer, and the panel shows the sentence for as long as it stands.
   */
  sendHold?: string | null;
  /**
   * Where the person can settle the standing reason when it is not on screen
   * beside the chat (a narrow window shows one side at a time); null when it
   * is in view. Shown as a button with the notice while the reason stands,
   * never with a sentence from `beforeSend`. Pressing it sends, saves and
   * clears nothing: the held message stays in the composer.
   */
  sendHoldAction?: { label: string; onAction: () => void } | null;
  /**
   * Runs before each message goes, once its files are uploaded: null lets it
   * go; a sentence holds it, back in the composer, and the panel shows the
   * sentence. A page that saves as the person types saves what is pending
   * here, so the chat reads what is on screen.
   */
  beforeSend?: () => Promise<string | null>;
};

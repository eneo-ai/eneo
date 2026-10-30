"use client";

import { useChat } from "@ai-sdk/react";
import { Button } from "@astryxdesign/core/Button";
import { ChatLayout, ChatMessageList, ChatSystemMessage } from "@astryxdesign/core/Chat";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Selector } from "@astryxdesign/core/Selector";
import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  memo,
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ComponentProps,
  type ReactNode
} from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { invalidateConversationLists } from "@/lib/api/conversations";
import { describeChatFailure } from "@/lib/chat/chat-error";
import { displayPartnerName } from "@/lib/chat/partner-name";
import { createChatTransport, type ChatSendOptions } from "@/lib/chat/transport";
import type { AnswerRating, ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { deriveContextUsage, usePreflight } from "@/lib/chat/use-preflight";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import { conversationFiles, deriveActivity } from "./activity";
import { ActivityPanelBody, type ActivityTab } from "./activity-panel";
import { ActivityTimings } from "./activity-timings";
import { documentDraft } from "./side-panel/document-draft";
import { documentExport, isExportableDocument } from "./side-panel/document-export";
import { saveDocumentVersion, type DocumentSaver } from "./side-panel/document-saver";
import { conversationDocuments, editedPassage } from "./side-panel/document-versions";
import {
  addGeneratedFile,
  messageGeneratedFiles,
  messageToolCalls
} from "./side-panel/message-tool-calls";
import { conversationUploads, type PanelContents } from "./side-panel/panel-contents";
import type { PreviewQuote } from "./side-panel/side-panel-store";
import { composeQuotedQuestion } from "./side-panel/question-quote";
import { SidePanel } from "./side-panel/side-panel";
import type { ToolCallRecord } from "./side-panel/message-tool-calls";
import { finishedToolCallIds, newlyFinishedToolCalls } from "./finished-tool-calls";
import { SidePanelProvider, useSidePanel } from "./side-panel/use-side-panel";
import { appViewSubject, appViewTitle, messageAppViewCalls } from "@/features/mcp-apps/mcp-apps";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import { useAnswerFeedback } from "./answer-feedback";
import { disabledCapabilitiesForRequest } from "./chat-capabilities";
import { matchesUpload } from "./chat-attachment-plan";
import {
  ChatMessage,
  PendingAnswer,
  PendingQuestion,
  type ActivityRequest,
  type ToolCards
} from "./chat-message";
import type { ChatReferences } from "./chat-references";
import { Composer, type ComposerHandle } from "./composer";
import { ContextUsageBar } from "./context-usage-bar";
import { ChatTools, mcpConversationOptions } from "./mcp-controls";
import type { PendingUpload } from "./message-files";
import { awaitPartnerUpdates, hasPendingPartnerUpdates } from "./partner-updates";
import { historyQueryKey } from "./session-actions";
import { StartState, type StartHeadingLevel } from "./start-state";
import { releasePreviews, useAttachments, type Attachment } from "./use-attachments";
import { useToolChoices } from "./use-tool-choices";

const NO_MENTION = "__none__";
/** The current time as ISO 8601 (the timestamp of a question sent now). */
function isoNow(): string {
  return new Date().toISOString();
}

type SentFiles = NonNullable<NonNullable<EneoUIMessage["metadata"]>["files"]>;

/** The request options of a question as they stood when it left the composer. */
type SendRequest = Omit<ChatSendOptions, "files" | "session_id" | "assistant_id" | "group_chat_id">;

/**
 * A question sent before its attachments were on the server. It waits in the
 * conversation, mirroring their progress, and the request is issued once all
 * of them are uploaded; an upload that fails, or a stop, takes it back out
 * and returns the draft to the composer.
 */
type PendingQuestionState = {
  /** The text as sent, quote included. */
  text: string;
  /** What the user typed, for the composer should the send be cancelled. */
  question: string;
  quote: PreviewQuote | null;
  /** The composer attachments it was sent with. */
  keys: string[];
  request: SendRequest;
};

/** Which answer's activity is shown, on which tab, and which source to focus. */
export type ActivityState = { messageId: string; tab: ActivityTab; source: number | null };

/**
 * Height of an element, tracked with a ResizeObserver (0 where unsupported).
 * Returns a callback ref, so an element that mounts after the view (the
 * docked composer appears with the first question) is observed too.
 */
function useElementHeight<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null);
  const [height, setHeight] = useState(0);
  useEffect(() => {
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setHeight(Math.ceil(entry.contentRect.height));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, height] as const;
}

/**
 * Astryx's message list is an aria-live log. ACCESSIBILITY.md → AI chat: the
 * list must not be a live region (screen readers would read every streamed
 * token); the view's single polite region announces finished answers
 * instead. React never rewrites the attribute (its value never changes), so
 * turning it off once is enough.
 */
function quietLog(element: HTMLDivElement | null) {
  element?.setAttribute("aria-live", "off");
}

/**
 * A message of the conversation. Every finished answer of a saved
 * conversation can be rated on its own; the rating starts from the one stored
 * with the answer.
 */
const ConversationMessage = memo(function ConversationMessage({
  sessionId,
  onToggleActivity,
  ...props
}: Omit<ComponentProps<typeof ChatMessage>, "feedback" | "onActivityToggle"> & {
  sessionId: string | null;
  /** One handler for every message, so a finished message's props stay the same. */
  onToggleActivity: (messageId: string, trigger: HTMLElement, request?: ActivityRequest) => void;
}) {
  const { message, isStreaming } = props;
  const [rating, rate] = useAnswerFeedback(message.id, message.metadata?.feedback ?? null);
  const feedback =
    sessionId !== null && message.role === "assistant" && !isStreaming
      ? { value: rating, onChange: (value: AnswerRating) => rate(sessionId, value) }
      : null;
  return (
    <ChatMessage
      {...props}
      sessionId={sessionId}
      feedback={feedback}
      onActivityToggle={(trigger, request) => onToggleActivity(message.id, trigger, request)}
    />
  );
});

/**
 * What a file list shows of each file, as one string: a file's content (an
 * upload's transcription) never changes under its id, so it is left out.
 */
function previewFilesKey(files: readonly PreviewFile[]): string {
  return JSON.stringify(
    files.map((file) => [
      file.id,
      file.name,
      file.mimetype,
      file.size,
      file.original_size,
      file.revises_file_id,
      file.created_at
    ])
  );
}

type ChatViewProps = {
  partner: ChatPartner;
  initialSessionId?: string | null;
  initialMessages?: EneoUIMessage[];
  /**
   * Replaces a conversation that was just deleted: the control that deleted it
   * may be gone, so the composer takes focus if focus was lost.
   */
  focusComposerIfLost?: boolean;
  onSessionCreated?: (sessionId: string) => void;
  /** Start a fresh conversation (offered when the context estimate overflows). */
  onNewConversation?: () => void;
  /** The generated title of a new conversation. */
  onTitle?: (title: string) => void;
  /**
   * The list got its first message (a question was sent) or lost it again (a
   * first question that failed before it was sent returns to the composer).
   */
  onStartedChange?: (started: boolean) => void;
  /** Interactive model picker shown in the composer (default-assistant only). */
  modelSelector?: ReactNode;
  /** The personal chat's Skills control, beside Verktyg in the composer. */
  skills?: ReactNode;
  /** Start state for the personal assistant: the assistant selector inside the composer. */
  partnerToken?: ReactNode;
  activity: ActivityState | null;
  onActivityChange: (next: ActivityState | null) => void;
  /**
   * A tool call of this visit reached its result or failed, once per call
   * (calls already in `initialMessages` are not reported). For a page that
   * shows what the conversation's tools change, such as a flow's definition.
   */
  onToolCallFinished?: (call: ToolCallRecord) => void;
  /** An answer ended: finished, stopped or failed. */
  onAnswerFinished?: () => void;
  /**
   * Outline level of the start state's heading: 1 (default) on a chat page,
   * lower where the chat sits inside a page with its own h1.
   */
  startHeadingLevel?: StartHeadingLevel;
  /** What the conversation can refer to (the flow chat's steps and values). */
  references?: ChatReferences;
  /** A card the page draws for a tool call of an answer (the flow chat's run card). */
  toolCards?: ToolCards;
  /** Controls after the composer's pills (the flow chat's Fråga/Redigera picker). */
  footerActions?: ReactNode;
  /** The text field's placeholder, when the page has a better one than "Fråga …". */
  placeholder?: string;
};

/**
 * One conversation: the start state, then the message list with the docked
 * composer and the side panel. Remount it (a new `key`) for another
 * conversation; a view that unmounts while an answer streams lets the stream
 * finish (the answer is saved and the history refreshed) but no longer calls
 * its callbacks, so it never changes the conversation shown after it.
 */
export function ChatView(props: ChatViewProps) {
  return (
    <SidePanelProvider>
      <ConversationView {...props} />
    </SidePanelProvider>
  );
}

function ConversationView({
  partner,
  initialSessionId = null,
  initialMessages = [],
  focusComposerIfLost = false,
  onSessionCreated,
  onNewConversation,
  onTitle,
  onStartedChange,
  modelSelector,
  skills,
  partnerToken,
  activity,
  onActivityChange,
  onToolCallFinished,
  onAnswerFinished,
  startHeadingLevel,
  references,
  toolCards,
  footerActions,
  placeholder
}: ChatViewProps) {
  const t = useTranslations();
  const { featureFlags, can } = useAppContext();
  const queryClient = useQueryClient();
  // A file sent earlier in this conversation is attached again as it is,
  // without another upload. The uploads come from the messages, set up below.
  const uploadsRef = useRef<PreviewFile[]>([]);
  const attachments = useAttachments(partner, {
    findExisting: (file) => uploadsRef.current.find((uploaded) => matchesUpload(file, uploaded))
  });
  const panel = useSidePanel()!;
  // The Felsök tab reads a saved turn's diagnostics; group chats have none.
  const debugAvailable = can("assistant_debug") && partner.type !== "group-chat";
  // Astryx's shared polite live region (mounted empty, cleared after a moment):
  // only "Svaret är klart", errors and tool approvals go there, never tokens.
  const announce = useAnnounce();
  const [timings] = useState(() => new ActivityTimings());
  useSyncExternalStore(timings.subscribe, timings.getVersion, timings.getVersion);
  const toolChoices = useToolChoices(partner);

  const [input, setInput] = useState("");
  const [mentionId, setMentionId] = useState<string>(NO_MENTION);
  const fileInput = useRef<HTMLInputElement>(null);
  // Ref for event-time reads (send body, onFinish); state for render-time
  // consumers (preflight). Both are set together when data-session arrives.
  const sessionIdRef = useRef<string | null>(initialSessionId);
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [liveAnswering, setLiveAnswering] = useState<{ id: string; handle: string } | null>(null);
  const [streamErrorCode, setStreamErrorCode] = useState<number | null>(null);
  const streamErrorCodeRef = useRef<number | null>(null);
  const streamStartedRef = useRef(false);
  // The question on its way: its text and the attachments it took from the
  // composer, put back if it fails before the answer starts.
  const pendingSendRef = useRef<{ text: string; attachments: Attachment[] } | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestionState | null>(null);
  // Ends the wait for the pending question's uploads (a stop while it waits).
  const pendingAbort = useRef<AbortController | null>(null);
  // The last question and its files, for "Försök igen" after an error.
  const [lastQuestion, setLastQuestion] = useState<{ text: string; files: SentFiles } | null>(null);
  const isNewSession = useRef(initialSessionId === null);
  // False once the view unmounted: its stream may still be running.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // What the context window holds after the last turn: the final provider
  // request's counts. The cumulative prompt/completion sums every tool round
  // (each re-sends the conversation) and only stands in for rows saved
  // before the final request's counts were recorded.
  const [lockedTokens, setLockedTokens] = useState(() => {
    const tokens = initialMessages[initialMessages.length - 1]?.metadata?.tokens;
    return {
      input: tokens?.contextPrompt ?? tokens?.prompt ?? 0,
      output: tokens?.contextCompletion ?? tokens?.completion ?? 0
    };
  });
  // Running conversation total, seeded from history (sum of each turn's
  // prompt+completion), then incremented per live token-usage event.
  const [cumulative, setCumulative] = useState(() => {
    let tokens = 0;
    let turns = 0;
    for (const message of initialMessages) {
      if (message.role !== "assistant") continue;
      const turnTokens =
        (message.metadata?.tokens?.prompt ?? 0) + (message.metadata?.tokens?.completion ?? 0);
      if (turnTokens > 0) {
        tokens += turnTokens;
        turns += 1;
      }
    }
    return { tokens, turns };
  });

  // Focus hand-off: the first question swaps the centred start composer for
  // the docked one (and a first question that fails before it is sent swaps
  // back); keep keyboard focus in the composer (WCAG 2.4.3).
  const startComposerRef = useRef<HTMLDivElement>(null);
  const dockElement = useRef<HTMLDivElement | null>(null);
  const dockInputRef = useRef<ComposerHandle>(null);
  const startInputRef = useRef<ComposerHandle>(null);
  const refocusComposer = useRef(false);
  const rescue = useFocusRescue();
  useEffect(() => {
    if (focusComposerIfLost) rescue(() => startInputRef.current?.element ?? null);
  }, [focusComposerIfLost, rescue]);

  const transport = useMemo(() => createChatTransport(), []);
  const { messages, sendMessage, setMessages, status, stop, error, clearError } =
    useChat<EneoUIMessage>({
      transport,
      messages: initialMessages,
      // Backend forwards one SSE delta per provider token; coalesce UI updates to
      // ~20/s so fast streams don't re-parse markdown on every token (the Svelte
      // app frame-buffered for the same reason). Tune up for snappier, down for calmer.
      experimental_throttle: 50,
      onData: (part) => {
        if (part.type === "data-session") {
          streamStartedRef.current = true;
          // The question went through: its attachments won't come back.
          const pending = pendingSendRef.current;
          if (pending) releasePreviews(pending.attachments.splice(0));
          if (!sessionIdRef.current) {
            sessionIdRef.current = part.data.session_id;
            setSessionId(part.data.session_id);
            if (mounted.current) onSessionCreated?.(part.data.session_id);
          }
          setLiveAnswering(part.data.answering_assistant ?? null);
        }
        if (part.type === "data-error") {
          streamErrorCodeRef.current = part.data.code ?? null;
          setStreamErrorCode(part.data.code ?? null);
        }
        if (
          part.type === "data-tool-approval" &&
          part.data.status === "pending" &&
          mounted.current
        ) {
          const names = part.data.tools.map((tool) => tool.title || tool.tool_name).join(", ");
          announce(t("chat_announce_tool_approval", { tools: names }));
        }
        if (part.type === "data-token-usage") {
          setLockedTokens({
            input: part.data.context_prompt_tokens ?? part.data.prompt_tokens ?? 0,
            output: part.data.context_completion_tokens ?? part.data.completion_tokens ?? 0
          });
          timings.markTokens(part.data.completion_tokens ?? 0);
          const turnTokens = part.data.turn_tokens ?? 0;
          if (turnTokens > 0) {
            setCumulative((current) => ({
              tokens: current.tokens + turnTokens,
              turns: current.turns + 1
            }));
          }
        }
      },
      onError: (failure) => {
        const pending = pendingSendRef.current;
        pendingSendRef.current = null;
        if (!mounted.current) {
          if (pending) releasePreviews(pending.attachments);
          return;
        }
        announce(describeChatFailure(failure, streamErrorCodeRef.current, t).message);
        if (!pending || streamStartedRef.current) return;
        // Failed before the answer started: the question goes back to the
        // composer, attachments included. A first question takes the view back
        // to the start state; keep focus in the composer across that swap.
        setInput((current) => (current.trim() ? current : pending.text));
        attachments.restore(pending.attachments);
        setMessages((current) => {
          const last = current.at(-1);
          if (
            last?.role === "user" &&
            last.parts.some((part) => part.type === "text" && part.text === pending.text)
          ) {
            // useChat applies this at once, before the view re-renders.
            if (current.length === 1) {
              refocusComposer.current =
                dockElement.current?.contains(document.activeElement ?? null) ?? false;
            }
            return current.slice(0, -1);
          }
          return current;
        });
      },
      onFinish: async ({ isAbort, isError }) => {
        const pending = pendingSendRef.current;
        pendingSendRef.current = null;
        if (pending) releasePreviews(pending.attachments);
        if (mounted.current) {
          if (isAbort) announce(t("chat_announce_stopped"));
          else if (!isError) announce(t("chat_announce_answer_ready"));
          onAnswerFinished?.();
        }
        // Auto-title after the first exchange of a fresh conversation (also when
        // the view has gone: the history then lists it under its title).
        if (isNewSession.current && sessionIdRef.current) {
          isNewSession.current = false;
          try {
            const { data } = await browserApi.POST("/api/v1/conversations/{session_id}/title/", {
              params: { path: { session_id: sessionIdRef.current } }
            });
            if (data?.name && mounted.current) onTitle?.(data.name);
          } catch {
            // Title generation is a nicety; ignore failures.
          }
        }
        invalidateConversationLists(queryClient, historyQueryKey(partner));
      }
    });

  const busy = status === "submitted" || status === "streaming";
  // The composer is taken from the moment a question leaves it, uploads included.
  const sending = busy || pendingQuestion !== null;

  // Record client-side step timings for the answer being streamed.
  useEffect(() => {
    timings.observe(messages, busy, Date.now());
  }, [timings, messages, busy]);

  // What the conversation has to show in the side panel.
  const documentsNow = useMemo(
    () =>
      conversationDocuments(
        messages.map((message) => ({
          files: messageGeneratedFiles(message),
          calls: messageToolCalls(message)
        }))
      ),
    [messages]
  );
  // A streamed chunk rarely changes the documents: keep them by content so
  // finished messages keep the same props.
  const documentsKey = useMemo(
    () => documentsNow.documents.map((document) => previewFilesKey(document.versions)).join("\n"),
    [documentsNow]
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- compared by content
  const documents = useMemo(() => documentsNow, [documentsKey]);
  const uploads = useMemo(() => conversationUploads(messages), [messages]);
  useEffect(() => {
    uploadsRef.current = uploads;
  }, [uploads]);
  const allFilesNow = useMemo<PreviewFile[]>(
    () => [...uploads, ...messages.flatMap(messageGeneratedFiles)],
    [uploads, messages]
  );
  const allFilesKey = useMemo(() => previewFilesKey(allFilesNow), [allFilesNow]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- compared by content
  const allFiles = useMemo(() => allFilesNow, [allFilesKey]);
  const panelContents: PanelContents = {
    views: messages
      .flatMap(messageAppViewCalls)
      .filter((call) => panel.offeredViews.has(call.toolCallId))
      .reverse()
      .map((call) => ({
        id: call.toolCallId,
        title: appViewTitle(call, t),
        subject: appViewSubject(call),
        shown: panel.viewCallId === call.toolCallId,
        open: () => panel.openView(call.toolCallId)
      })),
    documents: documents.documents,
    uploads
  };
  const versionsOf = (file: PreviewFile) => documents.versionsOf(file.id);
  // A Markdown document the assistant made here can be handed over as Word or
  // PDF: the assistant's own document tool renders it, when it has one.
  const exportOf = (file: PreviewFile) =>
    sessionId && isExportableDocument(file) && documents.versionsOf(file.id).length > 0
      ? documentExport(sessionId, file.id)
      : null;
  // A reader's edit of such a document is saved as its next version, which
  // joins the answer that holds the version it was edited from, as the
  // backend has stored it, so the documents update without a reload.
  const saverOf = (file: PreviewFile): DocumentSaver | null =>
    sessionId && isExportableDocument(file) && documents.versionsOf(file.id).length > 0
      ? {
          save: async (content) => {
            const version = await saveDocumentVersion(sessionId, file.id, content);
            setMessages((current) => addGeneratedFile(current, version));
            return version;
          }
        }
      : null;
  // Leaving the page would lose unsaved edits to a document.
  useBeforeUnloadWarning(panel.dirty);

  // The panel and an answer's activity share the side region, one at a time.
  const panelOpen = panel.occupant.kind !== "closed";
  useEffect(() => {
    if (activity) panel.closeAll();
  }, [activity, panel]);
  useEffect(() => {
    if (panelOpen) onActivityChange(null);
  }, [panelOpen, onActivityChange]);

  // The panel follows the answer being written: a document draft shows there
  // while the assistant writes it, and a file created in the live turn takes
  // it over, so an edit is seen without reopening anything. Files of a
  // conversation loaded from history are only noted, never opened.
  useEffect(() => {
    if (busy) panel.beginAnswer();
    else panel.endDraft();
  }, [busy, panel]);
  const last = messages.at(-1);
  const liveCalls = useMemo(
    () => (busy && last?.role === "assistant" ? messageToolCalls(last) : []),
    [busy, last]
  );
  const liveFiles = useMemo(
    () => (busy && last?.role === "assistant" ? messageGeneratedFiles(last) : []),
    [busy, last]
  );
  // The newest document being written: actual text as it arrives.
  const liveDraft = useMemo(() => {
    for (let index = liveCalls.length - 1; index >= 0; index--) {
      const call = liveCalls[index]!;
      const draft = documentDraft(
        call,
        call.input,
        liveFiles.some((file) => file.toolCallId === call.toolCallId)
      );
      if (draft) return draft;
    }
    return null;
  }, [liveCalls, liveFiles]);
  useEffect(() => {
    if (liveDraft) panel.write(liveDraft);
  }, [liveDraft, panel]);
  const arrivedFiles = useRef(new Set<string>());
  useEffect(() => {
    for (const file of liveFiles) {
      if (!file.id || !file.toolCallId || arrivedFiles.current.has(file.id)) continue;
      // Files arrive with their call's id, so hidden analysis exports never
      // replace the reader's preview: only a document the model wrote opens.
      arrivedFiles.current.add(file.id);
      const call = liveCalls.find((candidate) => candidate.toolCallId === file.toolCallId);
      if (call?.purpose !== "file_creation" || !panel.canPreview(file)) continue;
      const changed = editedPassage(call.input);
      panel.arrive(file, changed ? { text: changed, locator: null } : null, call.toolCallId);
    }
  }, [liveFiles, liveCalls, panel]);

  // A message an interactive view offered lands in the composer.
  useEffect(
    () =>
      panel.subscribe(() => {
        const text = panel.takeSuggestion();
        if (text === null) return;
        setInput((current) => (current.trim() ? `${current}\n${text}` : text));
        dockInputRef.current?.focus();
      }),
    [panel]
  );

  const preflight = usePreflight({
    question: input,
    fileIds: attachments.fileIds,
    sessionId,
    assistantId: sessionId || partner.type === "group-chat" ? null : partner.id,
    groupChatId: !sessionId && partner.type === "group-chat" ? partner.id : null
  });

  const usage = deriveContextUsage({
    preflight,
    lockedInputTokens: lockedTokens.input,
    lockedOutputTokens: lockedTokens.output,
    fallbackContextLimit: partner.completionModel?.token_limit ?? 0
  });

  const openAttachmentDialog = useCallback(() => {
    fileInput.current?.click();
  }, []);

  // Tool calls that had finished before this visit are not news; the first
  // run takes them as seen.
  const seenToolCalls = useRef<Set<string> | null>(null);
  const reportToolCall = useEffectEvent((call: ToolCallRecord) => onToolCallFinished?.(call));
  useEffect(() => {
    if (seenToolCalls.current === null) {
      seenToolCalls.current = new Set(finishedToolCallIds(messages));
      return;
    }
    for (const call of newlyFinishedToolCalls(messages, seenToolCalls.current)) {
      reportToolCall(call);
    }
  }, [messages]);

  const started = messages.length > 0 || pendingQuestion !== null;
  const reportStarted = useEffectEvent((value: boolean) => onStartedChange?.(value));
  useEffect(() => {
    reportStarted(started);
    if (refocusComposer.current) {
      refocusComposer.current = false;
      (started ? dockInputRef : startInputRef).current?.focus();
    }
  }, [started]);

  /** The files a batch of composer attachments travels as: ids for the request, names for the chips. */
  const sentFiles = (batch: readonly Attachment[]): SentFiles =>
    batch.flatMap((attachment) =>
      attachment.fileId
        ? [
            {
              id: attachment.fileId,
              name: attachment.name,
              mimetype: attachment.mimetype,
              size: attachment.size
            }
          ]
        : []
    ) as SentFiles;

  /** The request options as they stand now, for the question leaving the composer. */
  function requestOptions(): SendRequest {
    const mention =
      partner.type === "group-chat" && mentionId !== NO_MENTION
        ? partner.mentionableAssistants?.find((assistant) => assistant.id === mentionId)
        : undefined;
    const mcpOptions = mcpConversationOptions({
      servers: toolChoices.mcpServers,
      disabledServerIds: toolChoices.disabledMcpServerIds,
      autoAcceptTools: toolChoices.autoAcceptTools,
      supportsToolApproval: partner.type !== "group-chat"
    });
    return {
      tools: mention ? { assistants: [{ id: mention.id, handle: mention.handle }] } : null,
      disabled_capabilities: disabledCapabilitiesForRequest(
        partner,
        toolChoices.disabledCapabilities,
        featureFlags.showWebSearch
      ),
      ...mcpOptions
    };
  }

  /**
   * Sends a question; `resendFiles` repeats a failed question's attachments
   * ("Försök igen"), which leave the composer if they were put back there.
   * Attachments still uploading do not hold the question back: it leaves the
   * composer at once and waits in the conversation until all of them are on
   * the server (`awaitUploads`), or is withdrawn if they never are.
   */
  function sendQuestion(question: string, resendFiles?: SentFiles) {
    if (!question || sending || usage.willExceedContext) return;
    // A quote from a file or a view opens the question; it is sent once.
    const quote = resendFiles ? null : panel.quote;
    const text = resendFiles ? question : composeQuotedQuestion(quote, question);
    if (!resendFiles) panel.clearQuote();
    if (!started) {
      refocusComposer.current = Boolean(
        startComposerRef.current?.contains(document.activeElement ?? null)
      );
    }
    const request = requestOptions();
    // A retry leaves the composer alone unless it holds the retried question.
    setInput((current) => (resendFiles && current.trim() !== question ? current : ""));
    setMentionId(NO_MENTION);

    const batch = attachments.attachments;
    if (!resendFiles && batch.some((attachment) => attachment.uploading)) {
      const pending: PendingQuestionState = {
        text,
        question,
        quote,
        keys: batch.map((attachment) => attachment.key),
        request
      };
      const first = !started;
      const controller = new AbortController();
      pendingAbort.current = controller;
      setPendingQuestion(pending);
      // The request is issued once every attachment of the batch is on the
      // server; an upload that fails (which the upload has reported) or a
      // stop takes the question back out instead.
      attachments.awaitUploads(pending.keys, controller.signal).then(
        (ready) => {
          if (!mounted.current) return;
          pendingAbort.current = null;
          setPendingQuestion(null);
          issue(pending.text, sentFiles(ready), pending.request);
        },
        () => {
          if (!mounted.current) return;
          pendingAbort.current = null;
          withdrawQuestion(pending, first);
        }
      );
      return;
    }
    issue(text, resendFiles ?? sentFiles(batch), request);
  }

  /** Issues the request for a question whose files are all on the server. */
  function issue(text: string, files: SentFiles, request: SendRequest) {
    clearError();
    setStreamErrorCode(null);
    streamErrorCodeRef.current = null;
    streamStartedRef.current = false;
    // Previews of an earlier question that never started are no longer needed.
    if (pendingSendRef.current) releasePreviews(pendingSendRef.current.attachments);
    // Uploaded attachments travel as file ids; the metadata renders them as
    // file chips under the question.
    pendingSendRef.current = {
      text,
      attachments: attachments.detach(new Set(files.map((file) => file.id)))
    };
    setLastQuestion({ text, files });

    // The backend wants exactly ONE of session_id/assistant_id/group_chat_id:
    // continuing a session identifies the partner through the session.
    const continuing = sessionIdRef.current !== null;
    const body: ChatSendOptions = {
      session_id: sessionIdRef.current,
      assistant_id: continuing || partner.type === "group-chat" ? null : partner.id,
      group_chat_id: !continuing && partner.type === "group-chat" ? partner.id : null,
      files: files.map((file) => ({ id: file.id })),
      ...request
    };

    timings.markSent();
    const send = () => sendMessage({ text, metadata: { files, createdAt: isoNow() } }, { body });
    // A model or reasoning switch made in the composer is saved on the
    // assistant; the backend answers with what is stored, so that save lands first.
    if (hasPendingPartnerUpdates()) void awaitPartnerUpdates().then(send);
    else void send();
  }

  /** Takes a waiting question back out of the conversation; nothing was sent. */
  function withdrawQuestion(pending: PendingQuestionState, first: boolean) {
    setPendingQuestion(null);
    // The draft comes back unless the user has already started a new one.
    setInput((current) => (current.trim() ? current : pending.question));
    panel.restoreQuote(pending.quote);
    // A first question takes the view back to the start state; keep focus in
    // the composer across that swap.
    if (first) {
      refocusComposer.current =
        dockElement.current?.contains(document.activeElement ?? null) ?? false;
    }
  }

  // While a question waits for its uploads they are shown on it, not in the composer.
  const pendingKeys = new Set(pendingQuestion?.keys ?? []);
  const pendingUploads: PendingUpload[] = pendingQuestion
    ? attachments.attachments
        .filter((attachment) => pendingKeys.has(attachment.key))
        .map(({ key, name, size, mimetype, uploading }) => ({
          key,
          name,
          size,
          mimetype,
          uploading
        }))
    : [];
  const pendingDone = pendingUploads.filter((upload) => !upload.uploading).length;
  const composerAttachments = pendingQuestion
    ? {
        ...attachments,
        attachments: attachments.attachments.filter(
          (attachment) => !pendingKeys.has(attachment.key)
        )
      }
    : attachments;

  // Attachments still uploading do not block: the question waits for them in
  // the conversation.
  const canSubmit = input.trim().length > 0 && !usage.willExceedContext;
  const quote = panel.quote;
  const composerQuote = quote
    ? { text: quote.text, source: quote.fileName, onRemove: () => panel.clearQuote() }
    : null;

  const activityMessage = activity
    ? messages.find((message) => message.id === activity.messageId)
    : undefined;
  const activityForPanel = activityMessage
    ? deriveActivity(activityMessage, {
        streaming: busy && activityMessage.id === messages.at(-1)?.id,
        knowledge: partner.knowledge,
        tokens: timings.durations(activityMessage.id)?.tokens ?? null,
        files: conversationFiles(messages)
      })
    : null;

  // Focus returns to the control that opened the panel (pill or citation).
  const activityTrigger = useRef<HTMLElement | null>(null);
  const closeActivity = useCallback(() => {
    onActivityChange(null);
    const trigger = activityTrigger.current;
    activityTrigger.current = null;
    if (trigger) requestAnimationFrame(() => trigger.focus());
  }, [onActivityChange]);
  const openActivityId = activity?.messageId;
  const toggleActivity = useCallback(
    (messageId: string, trigger: HTMLElement, request?: ActivityRequest) => {
      const tab = request?.tab ?? "steps";
      // The pill toggles; a citation (or menu item with a tab) opens or switches.
      if (openActivityId === messageId && !request?.tab) {
        closeActivity();
        return;
      }
      activityTrigger.current = trigger;
      onActivityChange({ messageId, tab, source: request?.source ?? null });
    },
    [openActivityId, closeActivity, onActivityChange]
  );

  const failure = error ? describeChatFailure(error, streamErrorCode, t) : null;

  const partnerName = displayPartnerName(partner, t);
  const assistantIdentity = useMemo(
    () => ({ id: partner.id, name: partnerName, iconId: partner.iconId }),
    [partner.id, partnerName, partner.iconId]
  );
  const mention =
    partner.type === "group-chat" && (partner.mentionableAssistants?.length ?? 0) > 0 ? (
      <Selector
        label={t("mention")}
        isLabelHidden
        variant="ghost"
        size="sm"
        value={mentionId}
        onChange={setMentionId}
        options={[
          { value: NO_MENTION, label: t("mentions") },
          ...partner.mentionableAssistants!.map((assistant) => ({
            value: assistant.id,
            label: `@${assistant.handle}`
          }))
        ]}
      />
    ) : null;

  const tools = (
    <ChatTools
      capabilities={toolChoices.capabilities}
      disabledCapabilities={toolChoices.disabledCapabilities}
      servers={toolChoices.mcpServers}
      disabledServerIds={toolChoices.disabledMcpServerIds}
      autoAcceptTools={toolChoices.autoAcceptTools}
      modelSupportsTools={toolChoices.modelSupportsTools}
      onDisabledCapabilitiesChange={toolChoices.setDisabledCapabilities}
      onDisabledServerIdsChange={toolChoices.setDisabledMcpServerIds}
      onAutoAcceptToolsChange={toolChoices.setAutoAcceptTools}
    />
  );

  const composerLabel = t("chat_composer_label", { name: partnerName });
  const composerProps = {
    value: input,
    onChange: setInput,
    onSubmit: () => sendQuestion(input.trim()),
    canSubmit,
    busy: sending,
    // A stop while the question still waits for its uploads takes it back.
    onStop: () => (pendingAbort.current ? pendingAbort.current.abort() : void stop()),
    label: composerLabel,
    placeholder: placeholder ?? t("chat_composer_placeholder"),
    attachments: composerAttachments,
    onOpenFileDialog: openAttachmentDialog,
    knowledge: partner.knowledge,
    tools,
    skills,
    mention,
    modelSelector,
    quote: composerQuote,
    triggers: references?.triggers,
    headerActions: references?.headerActions,
    footerActions,
    onInput: references?.onComposer,
    contextBar: (
      <ContextUsageBar
        usage={usage}
        modelName={partner.completionModel?.name}
        cumulativeTokens={cumulative.tokens}
        turnCount={cumulative.turns}
        onNewConversation={onNewConversation}
      />
    )
  };

  const [observeDock, dockHeight] = useElementHeight<HTMLDivElement>();
  const dockRef = useCallback(
    (element: HTMLDivElement | null) => {
      dockElement.current = element;
      observeDock(element);
    },
    [observeDock]
  );

  const fileInputElement =
    attachments.maxFiles !== 0 ? (
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        accept={attachments.acceptString}
        onChange={(event) => {
          attachments.addFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
    ) : null;

  // Generation failed: one sentence (also announced), a retry of the same
  // question and, for support, the technical facts behind "Visa detaljer".
  // Shown in both layouts: a first question that fails before streaming
  // starts puts the view back in the start state.
  const errorNotice = failure ? (
    <ChatSystemMessage icon={<CircleAlert aria-hidden="true" className="text-ax-error size-4" />}>
      <span className="flex flex-col items-center gap-2">
        <span className="flex flex-wrap items-center justify-center gap-2">
          <span className="text-ax-error">{failure.message}</span>
          {lastQuestion && !sending && (
            <Button
              label={t("chat_retry")}
              size="sm"
              variant="secondary"
              onClick={() => sendQuestion(lastQuestion.text, lastQuestion.files)}
            />
          )}
        </span>
        {failure.details.length > 0 && (
          <Collapsible
            trigger={t("chat_error_show_details")}
            defaultIsOpen={false}
            className="w-full max-w-prose"
          >
            <ul
              aria-label={t("chat_error_details_label")}
              className="text-ax-text-secondary flex flex-col gap-0.5 text-start font-mono text-xs break-words"
            >
              {failure.details.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </Collapsible>
        )}
      </span>
    </ChatSystemMessage>
  ) : null;

  if (!started) {
    return (
      <>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <StartState
            partner={partner}
            headingLevel={startHeadingLevel}
            onPickStarter={(prompt) => {
              setInput(prompt);
              startInputRef.current?.focus();
            }}
            composer={
              <div ref={startComposerRef} className="flex w-full flex-col gap-3">
                {errorNotice}
                <Composer
                  {...composerProps}
                  variant="start"
                  partnerToken={partnerToken}
                  inputRef={startInputRef}
                />
              </div>
            }
          />
        </div>
        {/* One file input for the view's lifetime (same position in both layouts). */}
        {fileInputElement}
      </>
    );
  }

  // The latest answer's activity, offered in the panel's switcher.
  const latestAnswer = messages.findLast((message) => message.role === "assistant");
  const latestActivity =
    latestAnswer &&
    deriveActivity(latestAnswer, { streaming: busy && latestAnswer === messages.at(-1) })
      .hasActivity
      ? {
          detail: t("chat_activity_steps", {
            count: deriveActivity(latestAnswer, { knowledge: partner.knowledge }).steps.length
          }),
          open: () => onActivityChange({ messageId: latestAnswer.id, tab: "steps", source: null })
        }
      : null;

  return (
    <>
      <SidePanel
        panel={panel}
        messages={messages}
        contents={panelContents}
        versionsOf={versionsOf}
        exportOf={exportOf}
        saverOf={saverOf}
        latestActivity={latestActivity}
        activity={
          activity && activityMessage && activityForPanel
            ? {
                detail: t("chat_activity_steps", { count: activityForPanel.steps.length }),
                onClose: closeActivity,
                body: (
                  <ActivityPanelBody
                    messageId={activityMessage.id}
                    activity={activityForPanel}
                    durations={timings.durations(activityMessage.id)}
                    sessionId={sessionId}
                    tab={activity.tab}
                    onTabChange={(tab) => onActivityChange({ ...activity, tab, source: null })}
                    focusSource={activity.source}
                    debug={
                      debugAvailable && sessionId !== null
                        ? {
                            sessionId,
                            onSelectTurn: (messageId) =>
                              onActivityChange({ messageId, tab: "debug", source: null })
                          }
                        : null
                    }
                  />
                )
              }
            : null
        }
      >
        <ChatLayout
          className="min-w-0 flex-1"
          // WCAG 2.4.11: Tab and focus() scroll the focused element above the
          // docked composer instead of behind it.
          style={{ scrollPaddingBottom: dockHeight + 28 }}
          composer={
            <div ref={dockRef} className="mx-auto w-full max-w-[680px]">
              <Composer {...composerProps} inputRef={dockInputRef} />
            </div>
          }
        >
          <ChatMessageList
            ref={quietLog}
            aria-label={t("chat_conversation_label")}
            gap={6}
            isStreaming={busy}
            className="focus-visible:outline-ring rounded-ax-container mx-auto w-full max-w-[712px] focus-visible:outline-2 focus-visible:-outline-offset-2"
          >
            {messages.map((message, messageIndex) => {
              const streaming = busy && messageIndex === messages.length - 1;
              return (
                <ConversationMessage
                  key={message.id}
                  sessionId={sessionId}
                  message={message}
                  assistant={assistantIdentity}
                  isStreaming={streaming}
                  showResponseLabel={partner.showResponseLabel ?? false}
                  liveAnswering={liveAnswering}
                  knowledge={partner.knowledge}
                  durations={timings.durations(message.id)}
                  activityExpanded={activity?.messageId === message.id}
                  onToggleActivity={toggleActivity}
                  canDebug={debugAvailable && sessionId !== null}
                  conversationFiles={allFiles}
                  documents={documents.documents}
                  draft={streaming ? liveDraft : null}
                  references={references}
                  toolCards={toolCards}
                />
              );
            })}
            {pendingQuestion && (
              <PendingQuestion
                text={pendingQuestion.text}
                uploads={pendingUploads}
                conversationFiles={allFiles}
                references={references}
              />
            )}
            {(status === "submitted" || pendingQuestion) && (
              <PendingAnswer
                assistant={assistantIdentity}
                status={
                  pendingQuestion
                    ? t("uploading_attachments_progress", {
                        done: pendingDone,
                        total: pendingUploads.length
                      })
                    : undefined
                }
              />
            )}
            {errorNotice}
          </ChatMessageList>
        </ChatLayout>
      </SidePanel>
      {fileInputElement}
    </>
  );
}

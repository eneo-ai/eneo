"use client";

import { useChat } from "@ai-sdk/react";
import { Button } from "@astryxdesign/core/Button";
import { ChatLayout, ChatMessageList, ChatSystemMessage } from "@astryxdesign/core/Chat";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { Selector } from "@astryxdesign/core/Selector";
import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode
} from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessageForCode } from "@/lib/api/errors";
import { createChatTransport, type ChatSendOptions } from "@/lib/chat/transport";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { deriveContextUsage, usePreflight } from "@/lib/chat/use-preflight";
import { deriveActivity } from "./activity";
import { ActivityPanel, type ActivityTab } from "./activity-panel";
import { ActivityTimings } from "./activity-timings";
import { disabledCapabilitiesForRequest } from "./chat-capabilities";
import { ChatMessage, PendingAnswer, type ActivityRequest } from "./chat-message";
import { Composer } from "./composer";
import { ContextUsageBar } from "./context-usage-bar";
import { ChatMcpServers, mcpConversationOptions } from "./mcp-controls";
import { historyQueryKey, useSessionMutations } from "./session-actions";
import { StartState } from "./start-state";
import { releasePreviews, useAttachments, type Attachment } from "./use-attachments";
import { useToolChoices } from "./use-tool-choices";

const NO_MENTION = "__none__";
/** The current time as ISO 8601 (the timestamp of a question sent now). */
function isoNow(): string {
  return new Date().toISOString();
}

type SentFiles = NonNullable<NonNullable<EneoUIMessage["metadata"]>["files"]>;

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
 * One conversation: the start state, then the message list with the docked
 * composer. Remount it (a new `key`) for another conversation; a view that
 * unmounts while an answer streams lets the stream finish (the answer is
 * saved and the history refreshed) but no longer calls its callbacks, so it
 * never changes the conversation shown after it.
 */
export function ChatView({
  partner,
  initialSessionId = null,
  initialMessages = [],
  feedback = null,
  onRated,
  onSessionCreated,
  onNewConversation,
  onTitle,
  onStartedChange,
  modelSelector,
  partnerToken,
  activity,
  onActivityChange
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  initialMessages?: EneoUIMessage[];
  /** The session's feedback (session-level, shown on the latest answer). */
  feedback?: 1 | -1 | null;
  /** The answer thumbs rated the session. */
  onRated?: (sessionId: string, value: 1 | -1) => void;
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
  /** Start state for the personal assistant: the assistant selector inside the composer. */
  partnerToken?: ReactNode;
  activity: ActivityState | null;
  onActivityChange: (next: ActivityState | null) => void;
}) {
  const t = useTranslations();
  const { featureFlags } = useAppContext();
  const queryClient = useQueryClient();
  const attachments = useAttachments(partner);
  const isDesktop = useMediaQuery("(min-width: 1024px)");
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
  // The last question and its files, for "Försök igen" after an error.
  const [lastQuestion, setLastQuestion] = useState<{ text: string; files: SentFiles } | null>(null);
  const isNewSession = useRef(initialSessionId === null);
  const { feedback: feedbackMutation } = useSessionMutations(partner, { onRated });
  // False once the view unmounted: its stream may still be running.
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [lockedTokens, setLockedTokens] = useState(() => {
    const last = initialMessages[initialMessages.length - 1];
    return {
      input: last?.metadata?.tokens?.prompt ?? 0,
      output: last?.metadata?.tokens?.completion ?? 0
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
  const dockTextareaRef = useRef<HTMLTextAreaElement>(null);
  const startTextareaRef = useRef<HTMLTextAreaElement>(null);
  const refocusComposer = useRef(false);

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
            input: part.data.prompt_tokens ?? 0,
            output: part.data.completion_tokens ?? 0
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
        announce(
          getErrorMessageForCode(streamErrorCodeRef.current, t) ??
            (failure.message || t("request_failed"))
        );
        if (!pending || streamStartedRef.current) return;
        // Failed before the answer started: the question goes back to the
        // composer, attachments included. A first question takes the view back
        // to the start state; keep focus in the composer across that swap.
        refocusComposer.current =
          dockElement.current?.contains(document.activeElement ?? null) ?? false;
        setInput((current) => (current.trim() ? current : pending.text));
        attachments.restore(pending.attachments);
        setMessages((current) => {
          const last = current.at(-1);
          if (
            last?.role === "user" &&
            last.parts.some((part) => part.type === "text" && part.text === pending.text)
          ) {
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
        queryClient.invalidateQueries({ queryKey: historyQueryKey(partner) });
      }
    });

  const busy = status === "submitted" || status === "streaming";

  // Record client-side step timings for the answer being streamed.
  useEffect(() => {
    timings.observe(messages, busy, Date.now());
  }, [timings, messages, busy]);

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

  const started = messages.length > 0;
  const reportStarted = useEffectEvent((value: boolean) => onStartedChange?.(value));
  useEffect(() => {
    reportStarted(started);
    if (refocusComposer.current) {
      refocusComposer.current = false;
      (started ? dockTextareaRef : startTextareaRef).current?.focus();
    }
  }, [started]);

  /**
   * Sends a question; `resendFiles` repeats a failed question's attachments
   * ("Försök igen"), which leave the composer if they were put back there.
   */
  function sendQuestion(text: string, resendFiles?: SentFiles) {
    if (!text || busy || attachments.uploading || usage.willExceedContext) return;
    // Uploaded attachments travel as file ids; the metadata renders them as
    // file tokens under the question.
    const files =
      resendFiles ??
      (attachments.attachments.flatMap((attachment) =>
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
      ) as SentFiles);
    clearError();
    setStreamErrorCode(null);
    streamErrorCodeRef.current = null;
    streamStartedRef.current = false;
    // Previews of an earlier question that never started are no longer needed.
    if (pendingSendRef.current) releasePreviews(pendingSendRef.current.attachments);
    pendingSendRef.current = {
      text,
      attachments: attachments.detach(new Set(files.map((file) => file.id)))
    };
    setLastQuestion({ text, files });
    if (!started) {
      refocusComposer.current = Boolean(
        startComposerRef.current?.contains(document.activeElement ?? null)
      );
    }

    const mention =
      partner.type === "group-chat" && mentionId !== NO_MENTION
        ? partner.mentionableAssistants?.find((assistant) => assistant.id === mentionId)
        : undefined;

    // The backend wants exactly ONE of session_id/assistant_id/group_chat_id:
    // continuing a session identifies the partner through the session.
    const continuing = sessionIdRef.current !== null;
    const mcpOptions = mcpConversationOptions({
      servers: toolChoices.mcpServers,
      disabledServerIds: toolChoices.disabledMcpServerIds,
      autoAcceptTools: toolChoices.autoAcceptTools,
      supportsToolApproval: partner.type !== "group-chat"
    });
    const body: ChatSendOptions = {
      session_id: sessionIdRef.current,
      assistant_id: continuing || partner.type === "group-chat" ? null : partner.id,
      group_chat_id: !continuing && partner.type === "group-chat" ? partner.id : null,
      files: files.map((file) => ({ id: file.id })),
      tools: mention ? { assistants: [{ id: mention.id, handle: mention.handle }] } : null,
      disabled_capabilities: disabledCapabilitiesForRequest(
        partner,
        toolChoices.disabledCapabilities,
        featureFlags.showWebSearch
      ),
      ...mcpOptions
    };

    timings.markSent();
    void sendMessage({ text, metadata: { files, createdAt: isoNow() } }, { body });
    // A retry leaves the composer alone unless it holds the retried question.
    setInput((current) => (resendFiles && current.trim() !== text ? current : ""));
    setMentionId(NO_MENTION);
  }

  const canSubmit = input.trim().length > 0 && !attachments.uploading && !usage.willExceedContext;

  const lastAssistantIndex = messages.findLastIndex((message) => message.role === "assistant");
  const activityMessage = activity
    ? messages.find((message) => message.id === activity.messageId)
    : undefined;
  const activityForPanel = activityMessage
    ? deriveActivity(activityMessage, {
        streaming: busy && activityMessage.id === messages.at(-1)?.id,
        knowledge: partner.knowledge,
        tokens: timings.durations(activityMessage.id)?.tokens ?? null
      })
    : null;

  // Focus returns to the control that opened the panel (pill or citation).
  const activityTrigger = useRef<HTMLElement | null>(null);
  const toggleActivity = (messageId: string, trigger: HTMLElement, request?: ActivityRequest) => {
    const tab = request?.tab ?? "steps";
    // The pill toggles; a citation (or menu item with a tab) opens or switches.
    if (activity?.messageId === messageId && !request?.tab) {
      closeActivity();
      return;
    }
    activityTrigger.current = trigger;
    onActivityChange({ messageId, tab, source: request?.source ?? null });
  };
  const closeActivity = useCallback(() => {
    onActivityChange(null);
    const trigger = activityTrigger.current;
    activityTrigger.current = null;
    if (trigger) requestAnimationFrame(() => trigger.focus());
  }, [onActivityChange]);

  const setFeedback = (value: 1 | -1) => {
    if (!sessionIdRef.current) return;
    feedbackMutation.mutate({ id: sessionIdRef.current, value });
  };

  const errorText = error
    ? (getErrorMessageForCode(streamErrorCode, t) ?? (error.message || t("request_failed")))
    : null;

  const assistantIdentity = { id: partner.id, name: partner.name, iconId: partner.iconId };
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

  const tools =
    toolChoices.mcpServers.length > 0 ? (
      <ChatMcpServers
        servers={toolChoices.mcpServers}
        disabledServerIds={toolChoices.disabledMcpServerIds}
        autoAcceptTools={toolChoices.autoAcceptTools}
        onDisabledServerIdsChange={toolChoices.setDisabledMcpServerIds}
        onAutoAcceptToolsChange={toolChoices.setAutoAcceptTools}
      />
    ) : null;

  const composerLabel = t("chat_composer_label", { name: partner.name });
  const composerProps = {
    value: input,
    onChange: setInput,
    onSubmit: () => sendQuestion(input.trim()),
    canSubmit,
    busy,
    onStop: () => void stop(),
    label: composerLabel,
    placeholder: t("chat_composer_placeholder"),
    attachments,
    onOpenFileDialog: openAttachmentDialog,
    capabilities: toolChoices.capabilities,
    disabledCapabilities: toolChoices.disabledCapabilities,
    onToggleCapability: toolChoices.toggleCapability,
    knowledge: partner.knowledge,
    tools,
    mention,
    modelSelector,
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

  // Generation failed: the error (also announced) and a retry of the same
  // question. Shown in both layouts: a first question that fails before
  // streaming starts puts the view back in the start state.
  const errorNotice = errorText ? (
    <ChatSystemMessage icon={<CircleAlert aria-hidden="true" className="text-ax-error size-4" />}>
      <span className="flex flex-wrap items-center justify-center gap-2">
        <span className="text-ax-error">{errorText}</span>
        {lastQuestion && !busy && (
          <Button
            label={t("chat_retry")}
            size="sm"
            variant="secondary"
            onClick={() => sendQuestion(lastQuestion.text, lastQuestion.files)}
          />
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
            onPickStarter={(prompt) => {
              setInput(prompt);
              startTextareaRef.current?.focus();
            }}
            composer={
              <div ref={startComposerRef} className="flex w-full flex-col gap-3">
                {errorNotice}
                <Composer
                  {...composerProps}
                  variant="start"
                  partnerToken={partnerToken}
                  textareaRef={startTextareaRef}
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

  return (
    <>
      <div className="flex min-h-0 flex-1">
        <ChatLayout
          className="min-w-0 flex-1"
          // WCAG 2.4.11: Tab and focus() scroll the focused element above the
          // docked composer instead of behind it.
          style={{ scrollPaddingBottom: dockHeight + 28 }}
          composer={
            <div ref={dockRef} className="mx-auto w-full max-w-[680px]">
              <Composer {...composerProps} textareaRef={dockTextareaRef} />
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
                <ChatMessage
                  key={message.id}
                  message={message}
                  assistant={assistantIdentity}
                  isStreaming={streaming}
                  showResponseLabel={partner.showResponseLabel ?? false}
                  liveAnswering={liveAnswering}
                  knowledge={partner.knowledge}
                  durations={timings.durations(message.id)}
                  activityExpanded={activity?.messageId === message.id}
                  onActivityToggle={(trigger, request) =>
                    toggleActivity(message.id, trigger, request)
                  }
                  feedback={
                    messageIndex === lastAssistantIndex && sessionId && !streaming
                      ? {
                          value: feedback,
                          pending: feedbackMutation.isPending,
                          onChange: setFeedback
                        }
                      : null
                  }
                />
              );
            })}
            {status === "submitted" && <PendingAnswer assistant={assistantIdentity} />}
            {errorNotice}
          </ChatMessageList>
        </ChatLayout>
        {activity && activityMessage && activityForPanel && (
          <ActivityPanel
            variant={isDesktop ? "side" : "sheet"}
            messageId={activityMessage.id}
            activity={activityForPanel}
            durations={timings.durations(activityMessage.id)}
            sessionId={sessionId}
            tab={activity.tab}
            onTabChange={(tab) => onActivityChange({ ...activity, tab, source: null })}
            focusSource={activity.source}
            onClose={closeActivity}
          />
        )}
      </div>
      {fileInputElement}
    </>
  );
}

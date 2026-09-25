"use client";

import { useChat } from "@ai-sdk/react";
import { Button } from "@astryxdesign/core/Button";
import { ChatLayout, ChatMessageList, ChatSystemMessage } from "@astryxdesign/core/Chat";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode
} from "react";
import { toast } from "sonner";
import { useAppContext } from "@/components/providers/app-context";
import type { Capability } from "@/features/capabilities/capabilities";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessageForCode } from "@/lib/api/errors";
import { createChatTransport, type ChatSendOptions } from "@/lib/chat/transport";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { deriveContextUsage, usePreflight } from "@/lib/chat/use-preflight";
import { deriveActivity } from "./activity";
import { ActivityPanel, type ActivityTab } from "./activity-panel";
import { ActivityTimings } from "./activity-timings";
import {
  chatCapabilities,
  defaultDisabledCapabilities,
  disabledCapabilitiesForRequest
} from "./chat-capabilities";
import { ChatMessage, PendingAnswer, type ActivityRequest } from "./chat-message";
import { Composer } from "./composer";
import { ContextUsageBar } from "./context-usage-bar";
import { historyQueryKey } from "./history-panel";
import {
  ChatMcpServers,
  chatPartnerMcpServers,
  defaultDisabledMcpServerIds,
  mcpConversationOptions,
  pruneDisabledMcpServerIds
} from "./mcp-controls";
import {
  initialDisabledMcpServerIds,
  parseMcpPreferences,
  readMcpPreferencesRaw,
  subscribeMcpPreferences,
  saveMcpServerPreferences
} from "./mcp-preferences";
import { useSessionMutations } from "./session-actions";
import { StartState } from "./start-state";
import { useAttachments } from "./use-attachments";

const NO_MENTION = "__none__";
const AUTO_ACCEPT_TOOLS_STORAGE_KEY = "autoAcceptToolsEnabled";

function autoAcceptToolsPreference(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

/** The current time as ISO 8601 (the timestamp of a question sent now). */
function isoNow(): string {
  return new Date().toISOString();
}

type SentFiles = NonNullable<NonNullable<EneoUIMessage["metadata"]>["files"]>;

/** Which answer's activity is shown, on which tab, and which source to focus. */
export type ActivityState = { messageId: string; tab: ActivityTab; source: number | null };

/** Height of an element, tracked with a ResizeObserver (0 where unsupported). */
function useElementHeight(ref: React.RefObject<HTMLElement | null>) {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setHeight(Math.ceil(entry.contentRect.height));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return height;
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

export function ChatView({
  partner,
  initialSessionId = null,
  initialMessages = [],
  initialFeedback = null,
  onSessionCreated,
  onNewConversation,
  onTitle,
  onStarted,
  modelSelector,
  partnerToken,
  activity,
  onActivityChange
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  initialMessages?: EneoUIMessage[];
  /** The loaded session's feedback (session-level, shown on the latest answer). */
  initialFeedback?: 1 | -1 | null;
  onSessionCreated?: (sessionId: string) => void;
  /** Start a fresh conversation (offered when the context estimate overflows). */
  onNewConversation?: () => void;
  /** The generated title of a new conversation. */
  onTitle?: (title: string) => void;
  /** The first question of a new conversation was sent. */
  onStarted?: () => void;
  /** Interactive model picker shown in the composer (default-assistant only). */
  modelSelector?: ReactNode;
  /** Start state for the personal assistant: the assistant selector inside the composer. */
  partnerToken?: ReactNode;
  activity: ActivityState | null;
  onActivityChange: (next: ActivityState | null) => void;
}) {
  const t = useTranslations();
  const { featureFlags, tenant, user, can } = useAppContext();
  const queryClient = useQueryClient();
  const attachments = useAttachments(partner);
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  // Astryx's shared polite live region (mounted empty, cleared after a moment):
  // only "Svaret är klart", errors and tool approvals go there, never tokens.
  const announce = useAnnounce();
  const [timings] = useState(() => new ActivityTimings());
  useSyncExternalStore(timings.subscribe, timings.getVersion, timings.getVersion);

  const allCapabilities = useMemo(() => chatCapabilities(partner, can), [partner, can]);
  const capabilities = allCapabilities.filter(
    (capability) => capability.purpose !== "web_search" || featureFlags.showWebSearch
  );
  const mcpServers = useMemo(() => chatPartnerMcpServers(partner), [partner]);
  const preferenceIds = useMemo(
    () => [
      ...mcpServers.map((server) => server.id),
      ...allCapabilities.map((capability) => `capability:${capability.purpose}`)
    ],
    [mcpServers, allCapabilities]
  );
  const preferenceContext = useMemo(
    () =>
      partner.type === "default-assistant"
        ? { tenantId: tenant.id, userId: user.id, assistantId: partner.id }
        : null,
    [partner.type, partner.id, tenant.id, user.id]
  );
  const readPreferenceSnapshot = useCallback(
    () => (preferenceContext ? readMcpPreferencesRaw(preferenceContext) : null),
    [preferenceContext]
  );
  const rawPreferences = useSyncExternalStore(
    subscribeMcpPreferences,
    readPreferenceSnapshot,
    () => null
  );
  const savedPreferences = useMemo(() => parseMcpPreferences(rawPreferences), [rawPreferences]);
  const defaultDisabledPreferenceIds = useMemo(
    () => [
      ...defaultDisabledMcpServerIds(partner),
      ...defaultDisabledCapabilities(partner).map((purpose) => `capability:${purpose}`)
    ],
    [partner]
  );
  const resolvedDisabledIds = useMemo(
    () =>
      initialDisabledMcpServerIds({
        availableServerIds: preferenceIds,
        defaultDisabledServerIds: defaultDisabledPreferenceIds,
        preferences: savedPreferences
      }),
    [preferenceIds, defaultDisabledPreferenceIds, savedPreferences]
  );

  const [input, setInput] = useState("");
  const [locallyEditedPreferences, setLocallyEditedPreferences] = useState(false);
  const [localDisabledCapabilities, setLocalDisabledCapabilities] = useState<Set<Capability>>(
    () => new Set(defaultDisabledCapabilities(partner))
  );
  const [autoAcceptTools, setAutoAcceptTools] = useState(autoAcceptToolsPreference);
  const [localDisabledMcpServerIds, setLocalDisabledMcpServerIds] = useState<Set<string>>(
    () => new Set(defaultDisabledMcpServerIds(partner))
  );
  const disabledMcpServerIds = useMemo(
    () =>
      locallyEditedPreferences
        ? localDisabledMcpServerIds
        : new Set(resolvedDisabledIds.filter((id) => !id.startsWith("capability:"))),
    [locallyEditedPreferences, localDisabledMcpServerIds, resolvedDisabledIds]
  );
  const disabledCapabilities = locallyEditedPreferences
    ? localDisabledCapabilities
    : new Set(
        allCapabilities
          .filter((capability) => resolvedDisabledIds.includes(`capability:${capability.purpose}`))
          .map((capability) => capability.purpose)
      );

  function persistToolChoices(mcpDisabled: Set<string>, capabilityDisabled: Set<Capability>) {
    if (!preferenceContext) return;
    saveMcpServerPreferences(
      preferenceContext,
      preferenceIds,
      new Set([
        ...mcpDisabled,
        ...[...capabilityDisabled].map((purpose) => `capability:${purpose}`)
      ])
    );
  }

  function setCapabilityEnabled(purpose: Capability) {
    const next = new Set(disabledCapabilities);
    if (next.has(purpose)) next.delete(purpose);
    else next.add(purpose);
    setLocalDisabledCapabilities(next);
    setLocalDisabledMcpServerIds(disabledMcpServerIds);
    setLocallyEditedPreferences(true);
    persistToolChoices(disabledMcpServerIds, next);
  }

  function setMcpDisabled(next: Set<string>) {
    setLocalDisabledMcpServerIds(next);
    setLocalDisabledCapabilities(disabledCapabilities);
    setLocallyEditedPreferences(true);
    persistToolChoices(next, disabledCapabilities);
  }
  const activeDisabledMcpServerIds = useMemo(
    () => pruneDisabledMcpServerIds(disabledMcpServerIds, mcpServers),
    [disabledMcpServerIds, mcpServers]
  );
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
  const pendingSendRef = useRef<{ text: string } | null>(null);
  // The last question and its files, for "Försök igen" after an error.
  const [lastQuestion, setLastQuestion] = useState<{ text: string; files: SentFiles } | null>(null);
  const isNewSession = useRef(initialSessionId === null);
  const [feedbackValue, setFeedbackValue] = useState<1 | -1 | null>(initialFeedback);
  const { feedback: feedbackMutation } = useSessionMutations(partner);
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

  useEffect(() => {
    try {
      window.localStorage.setItem(
        AUTO_ACCEPT_TOOLS_STORAGE_KEY,
        autoAcceptTools ? "true" : "false"
      );
    } catch {
      // Ignore preference persistence failures.
    }
  }, [autoAcceptTools]);

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
          if (!sessionIdRef.current) {
            sessionIdRef.current = part.data.session_id;
            setSessionId(part.data.session_id);
            onSessionCreated?.(part.data.session_id);
          }
          setLiveAnswering(part.data.answering_assistant ?? null);
        }
        if (part.type === "data-error") {
          streamErrorCodeRef.current = part.data.code ?? null;
          setStreamErrorCode(part.data.code ?? null);
        }
        if (part.type === "data-tool-approval" && part.data.status === "pending") {
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
        announce(
          getErrorMessageForCode(streamErrorCodeRef.current, t) ??
            (failure.message || t("request_failed"))
        );
        const pending = pendingSendRef.current;
        if (!pending || streamStartedRef.current) return;
        setInput((current) => (current.trim() ? current : pending.text));
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
        pendingSendRef.current = null;
        if (isAbort) announce(t("chat_announce_stopped"));
        else if (!isError) announce(t("chat_announce_answer_ready"));
        // Auto-title after the first exchange of a fresh conversation.
        if (isNewSession.current && sessionIdRef.current) {
          isNewSession.current = false;
          try {
            const { data } = await browserApi.POST("/api/v1/conversations/{session_id}/title/", {
              params: { path: { session_id: sessionIdRef.current } }
            });
            if (data?.name) onTitle?.(data.name);
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

  // Focus hand-off: sending from the centred start composer swaps in the
  // docked one; keep keyboard focus in the composer (WCAG 2.4.3).
  const startComposerRef = useRef<HTMLDivElement>(null);
  const dockTextareaRef = useRef<HTMLTextAreaElement>(null);
  const startTextareaRef = useRef<HTMLTextAreaElement>(null);
  const refocusDock = useRef(false);
  const started = messages.length > 0;
  useEffect(() => {
    if (started && refocusDock.current) {
      refocusDock.current = false;
      dockTextareaRef.current?.focus();
    }
  }, [started]);

  /** Sends a question; `resendFiles` repeats a failed question's attachments. */
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
    pendingSendRef.current = { text };
    setLastQuestion({ text, files });
    if (!started) {
      refocusDock.current = Boolean(
        startComposerRef.current?.contains(document.activeElement ?? null)
      );
      onStarted?.();
    }

    const mention =
      partner.type === "group-chat" && mentionId !== NO_MENTION
        ? partner.mentionableAssistants?.find((assistant) => assistant.id === mentionId)
        : undefined;

    // The backend wants exactly ONE of session_id/assistant_id/group_chat_id:
    // continuing a session identifies the partner through the session.
    const continuing = sessionIdRef.current !== null;
    const mcpOptions = mcpConversationOptions({
      servers: mcpServers,
      disabledServerIds: activeDisabledMcpServerIds,
      autoAcceptTools,
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
        disabledCapabilities,
        featureFlags.showWebSearch
      ),
      ...mcpOptions
    };

    timings.markSent();
    void sendMessage({ text, metadata: { files, createdAt: isoNow() } }, { body });
    setInput("");
    attachments.clear();
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
    feedbackMutation.mutate(
      { id: sessionIdRef.current, value },
      {
        onSuccess: () => {
          setFeedbackValue(value);
          toast.success(t("chat_feedback_thanks"));
        }
      }
    );
  };

  const errorText = error
    ? (getErrorMessageForCode(streamErrorCode, t) ?? (error.message || t("request_failed")))
    : null;

  const assistantIdentity = { id: partner.id, name: partner.name, iconId: partner.iconId };
  const mention =
    partner.type === "group-chat" && (partner.mentionableAssistants?.length ?? 0) > 0 ? (
      <Select value={mentionId} onValueChange={setMentionId}>
        <SelectTrigger size="sm" className="h-8 w-40 rounded-full" aria-label={t("mention")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_MENTION}>{t("mentions")}</SelectItem>
          {partner.mentionableAssistants!.map((assistant) => (
            <SelectItem key={assistant.id} value={assistant.id}>
              @{assistant.handle}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    ) : null;

  const tools =
    mcpServers.length > 0 ? (
      <ChatMcpServers
        servers={mcpServers}
        disabledServerIds={activeDisabledMcpServerIds}
        autoAcceptTools={autoAcceptTools}
        onDisabledServerIdsChange={setMcpDisabled}
        onAutoAcceptToolsChange={setAutoAcceptTools}
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
    capabilities,
    disabledCapabilities,
    onToggleCapability: setCapabilityEnabled,
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

  const dockRef = useRef<HTMLDivElement>(null);
  const dockHeight = useElementHeight(dockRef);

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
                          value: feedbackValue,
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

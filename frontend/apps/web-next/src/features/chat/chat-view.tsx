"use client";

import { useChat } from "@ai-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import { Globe, Paperclip, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton
} from "@/components/ai-elements/conversation";
import { Message, MessageContent } from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type AttachmentsContext,
  type PromptInputMessage
} from "@/components/ai-elements/prompt-input";
import { useAppContext } from "@/components/providers/app-context";
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
import { cn } from "@/lib/utils";
import { ComposerAttachments } from "./attachments";
import { ChatMessage } from "./chat-message";
import { ContextUsageBar } from "./context-usage-bar";
import { historyQueryKey } from "./history-panel";
import {
  ChatMcpServers,
  chatPartnerMcpServers,
  defaultDisabledMcpServerIds,
  mcpConversationOptions,
  pruneDisabledMcpServerIds
} from "./mcp-controls";
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

function PersonalAssistantWelcome({
  title,
  description,
  onSelectPrompt
}: {
  title: string;
  description: string;
  onSelectPrompt: (prompt: string) => void;
}) {
  const t = useTranslations();
  const suggestions = [
    {
      label: t("personal_assistant_suggestion_summarize"),
      prompt: t("personal_assistant_prompt_summarize")
    },
    {
      label: t("personal_assistant_suggestion_draft"),
      prompt: t("personal_assistant_prompt_draft")
    },
    {
      label: t("personal_assistant_suggestion_plan"),
      prompt: t("personal_assistant_prompt_plan")
    }
  ];

  return (
    <ConversationEmptyState className="px-4 py-10">
      <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-6">
        <div
          aria-hidden="true"
          className="bg-card relative grid size-16 place-items-center rounded-2xl border shadow-sm"
        >
          <div className="absolute inset-1 rounded-[0.875rem] bg-[linear-gradient(135deg,color-mix(in_oklab,var(--primary)_18%,transparent),color-mix(in_oklab,var(--chart-2)_14%,transparent),color-mix(in_oklab,var(--chart-5)_14%,transparent))]" />
          <div className="bg-background/85 relative grid size-11 place-items-center rounded-xl shadow-inner backdrop-blur">
            <Sparkles className="text-primary size-5" />
          </div>
        </div>

        <div className="space-y-3 text-center">
          <p className="text-primary text-xs font-semibold">{t("personal_assistant_eyebrow")}</p>
          <h2 className="text-foreground text-3xl font-semibold sm:text-4xl">{title}</h2>
          <p className="text-muted-foreground mx-auto max-w-xl text-base leading-7">
            {description}
          </p>
        </div>

        <div className="grid w-full gap-2 sm:grid-cols-3">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion.label}
              type="button"
              className="group bg-card hover:border-primary/40 hover:bg-accent focus-visible:border-ring focus-visible:ring-ring/50 flex min-h-16 items-center gap-3 rounded-lg border px-3 py-3 text-left text-sm font-medium shadow-sm transition-colors focus-visible:ring-[3px]"
              onClick={() => onSelectPrompt(suggestion.prompt)}
            >
              <span className="bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground grid size-8 shrink-0 place-items-center rounded-md transition-colors">
                <Sparkles className="size-4" />
              </span>
              <span>{suggestion.label}</span>
            </button>
          ))}
        </div>
      </div>
    </ConversationEmptyState>
  );
}

export function ChatView({
  partner,
  initialSessionId = null,
  initialMessages = [],
  onSessionCreated,
  onNewConversation,
  modelSelector
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  initialMessages?: EneoUIMessage[];
  onSessionCreated?: (sessionId: string) => void;
  /** Start a fresh conversation (offered when the context estimate overflows). */
  onNewConversation?: () => void;
  /** Interactive model picker shown in the composer (default-assistant only). */
  modelSelector?: ReactNode;
}) {
  const t = useTranslations();
  const { featureFlags, user } = useAppContext();
  const queryClient = useQueryClient();
  const attachments = useAttachments(partner);
  const canUseWebSearch = featureFlags.showWebSearch && partner.type === "default-assistant";
  const mcpServers = useMemo(() => chatPartnerMcpServers(partner), [partner]);

  const [input, setInput] = useState("");
  const [streamErrorCode, setStreamErrorCode] = useState<number | null>(null);
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [autoAcceptTools, setAutoAcceptTools] = useState(autoAcceptToolsPreference);
  const [disabledMcpServerIds, setDisabledMcpServerIds] = useState<Set<string>>(
    () => new Set(defaultDisabledMcpServerIds(partner))
  );
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
  const streamStartedRef = useRef(false);
  const pendingSendRef = useRef<{ text: string } | null>(null);
  const isNewSession = useRef(initialSessionId === null);
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
          setStreamErrorCode(part.data.code ?? null);
        }
        if (part.type === "data-token-usage") {
          setLockedTokens({
            input: part.data.prompt_tokens ?? 0,
            output: part.data.completion_tokens ?? 0
          });
          const turnTokens = part.data.turn_tokens ?? 0;
          if (turnTokens > 0) {
            setCumulative((current) => ({
              tokens: current.tokens + turnTokens,
              turns: current.turns + 1
            }));
          }
        }
      },
      onError: () => {
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
      onFinish: async () => {
        pendingSendRef.current = null;
        // Auto-title after the first exchange of a fresh conversation.
        if (isNewSession.current && sessionIdRef.current) {
          isNewSession.current = false;
          try {
            await browserApi.POST("/api/v1/conversations/{session_id}/title/", {
              params: { path: { session_id: sessionIdRef.current } }
            });
          } catch {
            // Title generation is a nicety; ignore failures.
          }
        }
        queryClient.invalidateQueries({ queryKey: historyQueryKey(partner) });
      }
    });

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

  const busy = status === "submitted" || status === "streaming";
  const openAttachmentDialog = useCallback(() => {
    fileInput.current?.click();
  }, []);
  const promptAttachments = useMemo<AttachmentsContext>(
    () => ({
      add: (files) => {
        void attachments.addFiles(Array.from(files));
      },
      clear: attachments.clear,
      fileInputRef: fileInput,
      files: attachments.attachments.map((attachment) => ({
        filename: attachment.name,
        id: attachment.key,
        mediaType: attachment.mimetype,
        type: "file" as const,
        url: attachment.previewUrl ?? ""
      })),
      openFileDialog: openAttachmentDialog,
      remove: attachments.removeAttachment
    }),
    [attachments, openAttachmentDialog]
  );

  function submit(message: PromptInputMessage) {
    const text = message.text?.trim();
    if (!text || busy || attachments.uploading || usage.willExceedContext) return;
    clearError();
    setStreamErrorCode(null);
    streamStartedRef.current = false;
    pendingSendRef.current = { text };

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
      files: attachments.fileIds.map((id) => ({ id })),
      tools: mention ? { assistants: [{ id: mention.id, handle: mention.handle }] } : null,
      use_web_search: canUseWebSearch && useWebSearch ? true : undefined,
      ...mcpOptions
    };

    void sendMessage({ text, files: message.files }, { body });
    setInput("");
    attachments.clear();
    setMentionId(NO_MENTION);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Conversation className="min-h-0 flex-1">
        {/* Same column width as the prompt input: responses span the chat
            column (readable line length), not the full page. */}
        <ConversationContent className="mx-auto w-full max-w-3xl gap-6 px-0 py-6">
          {messages.length === 0 &&
            (partner.type === "default-assistant" ? (
              <PersonalAssistantWelcome
                title={t("hi_firstname", {
                  firstName: user.username || user.email.split("@")[0] || user.email
                })}
                description={t("personal_assistant_welcome")}
                onSelectPrompt={setInput}
              />
            ) : (
              <ConversationEmptyState title={partner.name} description={t("ask_a_question")} />
            ))}
          {messages.map((message, messageIndex) => (
            <ChatMessage
              key={message.id}
              message={message}
              sessionId={sessionId}
              isStreaming={busy && messageIndex === messages.length - 1}
              showResponseLabel={partner.showResponseLabel ?? false}
              liveAnswering={liveAnswering}
            />
          ))}
          {status === "submitted" && (
            <Message from="assistant">
              <MessageContent>
                <div className="flex h-5 items-center gap-1" aria-live="polite">
                  <span className="bg-muted-foreground size-1.5 animate-pulse rounded-full" />
                  <span className="bg-muted-foreground size-1.5 animate-pulse rounded-full [animation-delay:200ms]" />
                  <span className="bg-muted-foreground size-1.5 animate-pulse rounded-full [animation-delay:400ms]" />
                  <span className="sr-only">{t("assistant_is_thinking")}</span>
                </div>
              </MessageContent>
            </Message>
          )}
          {error && (
            <p className="text-destructive text-sm">
              {getErrorMessageForCode(streamErrorCode, t) ?? (error.message || t("request_failed"))}
            </p>
          )}
        </ConversationContent>
        <ConversationScrollButton aria-label={t("scroll_to_bottom")} />
      </Conversation>

      <div className="mx-auto w-full max-w-3xl pb-4">
        <ComposerAttachments attachments={attachments} />
        <ContextUsageBar
          usage={usage}
          modelName={partner.completionModel?.name}
          cumulativeTokens={cumulative.tokens}
          turnCount={cumulative.turns}
          onNewConversation={onNewConversation}
        />
        <PromptInput
          accept={attachments.acceptString}
          attachments={promptAttachments}
          onSubmit={submit}
        >
          <PromptInputBody>
            <PromptInputTextarea
              value={input}
              placeholder={t("ask_a_question")}
              onChange={(event) => setInput(event.currentTarget.value)}
            />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              {modelSelector}
              {attachments.maxFiles !== 0 && (
                <PromptInputButton
                  variant="outline"
                  disabled={!attachments.canAddMore}
                  onClick={openAttachmentDialog}
                  aria-label={t("attachments")}
                >
                  <Paperclip className="text-muted-foreground size-4" /> {t("attachments")}
                </PromptInputButton>
              )}
              {canUseWebSearch && (
                <PromptInputButton
                  variant={useWebSearch ? "default" : "outline"}
                  onClick={() => setUseWebSearch((value) => !value)}
                  aria-label={t("web_search")}
                >
                  <Globe className={cn("size-4", !useWebSearch && "text-muted-foreground")} />{" "}
                  {t("web_search")}
                </PromptInputButton>
              )}
              {mcpServers.length > 0 && (
                <ChatMcpServers
                  servers={mcpServers}
                  disabledServerIds={activeDisabledMcpServerIds}
                  autoAcceptTools={autoAcceptTools}
                  onDisabledServerIdsChange={setDisabledMcpServerIds}
                  onAutoAcceptToolsChange={setAutoAcceptTools}
                />
              )}
              {partner.type === "group-chat" &&
                (partner.mentionableAssistants?.length ?? 0) > 0 && (
                  <Select value={mentionId} onValueChange={setMentionId}>
                    <SelectTrigger size="sm" className="h-8 w-40" aria-label={t("mention")}>
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
                )}
            </PromptInputTools>
            <PromptInputSubmit
              status={status}
              disabled={
                busy ? false : !input.trim() || attachments.uploading || usage.willExceedContext
              }
              onStop={stop}
            />
          </PromptInputFooter>
        </PromptInput>
        <p className="text-muted-foreground mt-2.5 text-center text-[11.5px]">
          {t("chat_sovereignty_hint")}
        </p>
        {attachments.maxFiles !== 0 && (
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
        )}
      </div>
    </div>
  );
}

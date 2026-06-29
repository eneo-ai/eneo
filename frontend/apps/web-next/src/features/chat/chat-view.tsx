"use client";

import { useChat } from "@ai-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, Globe, Paperclip } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage
} from "@/components/ai-elements/prompt-input";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { useAppContext } from "@/components/providers/app-context";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { createChatTransport, type ChatSendOptions } from "@/lib/chat/transport";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { deriveContextUsage, usePreflight } from "@/lib/chat/use-preflight";
import { cn } from "@/lib/utils";
import { ComposerAttachments } from "./attachments";
import { ContextUsageBar } from "./context-usage-bar";
import { historyQueryKey } from "./history-panel";
import {
  GeneratedFile,
  MessageFiles,
  MessageSources,
  MessageTool,
  ToolApprovalCard
} from "./message-parts";
import { useAttachments } from "./use-attachments";

const NO_MENTION = "__none__";

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
  const { user } = useAppContext();
  const queryClient = useQueryClient();
  const attachments = useAttachments(partner);

  const [input, setInput] = useState("");
  const [useWebSearch, setUseWebSearch] = useState(false);
  const [mentionId, setMentionId] = useState<string>(NO_MENTION);
  const fileInput = useRef<HTMLInputElement>(null);
  // Ref for event-time reads (send body, onFinish); state for render-time
  // consumers (preflight). Both are set together when data-session arrives.
  const sessionIdRef = useRef<string | null>(initialSessionId);
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [liveAnswering, setLiveAnswering] = useState<{ id: string; handle: string } | null>(null);
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

  const transport = useMemo(() => createChatTransport(), []);
  const { messages, sendMessage, status, stop, error } = useChat<EneoUIMessage>({
    transport,
    messages: initialMessages,
    // Backend forwards one SSE delta per provider token; coalesce UI updates to
    // ~20/s so fast streams don't re-parse markdown on every token (the Svelte
    // app frame-buffered for the same reason). Tune up for snappier, down for calmer.
    experimental_throttle: 50,
    onData: (part) => {
      if (part.type === "data-session") {
        if (!sessionIdRef.current) {
          sessionIdRef.current = part.data.session_id;
          setSessionId(part.data.session_id);
          onSessionCreated?.(part.data.session_id);
        }
        setLiveAnswering(part.data.answering_assistant ?? null);
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
    onFinish: async () => {
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

  // Translated reasoning header: shimmering while thinking, elapsed once done.
  const thinkingMessage = (isStreaming: boolean, duration?: number): ReactNode => {
    if (isStreaming || duration === 0) {
      return <Shimmer duration={1}>{t("chat_reasoning_thinking")}</Shimmer>;
    }
    if (duration === undefined) return <span>{t("chat_reasoning_thought")}</span>;
    return <span>{t("chat_reasoning_thought_for", { seconds: duration })}</span>;
  };

  function submit(message: PromptInputMessage) {
    const text = message.text?.trim();
    if (!text || busy || attachments.uploading || usage.willExceedContext) return;

    const mention =
      partner.type === "group-chat" && mentionId !== NO_MENTION
        ? partner.mentionableAssistants?.find((assistant) => assistant.id === mentionId)
        : undefined;

    // The backend wants exactly ONE of session_id/assistant_id/group_chat_id:
    // continuing a session identifies the partner through the session.
    const continuing = sessionIdRef.current !== null;
    const body: ChatSendOptions = {
      session_id: sessionIdRef.current,
      assistant_id: continuing || partner.type === "group-chat" ? null : partner.id,
      group_chat_id: !continuing && partner.type === "group-chat" ? partner.id : null,
      files: attachments.fileIds.map((id) => ({ id })),
      tools: mention ? { assistants: [{ id: mention.id, handle: mention.handle }] } : null,
      use_web_search: useWebSearch || undefined,
      require_tool_approval: true
    };

    sendMessage({ text }, { body });
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
              <ConversationEmptyState
                icon={<Bot className="size-10" />}
                title={t("hi_firstname", {
                  firstName: user.username || user.email.split("@")[0] || user.email
                })}
                description={t("personal_assistant_welcome")}
              />
            ) : (
              <ConversationEmptyState title={partner.name} description={t("ask_a_question")} />
            ))}
          {messages.map((message, messageIndex) => {
            const isAssistant = message.role === "assistant";
            const isStreamingThis = busy && messageIndex === messages.length - 1;
            const textContent = message.parts
              .filter((part) => part.type === "text")
              .map((part) => part.text)
              .join("\n\n");
            const answering =
              message.metadata?.answeringAssistant ?? (isStreamingThis ? liveAnswering : null);
            return (
              <Message key={message.id} from={message.role}>
                <MessageContent>
                  {isAssistant && partner.showResponseLabel && answering && (
                    <span className="bg-secondary text-secondary-foreground w-fit rounded-full px-2 py-0.5 text-xs font-medium">
                      @{answering.handle}
                    </span>
                  )}
                  {message.parts.map((part, index) => {
                    if (part.type === "reasoning") {
                      return (
                        <Reasoning key={index} isStreaming={part.state === "streaming"}>
                          <ReasoningTrigger getThinkingMessage={thinkingMessage} />
                          <ReasoningContent>{part.text}</ReasoningContent>
                        </Reasoning>
                      );
                    }
                    if (part.type === "text") {
                      return isAssistant ? (
                        <MessageResponse key={index}>{part.text}</MessageResponse>
                      ) : (
                        <span key={index} className="whitespace-pre-wrap">
                          {part.text}
                        </span>
                      );
                    }
                    if (part.type === "dynamic-tool") {
                      return <MessageTool key={index} part={part} />;
                    }
                    if (part.type === "data-tool-approval") {
                      return <ToolApprovalCard key={part.id ?? index} data={part.data} />;
                    }
                    if (part.type === "file") {
                      return part.mediaType.startsWith("image/") ? (
                        // eslint-disable-next-line @next/next/no-img-element -- signed cross-origin URL
                        <img
                          key={index}
                          src={part.url}
                          alt={part.filename ?? "generated"}
                          className="max-h-96 rounded-lg border"
                        />
                      ) : null;
                    }
                    return null;
                  })}
                  {!isAssistant && (message.metadata?.files?.length ?? 0) > 0 && (
                    <MessageFiles files={message.metadata!.files!} />
                  )}
                  {isAssistant &&
                    message.metadata?.generatedFiles?.map((file) => (
                      <GeneratedFile key={file.id} file={file} />
                    ))}
                </MessageContent>
                {isAssistant && <MessageSources parts={message.parts} />}
                {isAssistant && textContent && !isStreamingThis && (
                  <MessageActions className="-ml-1.5">
                    <MessageAction
                      tooltip={t("copy")}
                      onClick={() => {
                        navigator.clipboard.writeText(textContent);
                        toast.success(t("copied"));
                      }}
                    >
                      <Copy className="size-3.5" />
                    </MessageAction>
                  </MessageActions>
                )}
              </Message>
            );
          })}
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
            <p className="text-destructive text-sm">{error.message || t("request_failed")}</p>
          )}
        </ConversationContent>
        <ConversationScrollButton />
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
        <PromptInput onSubmit={submit}>
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
              <PromptInputButton
                variant="outline"
                onClick={() => fileInput.current?.click()}
                aria-label={t("attachments")}
              >
                <Paperclip className="text-muted-foreground size-4" /> {t("attachments")}
              </PromptInputButton>
              {partner.type === "default-assistant" && (
                <PromptInputButton
                  variant={useWebSearch ? "default" : "outline"}
                  onClick={() => setUseWebSearch((value) => !value)}
                  aria-label={t("web_search")}
                >
                  <Globe className={cn("size-4", !useWebSearch && "text-muted-foreground")} />{" "}
                  {t("web_search")}
                </PromptInputButton>
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
      </div>
    </div>
  );
}

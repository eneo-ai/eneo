"use client";

import { useChat } from "@ai-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import { Globe, Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton
} from "@/components/ai-elements/conversation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { Context } from "@/components/ai-elements/context";
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
import { Badge } from "@/components/ui/badge";
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
import { historyQueryKey } from "./history-panel";
import { GeneratedFile, MessageSources, MessageTool, ToolApprovalCard } from "./message-parts";
import { useAttachments } from "./use-attachments";

const NO_MENTION = "__none__";

export function ChatView({
  partner,
  initialSessionId = null,
  initialMessages = [],
  onSessionCreated
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  initialMessages?: EneoUIMessage[];
  onSessionCreated?: (sessionId: string) => void;
}) {
  const t = useTranslations();
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
  const isNewSession = useRef(initialSessionId === null);
  const [lockedTokens, setLockedTokens] = useState(() => {
    const last = initialMessages[initialMessages.length - 1];
    return {
      input: last?.metadata?.tokens?.prompt ?? 0,
      output: last?.metadata?.tokens?.completion ?? 0
    };
  });

  const transport = useMemo(() => createChatTransport(), []);
  const { messages, sendMessage, status, stop, error } = useChat<EneoUIMessage>({
    transport,
    messages: initialMessages,
    onData: (part) => {
      if (part.type === "data-session") {
        if (!sessionIdRef.current) {
          sessionIdRef.current = part.data.session_id;
          setSessionId(part.data.session_id);
          onSessionCreated?.(part.data.session_id);
        }
      }
      if (part.type === "data-token-usage") {
        setLockedTokens({
          input: part.data.prompt_tokens ?? 0,
          output: part.data.completion_tokens ?? 0
        });
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
        <ConversationContent className="mx-auto w-full max-w-3xl px-0">
          {messages.length === 0 && (
            <ConversationEmptyState title={partner.name} description={t("ask_a_question")} />
          )}
          {messages.map((message) => (
            <Message
              key={message.id}
              from={message.role}
              className={message.role === "assistant" ? "max-w-full" : undefined}
            >
              {/* Assistant content takes the full row so tool/approval boxes
                  keep a stable width while streaming; user keeps the bubble. */}
              <MessageContent className={message.role === "assistant" ? "w-full" : undefined}>
                {message.role === "assistant" && <MessageSources parts={message.parts} />}
                {message.parts.map((part, index) => {
                  if (part.type === "text") {
                    return message.role === "assistant" ? (
                      <MessageResponse key={index}>{part.text}</MessageResponse>
                    ) : (
                      <span key={index}>{part.text}</span>
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
                {message.role === "user" && (message.metadata?.files?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {message.metadata!.files!.map((file) => (
                      <Badge key={file.id} variant="secondary">
                        <Paperclip className="size-3" /> {file.name}
                      </Badge>
                    ))}
                  </div>
                )}
                {message.role === "assistant" &&
                  message.metadata?.generatedFiles?.map((file) => (
                    <GeneratedFile key={file.id} file={file} />
                  ))}
              </MessageContent>
            </Message>
          ))}
          {error && (
            <p className="text-destructive text-sm">{error.message || t("request_failed")}</p>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="mx-auto w-full max-w-3xl pb-4">
        {attachments.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1 pb-2">
            {attachments.attachments.map((attachment) => (
              <Badge key={attachment.key} variant={attachment.uploading ? "outline" : "secondary"}>
                <Paperclip className="size-3" /> {attachment.name}
                <button
                  type="button"
                  aria-label={t("remove")}
                  onClick={() => attachments.removeAttachment(attachment.key)}
                >
                  <X className="size-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
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
              <PromptInputButton
                onClick={() => fileInput.current?.click()}
                aria-label={t("attachments")}
              >
                <Paperclip className="size-4" />
              </PromptInputButton>
              {partner.type === "default-assistant" && (
                <PromptInputButton
                  variant={useWebSearch ? "default" : "ghost"}
                  onClick={() => setUseWebSearch((value) => !value)}
                  aria-label={t("web_search")}
                >
                  <Globe className="size-4" />
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
              {usage.contextLimit > 0 && (
                <Context
                  usedTokens={usage.usedTokens}
                  maxTokens={usage.contextLimit}
                  modelId={partner.completionModel?.name}
                />
              )}
              {usage.willExceedContext && <Badge variant="destructive">{t("context_usage")}</Badge>}
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

"use client";

import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  CitationSourcesProvider,
  citationComponents,
  remarkCitations
} from "@/components/ai-elements/citation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse
} from "@/components/ai-elements/message";
import { useAppContext } from "@/components/providers/app-context";
import { resolveInrefs, trimPartialInref } from "@/lib/chat/inref";
import type { EneoUIMessage } from "@/lib/chat/types";

import { ActivityTimeline } from "./activity-timeline";
import { copyAssistantAnswer, getPreferredAssistantCopyFormat } from "./copy-assistant-answer";
import {
  GeneratedFile,
  McpImageStrip,
  MessageFilePart,
  MessageFiles,
  MessageSources,
  answeringAssistantFromParts,
  mcpReferencesFromParts,
  mergeSources,
  ToolApprovalCard
} from "./message-parts";

/**
 * Renders one conversation message: the activity timeline (reasoning + tool
 * calls), the answer markdown, attachments/generated files, sources, and the
 * copy action. Shared by ChatView and the design mock page so the two never
 * drift — ChatView owns the data/streaming, this owns the presentation.
 */
export function ChatMessage({
  message,
  sessionId = null,
  isStreaming = false,
  showResponseLabel = false,
  liveAnswering = null
}: {
  message: EneoUIMessage;
  sessionId?: string | null;
  isStreaming?: boolean;
  showResponseLabel?: boolean;
  liveAnswering?: { id: string; handle: string } | null;
}) {
  const t = useTranslations();
  const { settings } = useAppContext();
  const isAssistant = message.role === "assistant";
  const copyFormat = getPreferredAssistantCopyFormat(settings);
  const textContent = message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n\n");
  const answering =
    message.metadata?.answeringAssistant ??
    answeringAssistantFromParts(message.parts) ??
    (isStreaming ? liveAnswering : null);
  const mcpReferences = mcpReferencesFromParts(message.parts, message.metadata?.mcpToolReferences);
  const sources = mergeSources(message.parts, message.metadata?.webSearchReferences, mcpReferences);
  const sourceIds = sources.map((source) => source.sourceId);

  return (
    <Message from={message.role}>
      <MessageContent>
        {isAssistant && showResponseLabel && answering && (
          <span className="bg-secondary text-secondary-foreground w-fit rounded-full px-2 py-0.5 text-xs font-medium">
            @{answering.handle}
          </span>
        )}
        {isAssistant && (
          <ActivityTimeline parts={message.parts} isStreaming={isStreaming} sessionId={sessionId} />
        )}
        {message.parts.map((part, index) => {
          // Reasoning and tool calls are grouped into ActivityTimeline above.
          if (part.type === "reasoning" || part.type === "dynamic-tool") {
            return null;
          }
          if (part.type === "text") {
            return isAssistant ? (
              <CitationSourcesProvider key={index} value={sources}>
                <MessageResponse
                  className="font-voice text-[15px] leading-[1.7]"
                  remarkPlugins={[remarkCitations(sources.length, message.id)]}
                  components={citationComponents}
                >
                  {resolveInrefs(isStreaming ? trimPartialInref(part.text) : part.text, sourceIds)}
                </MessageResponse>
              </CitationSourcesProvider>
            ) : (
              <span key={index} className="whitespace-pre-wrap">
                {part.text}
              </span>
            );
          }
          if (part.type === "data-tool-approval") {
            return <ToolApprovalCard key={part.id ?? index} data={part.data} />;
          }
          if (part.type === "file") {
            return <MessageFilePart key={index} part={part} />;
          }
          return null;
        })}
        {!isAssistant && (message.metadata?.files?.length ?? 0) > 0 && (
          <MessageFiles files={message.metadata!.files!} />
        )}
        {isAssistant && <McpImageStrip references={mcpReferences} />}
        {isAssistant &&
          message.metadata?.generatedFiles?.map((file) => (
            <GeneratedFile key={file.id} file={file} />
          ))}
      </MessageContent>
      {isAssistant && <MessageSources sources={sources} idPrefix={message.id} />}
      {isAssistant && textContent && !isStreaming && (
        <MessageActions className="-ml-1.5">
          <MessageAction
            tooltip={copyFormat === "richtext" ? t("copy_as_richtext") : t("copy_as_markdown")}
            onClick={async () => {
              await copyAssistantAnswer(textContent, copyFormat);
              toast.success(t("copied"));
            }}
          >
            <Copy className="size-3.5" />
          </MessageAction>
        </MessageActions>
      )}
    </Message>
  );
}

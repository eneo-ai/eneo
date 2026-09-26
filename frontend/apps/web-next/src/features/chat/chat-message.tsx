"use client";

import { ChatMessage as AxChatMessage, ChatMessageBubble } from "@astryxdesign/core/Chat";
import { useClipboard } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { Copy, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef } from "react";

import {
  CitationSourcesProvider,
  citationComponents,
  useCitationRemarkPlugins
} from "@/components/ai-elements/citation";
import { MessageResponse } from "@/components/ai-elements/message";
import { iconUrl } from "@/components/composites/icon-field";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { resolveInrefs, trimPartialInref } from "@/lib/chat/inref";
import type { AnswerRating, EneoUIMessage, KnowledgeOrigin } from "@/lib/chat/types";
import { toast } from "@/lib/toast";

import { deriveActivity, modelName } from "./activity";
import type { ActivityTab } from "./activity-panel";
import { ActivityPill } from "./activity-pill";
import type { TurnDurations } from "./activity-timings";
import {
  assistantClipboardContent,
  canCopyRichText,
  copyRichText,
  getPreferredAssistantCopyFormat,
  type AssistantCopyFormat
} from "./copy-assistant-answer";
import {
  answeringAssistantFromParts,
  GeneratedFile,
  McpImageStrip,
  mcpReferencesFromParts,
  MessageFilePart,
  MessageFiles,
  ToolApprovalCard
} from "./message-parts";

/** Who answers: the chat partner's name and tile. */
export type AssistantIdentity = { id: string; name: string; iconId?: string | null };

/** An answer's rating and how to change it (null clears it). */
export type AnswerFeedback = {
  value: AnswerRating;
  onChange: (value: AnswerRating) => void;
};

const RATING_VALUE = { good: 1, bad: -1 } as const;

export type ActivityRequest = { tab?: ActivityTab; source?: number };

const NO_KNOWLEDGE: KnowledgeOrigin[] = [];

function messageText(message: EneoUIMessage): string {
  return message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n\n");
}

/** The user's question: a filled bubble on the right, attachments as file tokens below. */
function UserMessage({ message }: { message: EneoUIMessage }) {
  const t = useTranslations();
  const text = messageText(message);
  const files = message.metadata?.files ?? [];
  const fileParts = message.parts.filter(
    (part): part is Extract<EneoUIMessage["parts"][number], { type: "file" }> =>
      part.type === "file"
  );
  return (
    <AxChatMessage
      sender="user"
      name={<span className="sr-only">{t("chat_your_message")}</span>}
      className="w-full"
    >
      {text && (
        <ChatMessageBubble className="bg-ax-muted rounded-ax-page max-w-[min(100%,32.5rem)] px-[15px] py-2.5 text-[14.5px] leading-normal whitespace-pre-wrap">
          {text}
        </ChatMessageBubble>
      )}
      {files.length > 0 && <MessageFiles files={files} />}
      {fileParts.length > 0 && (
        <div className="flex flex-wrap justify-end gap-1.5">
          {fileParts.map((part, index) => (
            <MessageFilePart key={index} part={part} />
          ))}
        </div>
      )}
    </AxChatMessage>
  );
}

/**
 * "Assistenten tänker…" before any step or text has streamed in. Not a live
 * region: the view announces the finished answer instead (the spinner's own
 * status role is hidden).
 */
function ThinkingStatus() {
  const t = useTranslations();
  return (
    <span className="bg-ax-accent-muted text-ax-text-accent inline-flex min-h-[30px] items-center gap-1.5 self-start rounded-full ps-2 pe-3 text-[12.5px] font-semibold">
      <span aria-hidden="true" className="flex">
        <Spinner size="md" shade="inherit" />
      </span>
      {t("chat_assistant_thinking")}
    </span>
  );
}

const SKELETON_LINES = ["100%", "88%", "56%"];

/** Placeholder lines where the answer will stream in (decorative). */
function AnswerSkeleton() {
  return (
    <div aria-hidden="true" className="flex w-full flex-col gap-[9px] pt-0.5">
      {SKELETON_LINES.map((width, index) => (
        <Skeleton key={width} index={index} width={width} height={11} radius={1} />
      ))}
    </div>
  );
}

/** Header row of an answer: tile, assistant name (the message's accessible name) and model. */
function AssistantName({
  assistant,
  model,
  handle
}: {
  assistant: AssistantIdentity;
  model: string | null;
  handle: string | null;
}) {
  const t = useTranslations();
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
      <EntityAvatar
        id={assistant.id}
        name={assistant.name}
        src={iconUrl(assistant.iconId)}
        size="sm"
      />
      <span className="text-ax-text text-[13.5px] leading-snug font-semibold">
        <span className="sr-only">{t("chat_answer_from")} </span>
        {assistant.name}
      </span>
      {handle && (
        <span className="bg-ax-muted text-ax-text-secondary rounded-full px-2 py-0.5 text-xs font-medium">
          @{handle}
        </span>
      )}
      {model && (
        <span className="text-ax-text-secondary text-[12.5px] leading-snug font-normal">
          {model}
        </span>
      )}
    </span>
  );
}

function AnswerActions({
  text,
  hasActivity,
  onShowActivity,
  feedback,
  timestamp
}: {
  text: string;
  hasActivity: boolean;
  onShowActivity: (trigger: HTMLElement) => void;
  feedback: AnswerFeedback | null;
  timestamp: string | null;
}) {
  const t = useTranslations();
  const { settings } = useAppContext();
  const preferred = getPreferredAssistantCopyFormat(settings);
  const moreRef = useRef<HTMLDivElement>(null);
  const { copy: copyText } = useClipboard();

  // Confirmed with a toast (seen and announced) for both formats: a rich-text
  // copy does not go through useClipboard, so it has no copied state to show.
  const copy = useCallback(
    async (format: AssistantCopyFormat) => {
      const { text: plainText, html } = assistantClipboardContent(text, format);
      const copied =
        html !== null && canCopyRichText()
          ? await copyRichText({ text: plainText, html })
          : await copyText(plainText);
      if (copied) toast.success(t("copied"));
      else toast.error(t("chat_copy_failed"));
    },
    [copyText, t, text]
  );

  const iconClass = "pointer-coarse:size-11";
  const moreItems = [
    { label: t("copy_as_markdown"), onClick: () => void copy("markdown") },
    { label: t("copy_as_richtext"), onClick: () => void copy("richtext") },
    ...(hasActivity
      ? [
          {
            label: t("chat_show_activity"),
            onClick: () => {
              const trigger = moreRef.current?.querySelector("button");
              if (trigger) onShowActivity(trigger);
            }
          }
        ]
      : [])
  ];

  return (
    <div className="text-ax-text-secondary -ms-1.5 flex w-full items-center gap-0.5">
      <IconButton
        label={t("chat_copy_answer")}
        tooltip={preferred === "richtext" ? t("copy_as_richtext") : t("copy_as_markdown")}
        icon={<Copy className="size-4" />}
        variant="ghost"
        size="sm"
        className={iconClass}
        onClick={() => void copy(preferred)}
      />
      {feedback && (
        // ToggleButton takes no className: size its buttons for touch from here.
        <span className="contents pointer-coarse:[&_button]:size-11">
          {/* One choice at a time; pressing the chosen thumb again clears it.
              A filled thumb marks the choice besides the pressed background. */}
          <ToggleButtonGroup
            label={t("feedback_group_label")}
            size="sm"
            value={feedback.value === 1 ? "good" : feedback.value === -1 ? "bad" : null}
            onChange={(next) =>
              feedback.onChange(next === "good" || next === "bad" ? RATING_VALUE[next] : null)
            }
          >
            <ToggleButton
              value="good"
              label={t("chat_feedback_good")}
              isIconOnly
              icon={<ThumbsUp className="size-4" />}
              pressedIcon={<ThumbsUp className="size-4" fill="currentColor" />}
            />
            <ToggleButton
              value="bad"
              label={t("chat_feedback_bad")}
              isIconOnly
              icon={<ThumbsDown className="size-4" />}
              pressedIcon={<ThumbsDown className="size-4" fill="currentColor" />}
            />
          </ToggleButtonGroup>
        </span>
      )}
      <div ref={moreRef} className="contents">
        <MoreMenu
          label={t("chat_more_actions")}
          items={moreItems}
          size="sm"
          placement="below"
          className={iconClass}
        />
      </div>
      <span className="flex-1" />
      {timestamp && <Timestamp value={timestamp} format="date_time" />}
    </div>
  );
}

function AssistantMessage({
  message,
  assistant,
  isStreaming,
  showResponseLabel,
  liveAnswering,
  knowledge,
  durations,
  activityExpanded,
  onActivityToggle,
  feedback
}: {
  message: EneoUIMessage;
  assistant: AssistantIdentity;
  isStreaming: boolean;
  showResponseLabel: boolean;
  liveAnswering: { id: string; handle: string } | null;
  knowledge: KnowledgeOrigin[];
  durations: TurnDurations | null;
  activityExpanded: boolean;
  onActivityToggle?: (trigger: HTMLElement, request?: ActivityRequest) => void;
  feedback: AnswerFeedback | null;
}) {
  const text = messageText(message);
  const answering =
    message.metadata?.answeringAssistant ??
    answeringAssistantFromParts(message.parts) ??
    (isStreaming ? liveAnswering : null);
  const mcpReferences = mcpReferencesFromParts(message.parts, message.metadata?.mcpToolReferences);
  const activity = useMemo(
    () =>
      deriveActivity(message, {
        streaming: isStreaming,
        knowledge,
        tokens: durations?.tokens ?? null
      }),
    [message, isStreaming, knowledge, durations?.tokens]
  );
  const sources = activity.sources;
  const sourceIds = sources.map((source) => source.sourceId);
  const remarkPlugins = useCitationRemarkPlugins(sources.length, message.id);
  const openSource = useCallback(
    (index: number, trigger: HTMLElement) =>
      onActivityToggle?.(trigger, { tab: "sources", source: index }),
    [onActivityToggle]
  );
  const textParts = message.parts.filter((part) => part.type === "text");
  const hasText = text.trim().length > 0;

  return (
    <AxChatMessage
      sender="assistant"
      name={
        <AssistantName
          assistant={assistant}
          model={modelName(message)}
          handle={showResponseLabel && answering ? answering.handle : null}
        />
      }
      className="w-full"
    >
      <div className="flex w-full min-w-0 flex-col gap-3 pt-1">
        {activity.hasActivity && (
          <ActivityPill
            activity={activity}
            durations={durations}
            expanded={activityExpanded}
            onToggle={(trigger) => onActivityToggle?.(trigger)}
          />
        )}
        {isStreaming && !hasText && !activity.hasActivity && <ThinkingStatus />}
        {isStreaming && !hasText && <AnswerSkeleton />}
        {message.parts.map((part, index) => {
          if (part.type === "text") {
            if (!part.text.trim()) return null;
            const streamingThis = isStreaming && part === textParts.at(-1);
            return (
              <CitationSourcesProvider
                key={index}
                value={sources}
                prefix={message.id}
                onOpenSource={openSource}
              >
                <MessageResponse
                  className="font-voice text-ax-text text-base leading-[1.62]"
                  remarkPlugins={remarkPlugins}
                  components={citationComponents}
                  isAnimating={streamingThis}
                >
                  {resolveInrefs(
                    streamingThis ? trimPartialInref(part.text) : part.text,
                    sourceIds
                  )}
                </MessageResponse>
              </CitationSourcesProvider>
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
        <McpImageStrip references={mcpReferences} />
        {message.metadata?.generatedFiles?.map((file) => (
          <GeneratedFile key={file.id} file={file} />
        ))}
        {hasText && !isStreaming && (
          <AnswerActions
            text={text}
            hasActivity={activity.hasActivity}
            onShowActivity={(trigger) => onActivityToggle?.(trigger, { tab: "steps" })}
            feedback={feedback}
            timestamp={message.metadata?.createdAt ?? durations?.finishedAt ?? null}
          />
        )}
      </div>
    </AxChatMessage>
  );
}

/**
 * One conversation message. User questions are right-aligned bubbles; answers
 * carry a header (tile, assistant, model), the activity pill that opens the
 * Aktivitet panel, the answer in the serif voice with inline citations, tool
 * approvals, files and an actions row. Shared by ChatView and the design mock
 * page so the two never drift: ChatView owns data and streaming, this owns the
 * presentation.
 */
export function ChatMessage({
  message,
  assistant,
  isStreaming = false,
  showResponseLabel = false,
  liveAnswering = null,
  knowledge = NO_KNOWLEDGE,
  durations = null,
  activityExpanded = false,
  onActivityToggle,
  feedback = null
}: {
  message: EneoUIMessage;
  assistant: AssistantIdentity;
  isStreaming?: boolean;
  showResponseLabel?: boolean;
  liveAnswering?: { id: string; handle: string } | null;
  knowledge?: KnowledgeOrigin[];
  durations?: TurnDurations | null;
  activityExpanded?: boolean;
  onActivityToggle?: (trigger: HTMLElement, request?: ActivityRequest) => void;
  /** A finished answer of a saved conversation: its rating control. */
  feedback?: AnswerFeedback | null;
}) {
  if (message.role === "user") return <UserMessage message={message} />;
  return (
    <AssistantMessage
      message={message}
      assistant={assistant}
      isStreaming={isStreaming}
      showResponseLabel={showResponseLabel}
      liveAnswering={liveAnswering}
      knowledge={knowledge}
      durations={durations}
      activityExpanded={activityExpanded}
      onActivityToggle={onActivityToggle}
      feedback={feedback}
    />
  );
}

/**
 * Placeholder answer while the question is sent and nothing has streamed
 * yet: the header, a "thinking" status and skeleton lines (aria-hidden; the
 * live region announces the finished answer instead).
 */
export function PendingAnswer({ assistant }: { assistant: AssistantIdentity }) {
  return (
    <AxChatMessage
      sender="assistant"
      name={<AssistantName assistant={assistant} model={null} handle={null} />}
      className="w-full"
    >
      <div className="flex w-full flex-col gap-3 pt-1">
        <ThinkingStatus />
        <AnswerSkeleton />
      </div>
    </AxChatMessage>
  );
}

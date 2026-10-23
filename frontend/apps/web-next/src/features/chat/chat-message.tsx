"use client";

import {
  ChatMessage as AxChatMessage,
  ChatMessageBubble,
  ChatTokenizedText
} from "@astryxdesign/core/Chat";
import { useClipboard } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { ToggleButton, ToggleButtonGroup } from "@astryxdesign/core/ToggleButton";
import { Copy, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef, type ReactNode } from "react";

import {
  CitationSourcesProvider,
  useCitationRemarkPlugins
} from "@/components/ai-elements/citation";
import { ANSWER_TEXT_CLASS, MessageResponse } from "@/components/ai-elements/message";
import { iconUrl } from "@/components/composites/icon-field";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { McpAppFrames } from "@/features/mcp-apps/mcp-app-frames";
import { isChartDocumentAsset } from "@/features/mcp-apps/mcp-apps";
import { tableLocationLabel } from "@/features/workspace/preview/table-reference";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import { resolveInrefs, trimPartialInref } from "@/lib/chat/inref";
import type { AnswerRating, EneoUIMessage, KnowledgeOrigin } from "@/lib/chat/types";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

import { deriveActivity, modelName } from "./activity";
import type { ActivityTab } from "./activity-panel";
import type { ChatReferences } from "./chat-references";
import type { DocumentDraft } from "./side-panel/document-draft";
import { ActivityPill } from "./activity-pill";
import type { TurnDurations } from "./activity-timings";
import {
  answerLinkComponents,
  documentNames,
  DocumentLinksProvider,
  useDocumentNameRemarkPlugins
} from "./answer-links";
import { DocumentLine, DraftLine, type DocumentLineKind } from "./document-line";
import {
  isDocument,
  revisedFileId,
  type ConversationDocument,
  type GeneratedDocument
} from "./side-panel/document-versions";
import { messageGeneratedFiles, messageToolCalls } from "./side-panel/message-tool-calls";
import { isTableQuote, parseQuotedQuestion, quotedFileMatches } from "./side-panel/question-quote";
import { useSidePanel } from "./side-panel/use-side-panel";
import {
  assistantClipboardContent,
  canCopyRichText,
  copyRichText,
  getPreferredAssistantCopyFormat,
  type AssistantCopyFormat
} from "./copy-assistant-answer";
import {
  answeringAssistantFromParts,
  InlineImage,
  McpImageStrip,
  mcpReferencesFromParts,
  ToolApprovalCard
} from "./message-parts";
import { MessageFiles, PendingMessageFiles, type PendingUpload } from "./message-files";

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

/**
 * A passage the question quotes from a file or an interactive view. When the
 * file is in the conversation and can be shown, the quote opens it at the passage.
 */
function QuestionQuote({
  quote,
  conversationFiles
}: {
  quote: NonNullable<ReturnType<typeof parseQuotedQuestion>["quote"]>;
  conversationFiles: readonly PreviewFile[];
}) {
  const t = useTranslations();
  const panel = useSidePanel();
  // New quotes carry the exact file identity. Filename matching is only for
  // legacy quotes, and must never substitute a revision for an exact reference.
  const file =
    quote.fileName && panel
      ? conversationFiles.findLast(
          (candidate) => quotedFileMatches(quote, candidate) && panel.canPreview(candidate)
        )
      : undefined;
  const location = tableLocationLabel(quote.locator, (row) => t("table_reference_row", { row }));
  const body = (
    <blockquote className="m-0">
      {isTableQuote(quote.text) ? (
        // Cells quoted from a table carry its header row, and read as a table.
        <div className="text-ax-text-secondary text-sm">
          <MessageResponse>{quote.text}</MessageResponse>
        </div>
      ) : (
        <p className="text-ax-text-secondary m-0 line-clamp-6 text-[13.5px] whitespace-pre-wrap">
          {quote.text}
        </p>
      )}
      {quote.fileName && (
        <footer className="text-ax-text-secondary mt-1 text-xs">
          {quote.fileName}
          {location && <span> · {location}</span>}
        </footer>
      )}
    </blockquote>
  );
  const className =
    "border-ax-border-strong bg-ax-surface rounded-ax-element block w-full border-s-2 px-3 py-2 text-start";
  if (file && panel) {
    return (
      <button
        type="button"
        aria-label={t("file_quote_show", { name: file.name })}
        onClick={(event) => panel.showPassage(file, quote, event.currentTarget)}
        className={cn(
          className,
          "hover:bg-ax-hover focus-visible:outline-ring focus-visible:outline-2 focus-visible:outline-offset-2"
        )}
      >
        {body}
      </button>
    );
  }
  return (
    <div className={className}>
      {body}
      {quote.fileId && (
        <p className="text-ax-text-secondary mt-1 text-xs">{t("table_reference_unavailable")}</p>
      )}
    </div>
  );
}

/** A question as sent: a filled bubble on the right, its files (`children`) below. */
function Question({
  text: sent,
  conversationFiles,
  references,
  children
}: {
  text: string;
  conversationFiles: readonly PreviewFile[];
  references?: ChatReferences;
  children?: ReactNode;
}) {
  const t = useTranslations();
  // A question may open with a passage quoted from a file preview.
  const { quote, text } = parseQuotedQuestion(sent);
  return (
    <AxChatMessage
      sender="user"
      name={<span className="sr-only">{t("chat_your_message")}</span>}
      className="w-full"
    >
      {(text || quote) && (
        <ChatMessageBubble className="bg-ax-muted rounded-ax-page flex max-w-[min(100%,32.5rem)] flex-col gap-2 px-[15px] py-2.5 text-[14.5px] leading-normal whitespace-pre-wrap">
          {quote && <QuestionQuote quote={quote} conversationFiles={conversationFiles} />}
          {references ? (
            <ChatTokenizedText tokens={references.tokens(text)}>{text}</ChatTokenizedText>
          ) : (
            text
          )}
        </ChatMessageBubble>
      )}
      {children}
    </AxChatMessage>
  );
}

/** The user's question: a filled bubble on the right, attachments as file chips below. */
function UserMessage({
  message,
  conversationFiles,
  references
}: {
  message: EneoUIMessage;
  conversationFiles: readonly PreviewFile[];
  references?: ChatReferences;
}) {
  const files = message.metadata?.files ?? [];
  return (
    <Question
      text={messageText(message)}
      conversationFiles={conversationFiles}
      references={references}
    >
      {files.length > 0 && <MessageFiles files={files} />}
    </Question>
  );
}

/**
 * A question sent before its attachments were on the server. It stands in the
 * conversation like any question, mirroring the uploads' progress, until the
 * request is issued and the stored message takes its place.
 */
export function PendingQuestion({
  text,
  uploads,
  conversationFiles = NO_FILES,
  references
}: {
  text: string;
  uploads: readonly PendingUpload[];
  conversationFiles?: readonly PreviewFile[];
  references?: ChatReferences;
}) {
  return (
    <Question text={text} conversationFiles={conversationFiles} references={references}>
      <PendingMessageFiles uploads={uploads} />
    </Question>
  );
}

/**
 * What an answer produced, under its text: images inline, and one line per
 * document that names it and opens it in the side panel. A chart exported
 * only as part of a report is left out. A version a reader saved belongs to
 * the document it revises: it gets no line of its own, and the document's
 * line opens its newest version.
 */
function GeneratedFiles({
  message,
  documents
}: {
  message: EneoUIMessage;
  documents: ConversationDocument[];
}) {
  const calls = messageToolCalls(message);
  const hidden = new Set(
    calls.filter(isChartDocumentAsset).flatMap((call) => call.generatedFileIds)
  );
  const files = messageGeneratedFiles(message).filter(
    (file) => !hidden.has(file.id) && !file.revises_file_id
  );
  if (files.length === 0) return null;
  const latestOf = (file: GeneratedDocument) =>
    documents.find((document) => document.versions.some((version) => version.id === file.id))
      ?.latest ?? file;
  const kindOf = (file: GeneratedDocument): DocumentLineKind => {
    const call = calls.find((candidate) => candidate.generatedFileIds.includes(file.id));
    if (call?.purpose !== "file_creation") return "exported";
    return revisedFileId(call.input) ? "updated" : "created";
  };
  return (
    <div className="flex flex-col gap-2">
      {files.map((file) =>
        // An empty mimetype is the placeholder of an image still being generated.
        !file.mimetype || file.mimetype.startsWith("image/") ? (
          <InlineImage key={file.id} file={file} />
        ) : isDocument(file) ? (
          <DocumentLine key={file.id} file={latestOf(file)} kind={kindOf(file)} />
        ) : null
      )}
    </div>
  );
}

/**
 * "Assistenten tänker…" before any step or text has streamed in. Not a live
 * region: the view announces the finished answer instead (the spinner's own
 * status role is hidden).
 */
/**
 * The badge reads as thinking by default; a question still waiting for its
 * attachments to upload says what it waits for instead.
 */
function ThinkingStatus({ label }: { label?: string }) {
  const t = useTranslations();
  return (
    <span className="bg-ax-accent-muted text-ax-text-accent inline-flex min-h-[30px] items-center gap-1.5 self-start rounded-full ps-2 pe-3 text-[12.5px] font-semibold">
      <span aria-hidden="true" className="flex">
        <Spinner size="md" shade="inherit" />
      </span>
      {label ?? t("chat_assistant_thinking")}
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
  onDebug,
  feedback,
  timestamp
}: {
  text: string;
  hasActivity: boolean;
  onShowActivity: (trigger: HTMLElement) => void;
  /** Opens the answer's Felsök tab (users with `assistant_debug`). */
  onDebug: ((trigger: HTMLElement) => void) | null;
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
  // The panel returns focus to the menu button that opened it.
  const openPanel = (open: (trigger: HTMLElement) => void) => {
    const trigger = moreRef.current?.querySelector("button");
    if (trigger) open(trigger);
  };
  const moreItems = [
    { label: t("copy_as_markdown"), onClick: () => void copy("markdown") },
    { label: t("copy_as_richtext"), onClick: () => void copy("richtext") },
    ...(hasActivity
      ? [{ label: t("chat_show_activity"), onClick: () => openPanel(onShowActivity) }]
      : []),
    ...(onDebug ? [{ label: t("chat_debug_action"), onClick: () => openPanel(onDebug) }] : [])
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

const NO_DOCUMENTS: ConversationDocument[] = [];

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
  feedback,
  canDebug,
  sessionId,
  documents,
  draft,
  references
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
  canDebug: boolean;
  sessionId: string | null;
  documents: ConversationDocument[];
  draft: DocumentDraft | null;
  references?: ChatReferences;
}) {
  const panel = useSidePanel();
  const text = messageText(message);
  // The names an answer can mention a document by: each is a link to it.
  const names = useMemo(
    () => documentNames(documents.flatMap((document) => document.versions)),
    [documents]
  );
  const documentPlugins = useDocumentNameRemarkPlugins(names);
  const documentLinks = useMemo(
    () => ({
      names,
      fileFor: (name: string) => {
        // The file meant: the one this answer created, else the newest document of that name.
        const own = messageGeneratedFiles(message).findLast(
          (candidate) => isDocument(candidate) && nameMatches(candidate, name)
        );
        return (
          own ??
          documents.findLast((document) =>
            document.versions.some((version) => nameMatches(version, name))
          )?.latest
        );
      },
      onOpen: (file: GeneratedDocument, trigger: HTMLElement) => panel?.open(file, trigger)
    }),
    [names, documents, message, panel]
  );
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
  const citationPlugins = useCitationRemarkPlugins(sources.length, message.id);
  const referencePlugins = references?.remarkPlugins;
  const remarkPlugins = useMemo(
    () => [...citationPlugins, ...documentPlugins, ...(referencePlugins ?? [])],
    [citationPlugins, documentPlugins, referencePlugins]
  );
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
                <DocumentLinksProvider value={documentLinks}>
                  <MessageResponse
                    className={ANSWER_TEXT_CLASS}
                    remarkPlugins={remarkPlugins}
                    components={references?.components ?? answerLinkComponents}
                    isAnimating={streamingThis}
                  >
                    {resolveInrefs(
                      streamingThis ? trimPartialInref(part.text) : part.text,
                      sourceIds
                    )}
                  </MessageResponse>
                </DocumentLinksProvider>
              </CitationSourcesProvider>
            );
          }
          if (part.type === "data-tool-approval") {
            return <ToolApprovalCard key={part.id ?? index} data={part.data} />;
          }
          return null;
        })}
        <McpImageStrip references={mcpReferences} />
        <McpAppFrames message={message} live={isStreaming} sessionId={sessionId} />
        {draft && <DraftLine draft={draft} />}
        <GeneratedFiles message={message} documents={documents} />
        {hasText && !isStreaming && (
          <AnswerActions
            text={text}
            hasActivity={activity.hasActivity}
            onShowActivity={(trigger) => onActivityToggle?.(trigger, { tab: "steps" })}
            onDebug={
              canDebug && onActivityToggle
                ? (trigger) => onActivityToggle(trigger, { tab: "debug" })
                : null
            }
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
 * Aktivitet panel, the answer as prose with inline citations, tool
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
  feedback = null,
  canDebug = false,
  sessionId = null,
  conversationFiles = NO_FILES,
  documents = NO_DOCUMENTS,
  draft = null,
  references
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
  /** The viewer may debug assistants and the answer is saved: a "Felsök" action. */
  canDebug?: boolean;
  /** The saved conversation, for the results an interactive view reads. */
  sessionId?: string | null;
  /** Every file of the conversation, so a quoted passage can open its file. */
  conversationFiles?: readonly PreviewFile[];
  /** The documents the assistant made in the conversation, so an answer can name them. */
  documents?: ConversationDocument[];
  /** The document this answer is writing now, which the answer offers to show. */
  draft?: DocumentDraft | null;
  /** What the conversation can refer to: pills in questions and answers. */
  references?: ChatReferences;
}) {
  if (message.role === "user") {
    return (
      <UserMessage
        message={message}
        conversationFiles={conversationFiles}
        references={references}
      />
    );
  }
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
      canDebug={canDebug}
      sessionId={sessionId}
      documents={documents}
      draft={draft}
      references={references}
    />
  );
}

const NO_FILES: PreviewFile[] = [];

/** Whether a document goes by `name`: its file name, or its title for a Markdown document. */
function nameMatches(file: { name: string }, name: string): boolean {
  return file.name === name || file.name.replace(/\.(md|markdown)$/i, "") === name;
}

/**
 * Placeholder answer while the question is sent and nothing has streamed
 * yet: the header, a "thinking" status and skeleton lines (aria-hidden; the
 * live region announces the finished answer instead).
 */
export function PendingAnswer({
  assistant,
  status
}: {
  assistant: AssistantIdentity;
  /** What is waited for, when it is not the model: the question's uploads. */
  status?: string;
}) {
  return (
    <AxChatMessage
      sender="assistant"
      name={<AssistantName assistant={assistant} model={null} handle={null} />}
      className="w-full"
    >
      <div className="flex w-full flex-col gap-3 pt-1">
        <ThinkingStatus label={status} />
        <AnswerSkeleton />
      </div>
    </AxChatMessage>
  );
}

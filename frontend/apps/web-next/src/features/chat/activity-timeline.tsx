"use client";

import { useQuery } from "@tanstack/react-query";
import { BrainIcon, ChevronDownIcon, SparklesIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { ToolContent, ToolInput, ToolOutput } from "@/components/ai-elements/tool";
import {
  StatusNode,
  ToolStateIcon,
  ToolStatusBadge,
  humanizeToolName,
  toolStateTone,
  type ToolState
} from "@/components/ai-elements/tool-status";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { EneoUIMessage } from "@/lib/chat/types";

type Part = EneoUIMessage["parts"][number];
type ReasoningPart = Extract<Part, { type: "reasoning" }>;
type ToolPart = Extract<Part, { type: "dynamic-tool" }>;

const isActivityPart = (part: Part): part is ReasoningPart | ToolPart =>
  part.type === "reasoning" || part.type === "dynamic-tool";

// Tool state → translation key. `as const satisfies` keeps the values a literal
// union so next-intl still type-checks the lookup.
const STATUS_KEY = {
  "input-streaming": "chat_tool_status_pending",
  "input-available": "chat_tool_status_running",
  "output-available": "chat_tool_status_done",
  "output-error": "chat_tool_status_error",
  "output-denied": "chat_tool_status_denied",
  "approval-requested": "chat_tool_status_awaiting",
  "approval-responded": "chat_tool_status_approved"
} as const satisfies Record<ToolState, string>;

/**
 * Groups an assistant turn's reasoning and tool calls into one collapsible
 * "activity" block: a one-line summary on the surface, a connected timeline of
 * steps when expanded, and per-step I/O one dive deeper. Auto-expands while the
 * turn streams, then collapses — unless the reader has taken manual control.
 */
export function ActivityTimeline({
  parts,
  isStreaming,
  sessionId = null
}: {
  parts: Part[];
  isStreaming: boolean;
  sessionId?: string | null;
}) {
  const t = useTranslations();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);

  const steps = parts.filter(isActivityPart);
  if (steps.length === 0) return null;

  // Collapsed by default in BOTH states: while streaming the trigger shows a
  // single live action line; once done it shows the resolved summary. The reader
  // expands to see the full timeline.
  const open = userOpen ?? false;
  const toolCount = steps.filter((part) => part.type === "dynamic-tool").length;
  const errorCount = steps.filter(
    (part) => part.type === "dynamic-tool" && part.state === "output-error"
  ).length;

  const summary = [
    steps.some((part) => part.type === "reasoning") ? t("chat_activity_reasoned") : null,
    toolCount > 0 ? t("chat_activity_tools", { count: toolCount }) : null,
    errorCount > 0 ? t("chat_activity_errors", { count: errorCount }) : null
  ]
    .filter(Boolean)
    .join(" · ");

  // The current action, shown live while streaming: the running tool, the
  // reasoning, or — once the activity is done — that the answer is being written.
  const lastStep = steps[steps.length - 1];
  if (!lastStep) return null;
  const liveText =
    lastStep.type === "dynamic-tool" &&
    (lastStep.state === "input-available" || lastStep.state === "input-streaming")
      ? humanizeToolName(lastStep.toolName)
      : lastStep.type === "reasoning"
        ? t("chat_reasoning_thinking")
        : t("chat_activity_writing");

  return (
    <Collapsible
      open={open}
      onOpenChange={setUserOpen}
      className="bg-card/40 not-prose w-full rounded-xl border"
    >
      <CollapsibleTrigger className="group/act text-muted-foreground hover:text-foreground flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors">
        {isStreaming ? (
          <>
            <Spinner aria-hidden="true" className="text-primary size-4 shrink-0" />
            <span className="text-foreground min-w-0 truncate">
              <Shimmer as="span" duration={1}>{`${liveText}…`}</Shimmer>
            </span>
          </>
        ) : (
          <>
            <SparklesIcon aria-hidden="true" className="size-4 shrink-0" />
            <span className="truncate">{summary || t("chat_activity_label")}</span>
          </>
        )}
        <span className="ml-auto shrink-0 text-xs">
          {open ? t("chat_activity_hide") : t("chat_activity_show")}
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className="size-4 shrink-0 transition-transform group-data-[state=open]/act:rotate-180"
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 overflow-hidden px-3 pt-1 pb-3">
        <div className="relative flex flex-col gap-3">
          {/* Connector rail behind the nodes (nodes are opaque and sit on top). */}
          <span
            aria-hidden="true"
            className="bg-border absolute top-3 bottom-3 left-[13.5px] w-px"
          />
          {steps.map((part, index) =>
            part.type === "reasoning" ? (
              <ReasoningStep key={index} part={part} />
            ) : (
              <ToolStep
                key={index}
                part={part}
                label={t(STATUS_KEY[part.state])}
                sessionId={sessionId}
              />
            )
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ReasoningStep({ part }: { part: ReasoningPart }) {
  const t = useTranslations();
  const isStreaming = part.state === "streaming";

  // Shimmering header while thinking, elapsed seconds once done (duration is
  // computed inside <Reasoning/>).
  const thinkingMessage = (streaming: boolean, duration?: number): ReactNode => {
    if (streaming || duration === 0) {
      return <Shimmer duration={1}>{t("chat_reasoning_thinking")}</Shimmer>;
    }
    if (duration === undefined) return <span>{t("chat_reasoning_thought")}</span>;
    return <span>{t("chat_reasoning_thought_for", { seconds: duration })}</span>;
  };

  return (
    <div className="relative flex gap-3">
      <StatusNode tone={isStreaming ? "running" : "neutral"}>
        <BrainIcon aria-hidden="true" className="size-3.5" />
      </StatusNode>
      <div className="min-w-0 flex-1 pt-1">
        <Reasoning isStreaming={isStreaming} className="mb-0">
          <ReasoningTrigger getThinkingMessage={thinkingMessage} showIcon={false} />
          <ReasoningContent>{part.text}</ReasoningContent>
        </Reasoning>
      </div>
    </div>
  );
}

function ToolStep({
  part,
  label,
  sessionId
}: {
  part: ToolPart;
  label: string;
  sessionId: string | null;
}) {
  const t = useTranslations();
  // Keep the active and failed steps open by default; completed steps stay
  // tucked away until the reader dives in.
  const defaultOpen = part.state === "output-error" || part.state === "input-available";
  const [open, setOpen] = useState(defaultOpen);
  const canLoadResult = Boolean(
    sessionId &&
    part.toolCallId &&
    (part.state === "output-available" || part.state === "output-error")
  );
  const result = useQuery({
    queryKey: ["conversations", "tool-call-result", sessionId, part.toolCallId],
    enabled: open && canLoadResult,
    staleTime: Infinity,
    queryFn: async () => {
      const response = await unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/result/", {
          params: {
            path: {
              session_id: sessionId!,
              tool_call_id: part.toolCallId!
            }
          }
        })
      );
      return response.result ?? null;
    }
  });

  const hasLoadedResult = canLoadResult && result.data !== undefined;
  const resultText = typeof result.data === "string" && result.data.trim() ? result.data : null;
  const output =
    canLoadResult && result.isLoading
      ? t("loading_ellipsis")
      : canLoadResult && result.isError
        ? undefined
        : hasLoadedResult
          ? (resultText ?? t("mcp_tool_response_empty"))
          : part.state === "output-available"
            ? JSON.stringify(part.output, null, 2)
            : undefined;
  const errorText =
    canLoadResult && result.isError
      ? t("mcp_tool_response_load_error")
      : hasLoadedResult && output
        ? undefined
        : part.state === "output-error"
          ? part.errorText
          : undefined;

  return (
    <div className="relative flex gap-3">
      <StatusNode tone={toolStateTone(part.state)}>
        <ToolStateIcon state={part.state} className="size-3.5" />
      </StatusNode>
      <Collapsible open={open} onOpenChange={setOpen} className="group/tool min-w-0 flex-1">
        <CollapsibleTrigger className="flex w-full items-center gap-2 py-1 text-left">
          <span className="text-foreground truncate text-sm font-medium">
            {humanizeToolName(part.toolName)}
          </span>
          <ToolStatusBadge
            state={part.state}
            label={label}
            showIcon={false}
            className="ml-auto shrink-0"
          />
          <ChevronDownIcon
            aria-hidden="true"
            className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[state=open]/tool:rotate-180"
          />
        </CollapsibleTrigger>
        <ToolContent className="px-0">
          <ToolInput input={part.input} />
          <ToolOutput errorText={errorText} output={output} />
        </ToolContent>
      </Collapsible>
    </div>
  );
}

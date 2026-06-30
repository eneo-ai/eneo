"use client";

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
  toolStateTone,
  type ToolState
} from "@/components/ai-elements/tool-status";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Spinner } from "@/components/ui/spinner";
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
export function ActivityTimeline({ parts, isStreaming }: { parts: Part[]; isStreaming: boolean }) {
  const t = useTranslations();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);

  const steps = parts.filter(isActivityPart);
  if (steps.length === 0) return null;

  const open = userOpen ?? isStreaming;
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

  return (
    <Collapsible
      open={open}
      onOpenChange={setUserOpen}
      className="bg-card/40 not-prose w-full rounded-xl border"
    >
      <CollapsibleTrigger className="group/act text-muted-foreground hover:text-foreground flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors">
        <SparklesIcon aria-hidden="true" className="size-4 shrink-0" />
        <span className="truncate">{summary || t("chat_activity_label")}</span>
        {isStreaming && <Spinner className="text-primary size-3.5 shrink-0" />}
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
              <ToolStep key={index} part={part} label={t(STATUS_KEY[part.state])} />
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
          <ReasoningTrigger getThinkingMessage={thinkingMessage} />
          <ReasoningContent>{part.text}</ReasoningContent>
        </Reasoning>
      </div>
    </div>
  );
}

function ToolStep({ part, label }: { part: ToolPart; label: string }) {
  // Keep the active and failed steps open by default; completed steps stay
  // tucked away until the reader dives in.
  const defaultOpen = part.state === "output-error" || part.state === "input-available";

  return (
    <div className="relative flex gap-3">
      <StatusNode tone={toolStateTone(part.state)}>
        <ToolStateIcon state={part.state} className="size-3.5" />
      </StatusNode>
      <Collapsible defaultOpen={defaultOpen} className="group/tool min-w-0 flex-1">
        <CollapsibleTrigger className="flex w-full items-center gap-2 py-1 text-left">
          <span className="text-foreground truncate text-sm font-medium">{part.toolName}</span>
          <ToolStatusBadge state={part.state} label={label} className="ml-auto shrink-0" />
          <ChevronDownIcon
            aria-hidden="true"
            className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[state=open]/tool:rotate-180"
          />
        </CollapsibleTrigger>
        <ToolContent className="px-0">
          <ToolInput input={part.input} />
          <ToolOutput
            errorText={part.state === "output-error" ? part.errorText : undefined}
            output={
              part.state === "output-available" ? JSON.stringify(part.output, null, 2) : undefined
            }
          />
        </ToolContent>
      </Collapsible>
    </div>
  );
}

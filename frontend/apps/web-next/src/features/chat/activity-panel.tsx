"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQuery } from "@tanstack/react-query";
import {
  Ban,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Clock,
  ExternalLink,
  FileText,
  Folder,
  Globe,
  LoaderCircle,
  ShieldCheck,
  ShieldX,
  Square,
  X,
  type LucideIcon
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type Ref } from "react";
import { MessageResponse } from "@/components/ai-elements/message";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import {
  currentStep,
  type Activity,
  type ActivitySource,
  type ActivityStep,
  type StepStatus,
  type ToolPart
} from "./activity";
import type { TurnDurations } from "./activity-timings";
import { formatSeconds } from "./format";
import { McpResourceSnippetDialog } from "./message-parts";
import { eneoToolMetadata, skillName, toolPresentation } from "./tool-presentation";

export type ActivityTab = "steps" | "sources";

/** Id of the source entry that inline citation N (1-based) opens. */
export function sourceAnchorId(messageId: string, number: number): string {
  return `${messageId}-source-${number}`;
}

export const ACTIVITY_PANEL_ID = "chat-activity-panel";

// ---------------------------------------------------------------------------
// Step presentation
// ---------------------------------------------------------------------------

const STATUS_STYLE: Record<StepStatus, { icon: LucideIcon; className: string; spin?: boolean }> = {
  done: { icon: Check, className: "bg-ax-success-muted text-ax-success" },
  running: { icon: LoaderCircle, className: "bg-ax-accent-muted text-ax-text-accent", spin: true },
  waiting: { icon: Clock, className: "bg-ax-muted text-ax-text-secondary" },
  error: { icon: X, className: "bg-ax-error-muted text-ax-error" },
  denied: { icon: Ban, className: "bg-ax-warning-muted text-ax-warning" },
  stopped: { icon: Square, className: "bg-ax-muted text-ax-text-secondary" }
};

const STATUS_KEY = {
  done: "chat_step_status_done",
  running: "chat_step_status_running",
  waiting: "chat_step_status_waiting",
  error: "chat_step_status_error",
  denied: "chat_step_status_denied",
  stopped: "chat_step_status_stopped"
} as const satisfies Record<StepStatus, string>;

const STATUS_TEXT_CLASS: Partial<Record<StepStatus, string>> = {
  error: "text-ax-error",
  denied: "text-ax-warning",
  stopped: "text-ax-text-secondary",
  waiting: "text-ax-text-secondary"
};

const SKILL_FAILURE_KEYS: Record<string, string> = {
  unknown_key: "chat_debug_rejection_unknown_key",
  blocked: "chat_debug_rejection_blocked",
  activation_unavailable: "chat_debug_rejection_activation_unavailable",
  activation_limit_exceeded: "chat_debug_rejection_activation_limit_exceeded",
  context_limit_exceeded: "chat_debug_rejection_context_limit_exceeded",
  model_context_limit_exceeded: "chat_debug_rejection_model_context_limit_exceeded",
  token_measurement_unavailable: "chat_debug_rejection_token_measurement_unavailable",
  reserved_tool_collision: "chat_debug_rejection_reserved_tool_collision"
};

type Translate = ReturnType<typeof useTranslations>;

/** The human title of a step (also used by the live pill while streaming). */
export function stepTitle(step: ActivityStep, t: Translate): string {
  const done = step.status !== "running" && step.status !== "waiting";
  switch (step.kind) {
    case "reasoning":
      return done ? t("chat_activity_reasoned") : t("chat_reasoning_thinking");
    case "knowledge":
      return t("chat_activity_knowledge_title");
    case "tool":
      return toolPresentation(step.part, t, step.status === "done").label;
    case "skill":
      return t(
        step.status === "error" || step.status === "denied"
          ? "tool_activate_skill_failed"
          : "tool_activate_skill",
        { name: skillName(step.part) }
      );
    case "answer":
      return done ? t("chat_activity_answer_done") : t("chat_activity_writing");
  }
}

function toolArguments(part: ToolPart): string {
  const input = part.input;
  if (!input || typeof input !== "object" || Array.isArray(input)) return "";
  return Object.entries(input as Record<string, unknown>)
    .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
    .join(", ");
}

function toolServer(part: ToolPart): string | null {
  const server = eneoToolMetadata(part).server_name;
  return typeof server === "string" && server ? server : null;
}

function StatusCircle({ status }: { status: StepStatus }) {
  const t = useTranslations();
  const { icon: Icon, className, spin } = STATUS_STYLE[status];
  return (
    <span
      className={cn(
        "relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full",
        className
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn("size-3.5", spin && "animate-spin")}
        strokeWidth={2.6}
      />
      <span className="sr-only">{t(STATUS_KEY[status])}</span>
    </span>
  );
}

function ToolResult({ part, sessionId }: { part: ToolPart; sessionId: string | null }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const finished = part.state === "output-available" || part.state === "output-error";
  const canLoad = Boolean(sessionId && part.toolCallId && finished);
  const result = useQuery({
    queryKey: ["conversations", "tool-call-result", sessionId, part.toolCallId],
    enabled: open && canLoad,
    staleTime: Infinity,
    queryFn: async () => {
      const response = await unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/tool-calls/{tool_call_id}/result/", {
          params: { path: { session_id: sessionId!, tool_call_id: part.toolCallId } }
        })
      );
      return response.result ?? null;
    }
  });

  if (!finished) return null;
  const errorText = part.state === "output-error" ? part.errorText : undefined;
  if (!canLoad) {
    return errorText ? (
      <p className="text-ax-error border-ax-border border-t px-2.5 py-1.5 text-[12.5px]">
        {errorText}
      </p>
    ) : null;
  }

  const body = result.isPending
    ? t("loading_ellipsis")
    : result.isError
      ? t("mcp_tool_response_load_error")
      : typeof result.data === "string" && result.data.trim()
        ? result.data
        : (errorText ?? t("mcp_tool_response_empty"));

  return (
    <div className="border-ax-border border-t">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? regionId : undefined}
        onClick={() => setOpen((value) => !value)}
        className="text-ax-text-secondary hover:bg-ax-hover focus-visible:outline-ring flex min-h-8 w-full items-center gap-1.5 px-2.5 text-left text-[12.5px] font-medium focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        <ChevronRight
          aria-hidden="true"
          className={cn("size-3.5 transition-transform", open && "rotate-90")}
        />
        {open ? t("chat_tool_hide_result") : t("chat_tool_show_result")}
      </button>
      {open && (
        <pre
          id={regionId}
          role="region"
          tabIndex={0}
          aria-label={t("chat_tool_result")}
          className="text-ax-text focus-visible:outline-ring max-h-48 overflow-auto px-2.5 pb-2 font-mono text-[11.5px] break-words whitespace-pre-wrap focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          {body}
        </pre>
      )}
    </div>
  );
}

function StepDetails({ step, sessionId }: { step: ActivityStep; sessionId: string | null }) {
  const t = useTranslations();
  const [showReasoning, setShowReasoning] = useState(false);
  const reasoningId = useId();

  switch (step.kind) {
    case "reasoning":
      if (!step.text.trim()) return null;
      return (
        <div className="flex flex-col gap-1.5">
          <button
            type="button"
            aria-expanded={showReasoning}
            aria-controls={showReasoning ? reasoningId : undefined}
            onClick={() => setShowReasoning((value) => !value)}
            className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner -ms-1 flex min-h-6 w-fit items-center gap-1 px-1 text-[12.5px] font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <ChevronRight
              aria-hidden="true"
              className={cn("size-3.5 transition-transform", showReasoning && "rotate-90")}
            />
            {showReasoning ? t("chat_activity_hide_reasoning") : t("chat_activity_show_reasoning")}
          </button>
          {showReasoning && (
            <div id={reasoningId} className="text-ax-text-secondary text-[12.5px] leading-relaxed">
              <MessageResponse>{step.text}</MessageResponse>
            </div>
          )}
        </div>
      );
    case "knowledge":
      return (
        <div className="flex flex-col gap-1.5">
          {step.origins.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {step.origins.map((origin) => {
                const Icon = origin.kind === "website" ? Globe : Folder;
                return (
                  <li
                    key={origin.id}
                    className="bg-ax-card border-ax-border rounded-ax-inner inline-flex h-6 max-w-full items-center gap-1.5 border px-2 text-xs font-medium"
                  >
                    <Icon aria-hidden="true" className="size-3 shrink-0" />
                    <span className="truncate">{origin.name}</span>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-ax-text-secondary text-[12.5px]">
            {t("chat_activity_knowledge_hits", { count: step.hits })}
          </p>
        </div>
      );
    case "tool": {
      const server = toolServer(step.part);
      const args = toolArguments(step.part);
      return (
        <div className="flex flex-col gap-1.5">
          <div className="bg-ax-card border-ax-border rounded-ax-element overflow-hidden border">
            <div
              role="region"
              tabIndex={0}
              aria-label={t("chat_tool_call_label")}
              className="focus-visible:outline-ring overflow-x-auto px-2.5 py-1.5 font-mono text-[11.5px] whitespace-nowrap focus-visible:outline-2 focus-visible:-outline-offset-2"
            >
              {server ? `${server}/` : ""}
              {step.part.toolName}({args})
            </div>
            <ToolResult part={step.part} sessionId={sessionId} />
          </div>
          {step.references.length > 0 && (
            <ul className="flex flex-col gap-1 text-[12.5px]">
              {step.references.map((reference) => {
                const meta = (reference.meta ?? {}) as { title?: unknown; pageRange?: unknown };
                const title =
                  typeof meta.title === "string" && meta.title ? meta.title : reference.uri;
                const pages = typeof meta.pageRange === "string" ? meta.pageRange : null;
                return (
                  <li key={reference.id} className="flex min-w-0 items-center gap-1.5">
                    <FileText
                      aria-hidden="true"
                      className="text-ax-text-secondary size-3.5 shrink-0"
                    />
                    <span className="min-w-0 flex-1 truncate">{title}</span>
                    {pages && (
                      <span className="text-ax-text-secondary shrink-0">
                        {t("mcp_resource_page_range", { pageRange: pages })}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {step.approval && (
            <p
              className={cn(
                "flex items-center gap-1.5 text-xs",
                step.approval === "approved" ? "text-ax-success" : "text-ax-error"
              )}
            >
              {step.approval === "approved" ? (
                <ShieldCheck aria-hidden="true" className="size-3.5" />
              ) : (
                <ShieldX aria-hidden="true" className="size-3.5" />
              )}
              {step.approval === "approved" ? t("chat_tool_approved") : t("chat_tool_denied")}
            </p>
          )}
        </div>
      );
    }
    case "skill": {
      const args =
        step.part.input && typeof step.part.input === "object" && !Array.isArray(step.part.input)
          ? (step.part.input as Record<string, unknown>)
          : {};
      const failed = step.status === "error" || step.status === "denied";
      const reasonKey =
        typeof args.reason === "string" ? SKILL_FAILURE_KEYS[args.reason] : undefined;
      return (
        <p className="text-ax-text-secondary text-[12.5px]">
          {failed
            ? t(reasonKey ?? "skill_step_failed_detail")
            : t(
                args.mode === "always" ? "skill_step_always_detail" : "skill_step_on_demand_detail"
              )}
        </p>
      );
    }
    case "answer": {
      const parts = [
        step.model,
        step.tokens !== null ? t("chat_activity_tokens", { count: step.tokens }) : null
      ].filter(Boolean);
      return parts.length > 0 ? (
        <p className="text-ax-text-secondary text-[12.5px]">{parts.join(" · ")}</p>
      ) : null;
    }
  }
}

function StepList({
  activity,
  durations,
  sessionId
}: {
  activity: Activity;
  durations: TurnDurations | null;
  sessionId: string | null;
}) {
  const t = useTranslations();
  const locale = useLocale();
  return (
    <ol className="flex flex-col">
      {activity.steps.map((step, index) => {
        const duration = durations?.stepMs[step.key];
        const last = index === activity.steps.length - 1;
        const statusText = STATUS_TEXT_CLASS[step.status];
        return (
          <li key={step.key} className="flex gap-3">
            <div className="flex w-[22px] shrink-0 flex-col items-center">
              <StatusCircle status={step.status} />
              {!last && (
                <span aria-hidden="true" className="bg-ax-border-strong my-1 w-px flex-1" />
              )}
            </div>
            <div className={cn("flex min-w-0 flex-1 flex-col gap-1.5", !last && "pb-[18px]")}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] leading-snug font-semibold">
                  {stepTitle(step, t)}
                  {statusText && (
                    <span
                      className={cn("ms-1.5 text-xs font-medium", statusText)}
                      aria-hidden="true"
                    >
                      {t(STATUS_KEY[step.status])}
                    </span>
                  )}
                </span>
                {duration !== undefined && (
                  <span className="text-ax-text-secondary shrink-0 text-xs tabular-nums">
                    {formatSeconds(duration, locale)}
                  </span>
                )}
              </div>
              <StepDetails step={step} sessionId={sessionId} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function SourceList({
  messageId,
  sources,
  focusIndex
}: {
  messageId: string;
  sources: ActivitySource[];
  focusIndex: number | null;
}) {
  const t = useTranslations();
  const itemRefs = useRef<Map<number, HTMLLIElement>>(new Map());

  // A citation opened the panel: move focus to that source (WCAG 2.4.3).
  useEffect(() => {
    if (focusIndex === null) return;
    const item = itemRefs.current.get(focusIndex);
    item?.focus();
    item?.scrollIntoView({ block: "nearest" });
  }, [focusIndex]);

  if (sources.length === 0) {
    return (
      <p className="text-ax-text-secondary px-1 text-[13px]">{t("chat_activity_no_sources")}</p>
    );
  }

  return (
    <ol className="flex flex-col gap-1">
      {sources.map((source, index) => {
        const number = index + 1;
        const meta = [
          source.origin,
          source.detail ? t("mcp_resource_page_range", { pageRange: source.detail }) : null
        ]
          .filter(Boolean)
          .join(" · ");
        const titleClass =
          "focus-visible:outline-ring rounded-ax-inner text-left text-[13px] leading-snug font-medium break-words focus-visible:outline-2 focus-visible:outline-offset-2";
        return (
          <li
            key={source.key}
            id={sourceAnchorId(messageId, number)}
            ref={(element) => {
              if (element) itemRefs.current.set(index, element);
              else itemRefs.current.delete(index);
            }}
            tabIndex={-1}
            className="focus-visible:outline-ring rounded-ax-element focus:bg-ax-selected flex gap-2.5 p-2 focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <span
              aria-hidden="true"
              className="bg-ax-muted rounded-ax-inner mt-px flex size-5 shrink-0 items-center justify-center text-[11px] font-bold"
            >
              {number}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="sr-only">{t("chat_source_number", { number })}</span>
              {source.url ? (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(titleClass, "hover:underline")}
                >
                  {source.title}
                  <ExternalLink aria-hidden="true" className="ms-1 inline size-3 align-[-1px]" />
                  <span className="sr-only"> {t("chat_opens_in_new_tab")}</span>
                </a>
              ) : source.mcpSnippet ? (
                <McpResourceSnippetDialog source={source} snippet={source.mcpSnippet}>
                  <button type="button" className={cn(titleClass, "hover:underline")}>
                    {source.title}
                  </button>
                </McpResourceSnippetDialog>
              ) : (
                <span className="text-[13px] leading-snug font-medium break-words">
                  {source.title}
                </span>
              )}
              {meta && <span className="text-ax-text-secondary text-xs">{meta}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Pill
// ---------------------------------------------------------------------------

/**
 * Disclosure button summarising an answer's activity ("5 steg · 14,6 s · 22
 * källor"); while streaming it names the running step. It opens the Aktivitet
 * panel (aria-expanded/aria-controls).
 */
export function ActivityPill({
  activity,
  durations,
  expanded,
  onToggle,
  ref
}: {
  activity: Activity;
  durations: TurnDurations | null;
  expanded: boolean;
  onToggle: (trigger: HTMLButtonElement) => void;
  ref?: Ref<HTMLButtonElement>;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const live = currentStep(activity);
  const stepCount = activity.steps.length;
  const label = live
    ? `${stepTitle(live, t)}…`
    : [
        stepCount > 0 ? t("chat_activity_steps", { count: stepCount }) : null,
        durations?.totalMs != null ? formatSeconds(durations.totalMs, locale) : null,
        activity.sources.length > 0
          ? t("chat_activity_sources", { count: activity.sources.length })
          : null,
        activity.errorCount > 0 ? t("chat_activity_errors", { count: activity.errorCount }) : null
      ]
        .filter(Boolean)
        .join(" · ");
  const Icon = live ? LoaderCircle : activity.errorCount > 0 ? CircleAlert : CircleCheck;

  return (
    <button
      ref={ref}
      type="button"
      aria-expanded={expanded}
      aria-controls={expanded ? ACTIVITY_PANEL_ID : undefined}
      onClick={(event) => onToggle(event.currentTarget)}
      className={cn(
        "focus-visible:outline-ring inline-flex min-h-[30px] max-w-full items-center gap-1.5 self-start rounded-full py-1 ps-2 pe-2.5 text-[12.5px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11",
        expanded || live
          ? "bg-ax-accent-muted text-ax-text-accent"
          : "bg-ax-muted text-ax-text-secondary hover:text-ax-text"
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "size-[15px] shrink-0",
          live && "animate-spin",
          !live && !expanded && (activity.errorCount > 0 ? "text-ax-warning" : "text-ax-success")
        )}
      />
      <span className="sr-only">{t("chat_activity_label")}: </span>
      <span className="truncate">{label}</span>
      <ChevronRight aria-hidden="true" className="size-3.5 shrink-0" />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

function PanelBody({
  messageId,
  activity,
  durations,
  sessionId,
  tab,
  onTabChange,
  focusSource,
  onClose,
  tabListRef
}: {
  messageId: string;
  activity: Activity;
  durations: TurnDurations | null;
  sessionId: string | null;
  tab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  focusSource: number | null;
  onClose: () => void;
  tabListRef?: Ref<HTMLDivElement>;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const stepsPanelId = `${ACTIVITY_PANEL_ID}-steps`;
  const sourcesPanelId = `${ACTIVITY_PANEL_ID}-sources`;
  const steps = activity.steps.length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-ax-border flex min-h-[52px] shrink-0 items-center justify-between gap-2 border-b ps-3.5 pe-2.5">
        <div ref={tabListRef}>
          <TabList
            value={tab}
            onChange={(value) => onTabChange(value === "sources" ? "sources" : "steps")}
            role="tablist"
            size="sm"
            aria-label={t("chat_activity_label")}
          >
            <Tab value="steps" label={t("chat_activity_steps_tab")} panelId={stepsPanelId} />
            <Tab
              value="sources"
              label={t("chat_sources_label")}
              panelId={sourcesPanelId}
              endContent={
                <span className="bg-ax-surface text-ax-text-secondary rounded-full px-1.5 text-[11px] font-bold tabular-nums">
                  {activity.sources.length}
                </span>
              }
            />
          </TabList>
        </div>
        <IconButton
          label={t("chat_activity_close")}
          icon={<X className="size-4" />}
          variant="ghost"
          size="sm"
          onClick={onClose}
        />
      </div>

      <div
        id={stepsPanelId}
        role="tabpanel"
        aria-label={t("chat_activity_steps_tab")}
        tabIndex={0}
        hidden={tab !== "steps"}
        className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto px-4 pt-[18px] pb-4 focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        <StepList activity={activity} durations={durations} sessionId={sessionId} />
      </div>
      <div
        id={sourcesPanelId}
        role="tabpanel"
        aria-label={t("chat_sources_label")}
        tabIndex={0}
        hidden={tab !== "sources"}
        className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto p-3 focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        <SourceList
          messageId={messageId}
          sources={activity.sources}
          focusIndex={tab === "sources" ? focusSource : null}
        />
      </div>

      <div className="border-ax-border text-ax-text-secondary flex shrink-0 justify-between gap-2 border-t px-4 py-3 text-xs">
        <span>
          {durations?.totalMs != null
            ? t("chat_activity_total", { duration: formatSeconds(durations.totalMs, locale) })
            : null}
        </span>
        <span>
          {t("chat_activity_steps", { count: steps })} ·{" "}
          {activity.errorCount > 0
            ? t("chat_activity_errors", { count: activity.errorCount })
            : t("chat_activity_no_errors")}
        </span>
      </div>
    </div>
  );
}

export type ActivityPanelProps = {
  messageId: string;
  activity: Activity;
  durations: TurnDurations | null;
  sessionId: string | null;
  tab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  /** 0-based source to focus (opened from an inline citation). */
  focusSource: number | null;
  onClose: () => void;
  /** Inline side panel (≥1024px) or a modal bottom sheet (smaller screens). */
  variant: "side" | "sheet";
};

/**
 * The Aktivitet panel: steps (timeline with tool calls, sources read,
 * approvals, durations when known) and numbered sources. Side panel on wide
 * screens, bottom sheet on tablets and phones. Focus moves into it when it
 * opens; Escape and the close button close it (the caller returns focus to
 * the pill that opened it).
 */
export function ActivityPanel({ variant, onClose, ...props }: ActivityPanelProps) {
  const t = useTranslations();
  const titleId = useId();
  const asideRef = useRef<HTMLElement>(null);
  const tabListRef = useRef<HTMLDivElement>(null);
  const focusedFor = useRef<string | null>(null);
  const { focusSource, tab, messageId } = props;

  // Side panel: move focus in once per opened answer (the sheet's dialog does
  // this itself). A citation that targets a source focuses that source instead.
  useEffect(() => {
    if (variant !== "side" || focusedFor.current === messageId) return;
    focusedFor.current = messageId;
    if (tab === "sources" && focusSource !== null) return;
    tabListRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus();
  }, [variant, messageId, tab, focusSource]);

  // Escape closes the side panel from anywhere inside it.
  useEffect(() => {
    const aside = asideRef.current;
    if (variant !== "side" || !aside) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      onClose();
    };
    aside.addEventListener("keydown", onKeyDown);
    return () => aside.removeEventListener("keydown", onKeyDown);
  }, [variant, onClose]);

  if (variant === "sheet") {
    return (
      <BottomSheet
        isOpen
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        label={t("chat_activity_panel_label")}
        height="tall"
      >
        <PanelBody {...props} onClose={onClose} />
      </BottomSheet>
    );
  }

  return (
    <aside
      ref={asideRef}
      id={ACTIVITY_PANEL_ID}
      aria-labelledby={titleId}
      className="bg-ax-sunken border-ax-border flex w-[340px] shrink-0 flex-col border-s"
    >
      <h2 id={titleId} className="sr-only">
        {t("chat_activity_panel_label")}
      </h2>
      <PanelBody {...props} onClose={onClose} tabListRef={tabListRef} />
    </aside>
  );
}

"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import {
  Ban,
  Check,
  Clock,
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
import { MessageResponse } from "@/components/ai-elements/message";
import { cn } from "@/lib/utils";
import type { Activity, ActivityStep, StepStatus, ToolCall } from "./activity";
import type { TurnDurations } from "./activity-timings";
import { formatSeconds } from "./format";
import { ToolCallList } from "./tool-call-list";
import { skillName, toolPresentation } from "./tool-presentation";

/**
 * The Aktivitet panel's Steg tab: a vertical timeline of an answer's steps
 * with status, measured duration and details (knowledge searched, tool calls
 * with their arguments and results, documents read, approvals).
 */

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
      return toolStepTitle(step.calls, done, t);
    case "skill":
      return t(
        step.status === "error" || step.status === "denied"
          ? "tool_activate_skill_failed"
          : done
            ? "skill_used_in_reply"
            : "tool_activate_skill",
        { name: skillName(step.part) }
      );
    case "answer":
      return done ? t("chat_activity_answer_done") : t("chat_activity_writing");
  }
}

/**
 * A tool step's title: the call's own label, or for several calls the shared
 * label with the count ("Läste bifogad fil · 4 anrop") when they are all the
 * same tool, else just the count.
 */
function toolStepTitle(calls: ToolCall[], done: boolean, t: Translate): string {
  const labels = calls.map((call) => toolPresentation(call.part, t, done).label);
  const first = labels[0] ?? "";
  if (calls.length === 1) return first;
  return labels.every((label) => label === first)
    ? t("chat_activity_tool_group", { label: first, count: calls.length })
    : t("chat_activity_tool_calls", { count: calls.length });
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

// Compact Astryx Collapsible for disclosures inside the panel's steps.
const PANEL_COLLAPSIBLE_CLASS =
  "[&_.astryx-collapsible-trigger]:text-ax-text-secondary [&_.astryx-collapsible-trigger]:min-h-8 [&_.astryx-collapsible-trigger]:text-[12.5px] [&_.astryx-collapsible-trigger]:font-medium";

function StepDetails({
  step,
  activity,
  sessionId,
  durations
}: {
  step: ActivityStep;
  activity: Activity;
  sessionId: string | null;
  durations: TurnDurations | null;
}) {
  const t = useTranslations();

  switch (step.kind) {
    case "reasoning":
      if (!step.text.trim()) return null;
      return (
        <div className={PANEL_COLLAPSIBLE_CLASS}>
          <Collapsible
            trigger={t("chat_activity_reasoning")}
            chevronPosition="start"
            defaultIsOpen={false}
          >
            <div className="text-ax-text-secondary text-[12.5px] leading-relaxed">
              <MessageResponse>{step.text}</MessageResponse>
            </div>
          </Collapsible>
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
      const references = step.calls.flatMap((call) => call.references);
      // One approval line when every call got the same decision; a mixed
      // group shows each denial on its row instead.
      const approvals = new Set(step.calls.map((call) => call.approval));
      const approval = approvals.size === 1 ? (step.calls[0]?.approval ?? null) : null;
      return (
        <div className="flex flex-col gap-1.5">
          <ToolCallList
            calls={step.calls}
            files={activity.files}
            sessionId={sessionId}
            durations={durations}
          />
          {references.length > 0 && (
            <ul className="flex flex-col gap-1 text-[12.5px]">
              {references.map((reference) => {
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
          {approval && (
            <p
              className={cn(
                "flex items-center gap-1.5 text-xs",
                approval === "approved" ? "text-ax-success" : "text-ax-error"
              )}
            >
              {approval === "approved" ? (
                <ShieldCheck aria-hidden="true" className="size-3.5" />
              ) : (
                <ShieldX aria-hidden="true" className="size-3.5" />
              )}
              {approval === "approved" ? t("chat_tool_approved") : t("chat_tool_denied")}
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
      const mode = t(
        args.mode === "always"
          ? "skills_activation_mode_always"
          : "skills_activation_mode_on_demand"
      );
      return (
        <p className="text-ax-text-secondary text-[12.5px]">
          {failed
            ? t(reasonKey ?? "skill_step_failed_detail")
            : `${mode} · ${t(args.mode === "always" ? "skill_step_always_detail" : "skill_step_on_demand_detail")}`}
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

export function StepList({
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
              <StepDetails
                step={step}
                activity={activity}
                sessionId={sessionId}
                durations={durations}
              />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

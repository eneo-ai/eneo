"use client";

import type { DynamicToolUIPart, ToolUIPart } from "ai";
import {
  CheckCircleIcon,
  CircleIcon,
  ClockIcon,
  Loader2Icon,
  XCircleIcon,
  type LucideIcon
} from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Single source of truth for how a tool-call lifecycle state is shown: its
 * semantic tone (which token-driven color), its glyph, and an English fallback
 * label. Both the vendored `tool.tsx` header and the chat activity timeline
 * read from here so the status vocabulary never drifts between the two.
 */
export type ToolState = (ToolUIPart | DynamicToolUIPart)["state"];

export type StatusTone = "running" | "success" | "error" | "warning" | "neutral";

export function toolStateTone(state: ToolState): StatusTone {
  switch (state) {
    case "input-available":
      return "running";
    case "output-available":
    case "approval-responded":
      return "success";
    case "output-error":
      return "error";
    case "approval-requested":
      return "warning";
    default: // input-streaming, output-denied
      return "neutral";
  }
}

const STATE_ICON: Record<ToolState, { Icon: LucideIcon; spin?: boolean }> = {
  "input-streaming": { Icon: CircleIcon },
  "input-available": { Icon: Loader2Icon, spin: true },
  "output-available": { Icon: CheckCircleIcon },
  "output-error": { Icon: XCircleIcon },
  "output-denied": { Icon: XCircleIcon },
  "approval-requested": { Icon: ClockIcon },
  "approval-responded": { Icon: CheckCircleIcon }
};

/** English fallbacks; i18n surfaces pass a translated `label` to the badge. */
const DEFAULT_LABEL: Record<ToolState, string> = {
  "input-streaming": "Pending",
  "input-available": "Running",
  "output-available": "Completed",
  "output-error": "Error",
  "output-denied": "Denied",
  "approval-requested": "Awaiting approval",
  "approval-responded": "Approved"
};

// Tone → utility classes. Text/border read the status token; the matching /10
// tint never carries text on its own (icon + label always accompany the color).
const TONE_BADGE: Record<StatusTone, string> = {
  running: "border-primary/25 bg-primary/10 text-primary",
  success: "border-success/25 bg-success/10 text-success",
  error: "border-destructive/25 bg-destructive/10 text-destructive",
  warning: "border-warning/25 bg-warning/10 text-warning",
  neutral: "border-border bg-muted text-muted-foreground"
};

const TONE_NODE: Record<StatusTone, string> = {
  running: "border-primary/50 text-primary",
  success: "border-success/50 text-success",
  error: "border-destructive/50 text-destructive",
  warning: "border-warning/50 text-warning",
  neutral: "border-border text-muted-foreground"
};

export function ToolStateIcon({ state, className }: { state: ToolState; className?: string }) {
  const { Icon, spin } = STATE_ICON[state];
  return <Icon aria-hidden="true" className={cn(className, spin && "animate-spin")} />;
}

/** Tone-tinted status pill (icon + label). `label` overrides the English fallback. */
export function ToolStatusBadge({
  state,
  label,
  className
}: {
  state: ToolState;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_BADGE[toolStateTone(state)],
        className
      )}
    >
      <ToolStateIcon state={state} className="size-3.5" />
      {label ?? DEFAULT_LABEL[state]}
    </span>
  );
}

/** Timeline rail node: a bordered circle whose tone encodes status; caller supplies the glyph. */
export function StatusNode({
  tone,
  className,
  children,
  ...props
}: ComponentProps<"span"> & { tone: StatusTone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "bg-card relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border",
        TONE_NODE[tone],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}

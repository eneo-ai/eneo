"use client";

import { BookOpenCheck, ChevronRight, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import type { EneoUIMessage } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { skillName } from "./tool-presentation";

type ToolPart = Extract<EneoUIMessage["parts"][number], { type: "dynamic-tool" }>;

const FAILURE_REASONS: Record<string, string> = {
  unknown_key: "chat_debug_rejection_unknown_key",
  blocked: "chat_debug_rejection_blocked",
  activation_unavailable: "chat_debug_rejection_activation_unavailable",
  activation_limit_exceeded: "chat_debug_rejection_activation_limit_exceeded",
  context_limit_exceeded: "chat_debug_rejection_context_limit_exceeded",
  model_context_limit_exceeded: "chat_debug_rejection_model_context_limit_exceeded",
  token_measurement_unavailable: "chat_debug_rejection_token_measurement_unavailable",
  reserved_tool_collision: "chat_debug_rejection_reserved_tool_collision"
};

/** Shows the Skill that shaped a reply without exposing the activation payload. */
export function SkillActivationStep({ part }: { part: ToolPart }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const name = skillName(part);
  const failed = part.state === "output-error" || part.state === "output-denied";
  const args =
    part.input && typeof part.input === "object" && !Array.isArray(part.input)
      ? (part.input as Record<string, unknown>)
      : {};
  const always = args.mode === "always";
  const reasonKey = typeof args.reason === "string" ? FAILURE_REASONS[args.reason] : undefined;
  const detail = failed
    ? t(reasonKey ?? "skill_step_failed_detail")
    : t(always ? "skill_step_always_detail" : "skill_step_on_demand_detail");

  return (
    <div className="max-w-full font-sans">
      <button
        type="button"
        className={cn(
          "focus-visible:outline-ring inline-flex min-h-7 max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11",
          failed ? "bg-ax-error-muted text-ax-error" : "bg-ax-accent-muted text-ax-text-accent"
        )}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={open ? detailId : undefined}
      >
        {failed ? (
          <X aria-hidden="true" className="size-3.5 shrink-0" />
        ) : (
          <BookOpenCheck aria-hidden="true" className="size-3.5 shrink-0" />
        )}
        <span className="truncate">
          {t(failed ? "tool_activate_skill_failed" : "skill_used_in_reply", { name })}
        </span>
        <ChevronRight
          aria-hidden="true"
          className={cn("size-3 shrink-0 transition-transform", open && "rotate-90")}
        />
      </button>
      {open && (
        <div
          id={detailId}
          className="bg-ax-sunken border-ax-border rounded-ax-element mt-1.5 max-w-prose space-y-1.5 border px-3 py-2.5 text-sm"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{name}</span>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                failed ? "bg-ax-error-muted text-ax-error" : "bg-ax-muted text-ax-text-secondary"
              )}
            >
              {failed
                ? t("chat_tool_status_error")
                : t(always ? "skills_activation_mode_always" : "skills_activation_mode_on_demand")}
            </span>
          </div>
          <p className="text-ax-text-secondary text-[13px] leading-5">{detail}</p>
        </div>
      )}
    </div>
  );
}

"use client";

import { BookOpenCheck, ChevronRight, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { EneoUIMessage } from "@/lib/chat/types";
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
    <div className="max-w-full">
      <button
        type="button"
        className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
          failed
            ? "border-destructive/30 bg-destructive/10 text-destructive"
            : "border-primary/30 bg-primary/10 text-primary"
        }`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {failed ? (
          <X aria-hidden="true" className="size-3.5" />
        ) : (
          <BookOpenCheck aria-hidden="true" className="size-3.5" />
        )}
        <span className="truncate">
          {t(failed ? "tool_activate_skill_failed" : "skill_used_in_reply", { name })}
        </span>
        <ChevronRight
          aria-hidden="true"
          className={`size-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && (
        <div className="bg-muted/40 mt-1.5 max-w-prose space-y-1.5 rounded-lg border px-3 py-2.5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{name}</span>
            <Badge variant={failed ? "destructive" : "outline"}>
              {failed
                ? t("chat_tool_status_error")
                : t(always ? "skills_activation_mode_always" : "skills_activation_mode_on_demand")}
            </Badge>
          </div>
          <p className="text-muted-foreground text-[13px] leading-5">{detail}</p>
        </div>
      )}
    </div>
  );
}

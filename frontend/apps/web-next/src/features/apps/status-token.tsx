"use client";

import { Token, type TokenColor } from "@astryxdesign/core/Token";
import { Check, Circle, Clock, Hourglass, X, type LucideIcon } from "lucide-react";
import { useTranslations } from "use-intl";
import type { AppRunStatus } from "./apps";

const TOKENS: Partial<
  Record<AppRunStatus, { label: string; color: TokenColor; Icon: LucideIcon }>
> = {
  complete: { label: "complete", color: "green", Icon: Check },
  failed: { label: "failed", color: "red", Icon: X },
  "in progress": { label: "in_progress", color: "blue", Icon: Hourglass },
  queued: { label: "queued", color: "gray", Icon: Clock }
};

/** The visible run-status label, shared by tokens and result sorting. */
export function appRunStatusLabel(status: AppRunStatus, t: (key: string) => string): string {
  const token = TOKENS[status];
  return token ? t(token.label) : status;
}

/**
 * A run's status in words: a small Token with a still icon, no pulsing, as a
 * run can take minutes. Not a live region; the job toast every run raises
 * says when it finished or failed.
 */
export function AppRunStatusToken({ status }: { status: AppRunStatus }) {
  const t = useTranslations();
  const token = TOKENS[status];
  const Icon = token?.Icon ?? Circle;
  return (
    <Token
      size="sm"
      color={token?.color ?? "gray"}
      label={appRunStatusLabel(status, t)}
      icon={<Icon className="size-3.5" aria-hidden="true" />}
    />
  );
}

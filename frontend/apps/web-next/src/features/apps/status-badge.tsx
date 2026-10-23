"use client";

import { Check, Circle, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { AppRunStatus } from "./apps";

const STYLES: Record<string, string> = {
  complete: "border-success/30 bg-success/10 text-success",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
  "in progress": "border-primary/30 bg-primary/10 text-primary",
  queued: "border-border bg-muted text-muted-foreground"
};

/** Run status pill (icon-only, or icon + label in `full` variant). */
export function AppRunStatusBadge({
  status,
  variant = "icon"
}: {
  status: AppRunStatus;
  variant?: "icon" | "full";
}) {
  const t = useTranslations();

  const label =
    status === "complete"
      ? t("complete")
      : status === "in progress"
        ? t("in_progress")
        : status === "failed"
          ? t("failed")
          : status === "queued"
            ? t("queued")
            : status;

  return (
    <div
      role="status"
      aria-label={label}
      className={cn(
        "flex min-h-7 w-fit min-w-7 items-center justify-center gap-2 rounded-md border px-2 py-0.5",
        STYLES[status] ?? "border-border bg-muted text-muted-foreground"
      )}
    >
      {status === "complete" ? (
        <Check className="size-4" aria-hidden="true" />
      ) : status === "in progress" ? (
        <span className="relative size-2.5" aria-hidden="true">
          <span className="absolute size-full animate-ping rounded-full bg-current opacity-75" />
          <span className="absolute size-full rounded-full bg-current" />
        </span>
      ) : status === "failed" ? (
        <X className="size-4" aria-hidden="true" />
      ) : (
        <Circle className="size-3" aria-hidden="true" />
      )}
      {variant === "full" && <span className="text-xs font-medium">{label}</span>}
    </div>
  );
}

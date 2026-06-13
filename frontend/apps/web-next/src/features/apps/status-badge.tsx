"use client";

import { Check, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { AppRunStatus } from "./apps";

const STYLES: Record<string, string> = {
  complete:
    "border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300",
  failed:
    "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  "in progress":
    "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
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
      className={cn(
        "flex min-h-7 w-fit min-w-7 items-center justify-center gap-2 rounded-md border px-2 py-0.5",
        STYLES[status] ?? "border-border bg-muted text-muted-foreground"
      )}
    >
      {status === "complete" ? (
        <Check className="size-4" aria-label={t("finished")} />
      ) : status === "in progress" ? (
        <span className="relative size-2.5" aria-label={t("running")}>
          <span className="absolute size-full animate-ping rounded-full bg-current opacity-75" />
          <span className="absolute size-full rounded-full bg-current" />
        </span>
      ) : status === "failed" ? (
        <X className="size-4" aria-label={t("failed")} />
      ) : null}
      {variant === "full" && <span className="text-xs font-medium">{label}</span>}
    </div>
  );
}

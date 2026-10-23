"use client";

import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { BadgeVariant } from "./use-policy-draft";

/**
 * Shared shell for the governance policy sections (models, MCP, prompt): card
 * frame, icon tile, heading + status badge and divider, so the three sections
 * stay visually identical and there is a single place to evolve that layout.
 */
export function PolicySection({
  id,
  title,
  description,
  summary,
  summaryVariant,
  icon,
  children
}: {
  /** Stable key used to build the aria ids. */
  id: string;
  title: string;
  description: string;
  summary: string;
  summaryVariant: BadgeVariant;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`section-${id}-title`}
      aria-describedby={`section-${id}-summary`}
      className="bg-card overflow-hidden rounded-xl border"
    >
      <header className="flex items-start gap-4 border-b p-5">
        <div
          className="bg-muted text-foreground flex size-10 shrink-0 items-center justify-center rounded-lg"
          aria-hidden="true"
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`section-${id}-title`} className="text-foreground text-base font-semibold">
              {title}
            </h2>
            <Badge id={`section-${id}-summary`} variant={summaryVariant}>
              {summary}
            </Badge>
          </div>
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        </div>
      </header>
      <div className="space-y-4 p-5">{children}</div>
    </section>
  );
}

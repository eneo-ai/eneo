"use client";

import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";

/**
 * Status dot plus label for knowledge tables (crawl state, update interval,
 * webhook), with optional detail under it: why a crawl failed, what failed,
 * when the next crawl runs. The detail is visible text, so keyboard, touch
 * and screen reader users get it too (no hover-only tooltip).
 */
export function KnowledgeLabel({
  tone,
  label,
  detail,
  isPulsing
}: {
  tone: StatusTone;
  label: string;
  detail?: ReactNode;
  /** Pulse the dot for work in progress (respects reduced motion). */
  isPulsing?: boolean;
}) {
  return (
    <span className="inline-flex min-w-0 flex-col gap-0.5">
      <StatusLabel status={tone} label={label} isPulsing={isPulsing} />
      {detail ? (
        <span className="text-ax-text-secondary ps-3.5 text-xs break-words">{detail}</span>
      ) : null}
    </span>
  );
}

/** First cell of a knowledge row: a decorative type tile and the link to the item. */
export function KnowledgeNameCell({
  icon: Icon,
  href,
  children
}: {
  icon: LucideIcon;
  href: string;
  children: ReactNode;
}) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <span
        aria-hidden="true"
        className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-7 shrink-0 items-center justify-center"
      >
        <Icon className="size-4" />
      </span>
      <Link
        href={href}
        className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 min-w-0 items-center font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
      >
        {children}
      </Link>
    </span>
  );
}

/** Filter field and the tab's actions above a knowledge table (which sorts by its headers). */
export function KnowledgeTableControls({
  filterValue,
  onFilterChange,
  filterLabel,
  filterPlaceholder,
  resultCount,
  children
}: {
  filterValue: string;
  onFilterChange: (value: string) => void;
  /** Accessible name of the filter field ("Filtrera samlingar"). */
  filterLabel: string;
  filterPlaceholder: string;
  /** Rows matching the filter, announced while a query is typed. */
  resultCount: number;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
      <ResourceFilterInput
        value={filterValue}
        onChange={onFilterChange}
        label={filterLabel}
        placeholder={filterPlaceholder}
        resultCount={resultCount}
        className="sm:w-72"
      />
      {children ? <div className="flex flex-wrap justify-end gap-2">{children}</div> : null}
    </div>
  );
}

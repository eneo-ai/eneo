"use client";

import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { useId, type ReactNode } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";

export type KnowledgeSortOption = {
  value: string;
  label: string;
};

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

/** Filter field, an optional sort select and the tab's actions above a knowledge table. */
export function KnowledgeTableControls({
  filterValue,
  onFilterChange,
  filterLabel,
  filterPlaceholder,
  sortLabel,
  sortValue,
  onSortChange,
  sortOptions,
  children
}: {
  filterValue: string;
  onFilterChange: (value: string) => void;
  /** Accessible name of the filter field; defaults to "Sök". */
  filterLabel?: string;
  filterPlaceholder: string;
  /** Sort select; omit when the table sorts by its column headers. */
  sortLabel?: string;
  sortValue?: string;
  onSortChange?: (value: string) => void;
  sortOptions?: KnowledgeSortOption[];
  children?: ReactNode;
}) {
  const sortLabelId = useId();

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <ResourceFilterInput
          value={filterValue}
          onChange={onFilterChange}
          label={filterLabel}
          placeholder={filterPlaceholder}
          className="sm:w-72"
        />
        {sortOptions && sortValue !== undefined && onSortChange ? (
          <div className="flex flex-col gap-1">
            <span id={sortLabelId} className="text-ax-text-secondary text-xs font-medium">
              {sortLabel}
            </span>
            <Select value={sortValue} onValueChange={onSortChange}>
              <SelectTrigger aria-labelledby={sortLabelId} className="w-full sm:w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="start">
                {sortOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
      </div>
      {children ? <div className="flex flex-wrap justify-end gap-2">{children}</div> : null}
    </div>
  );
}

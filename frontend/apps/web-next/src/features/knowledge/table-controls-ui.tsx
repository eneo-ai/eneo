"use client";

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

export function KnowledgeTableControls({
  filterValue,
  onFilterChange,
  filterPlaceholder,
  sortLabel,
  sortValue,
  onSortChange,
  sortOptions,
  children
}: {
  filterValue: string;
  onFilterChange: (value: string) => void;
  filterPlaceholder: string;
  sortLabel: string;
  sortValue: string;
  onSortChange: (value: string) => void;
  sortOptions: KnowledgeSortOption[];
  children?: ReactNode;
}) {
  const sortLabelId = useId();

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <ResourceFilterInput
          value={filterValue}
          onChange={onFilterChange}
          placeholder={filterPlaceholder}
        />
        <span id={sortLabelId} className="sr-only">
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
      {children ? <div className="flex justify-end gap-2">{children}</div> : null}
    </div>
  );
}

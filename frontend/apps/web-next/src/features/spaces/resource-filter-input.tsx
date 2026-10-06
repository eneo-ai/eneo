"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { TextInput } from "@/components/astryx/text-input";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, type Ref } from "react";
import { cn } from "@/lib/utils";

/**
 * Filter field above a resource grid or table: Astryx TextInput with a search
 * icon and a clear button. The label names what is filtered ("Filtrera
 * samlingar") and is visually hidden. While a query is typed, the number of
 * matches is announced politely (WCAG 4.1.3): the list changes silently, and
 * an empty-result message that appears with its text is not announced
 * reliably.
 */
export function ResourceFilterInput({
  value,
  onChange,
  placeholder,
  label,
  resultCount,
  inputRef,
  className
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** Accessible name: what the field filters. */
  label: string;
  /** Items matching `value`; announced whenever the query or the count changes. */
  resultCount: number;
  /** Optional focus target for an empty state's clear action. */
  inputRef?: Ref<HTMLInputElement>;
  className?: string;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const query = value.trim();
  const announced = useRef(false);

  useEffect(() => {
    if (query) {
      announce(t("space_filter_result_count", { count: resultCount }));
      announced.current = true;
    } else if (announced.current) {
      // Clearing the query drops a count that no longer applies.
      announce("");
      announced.current = false;
    }
  }, [announce, query, resultCount, t]);

  return (
    <div className={cn("w-full max-w-sm", className)}>
      <TextInput
        ref={inputRef}
        label={label}
        isLabelHidden
        value={value}
        onChange={(next) => onChange(next)}
        placeholder={placeholder}
        startIcon={Search}
        hasClear
        width="100%"
      />
    </div>
  );
}

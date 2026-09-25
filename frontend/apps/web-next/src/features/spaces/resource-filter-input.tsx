"use client";

import { TextInput } from "@astryxdesign/core/TextInput";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/**
 * Filter field above a resource grid or table: Astryx TextInput with a search
 * icon and a clear button. The label is visually hidden; it defaults to "Sök".
 */
export function ResourceFilterInput({
  value,
  onChange,
  placeholder,
  label,
  className
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** Accessible name; defaults to the generic "Sök". */
  label?: string;
  className?: string;
}) {
  const t = useTranslations();

  return (
    <div className={cn("w-full max-w-sm", className)}>
      <TextInput
        label={label ?? t("search")}
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

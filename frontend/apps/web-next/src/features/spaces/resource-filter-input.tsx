"use client";

import { Search, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ResourceFilterInput({
  value,
  onChange,
  placeholder
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  const t = useTranslations();

  return (
    <div className="relative max-w-sm">
      <Search
        aria-hidden="true"
        className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2"
      />
      <Input
        value={value}
        aria-label={t("search")}
        placeholder={placeholder}
        className="pr-9 pl-9"
        onChange={(event) => onChange(event.target.value)}
      />
      {value && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="text-muted-foreground hover:text-foreground absolute top-1/2 right-1 size-7 -translate-y-1/2"
          aria-label={t("clear")}
          onClick={() => onChange("")}
        >
          <X className="size-4" aria-hidden="true" />
        </Button>
      )}
    </div>
  );
}

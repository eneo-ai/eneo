"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { type KeyboardEvent, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

/** Comma/Enter chip input bound to a string[] (e.g. MCP server tags). */
export function TagInput({
  value,
  onChange,
  onBlurCommit,
  id,
  placeholder
}: {
  value: string[];
  onChange: (next: string[]) => void;
  /** Called after a blur that doesn't add a tag, so callers can autosave. */
  onBlurCommit?: () => void;
  id?: string;
  placeholder?: string;
}) {
  const t = useTranslations();
  const [draft, setDraft] = useState("");

  const add = (raw: string): boolean => {
    const tag = raw.trim();
    setDraft("");
    if (!tag || value.includes(tag)) return false;
    onChange([...value, tag]);
    return true;
  };

  const removeAt = (index: number) => onChange(value.filter((_, i) => i !== index));

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add(draft);
    } else if (event.key === "Backspace" && draft === "" && value.length > 0) {
      removeAt(value.length - 1);
    }
  };

  return (
    <div>
      {value.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {value.map((tag, index) => (
            <Badge key={tag} variant="secondary" className="gap-1 pr-1">
              {tag}
              <button
                type="button"
                onClick={() => removeAt(index)}
                aria-label={t("mcp_remove_tag", { tag })}
                className="hover:bg-foreground/10 -mr-0.5 rounded-full p-0.5"
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        id={id}
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => {
          const added = add(draft);
          if (!added) onBlurCommit?.();
        }}
      />
    </div>
  );
}

"use client";

import { Check, Sparkles } from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { useTranslations } from "next-intl";
import { useId, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import {
  TEMPLATE_ICON_NAMES,
  TemplateIcon,
  compactIconName,
  storedTemplateIconName,
  templateIconName
} from "@/features/templates/template-icon";
import { cn } from "@/lib/utils";

/** Offered before anything is searched (the Svelte picker's list). */
const POPULAR_ICONS = [
  "rocket",
  "sparkles",
  "zap",
  "star",
  "heart",
  "message-square",
  "mail",
  "bell",
  "calendar",
  "clock",
  "user",
  "users",
  "building",
  "house",
  "briefcase",
  "shopping-cart",
  "credit-card",
  "dollar-sign",
  "file-text",
  "image",
  "video",
  "music",
  "code",
  "database"
] as const satisfies readonly IconName[];

/** Search results drawn at once; refining the search finds the rest. */
const MAX_RESULTS = 200;

/**
 * The template's Lucide icon: a button beside the name shows the chosen icon
 * (or a sparkle when there is none) and opens a dialog with popular icons, a
 * search over every icon name and a way to clear the choice. `value` is the
 * stored kebab-case name.
 */
export function TemplateIconPicker({
  value,
  onChange
}: {
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations();
  const popularId = useId();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const selected = templateIconName(value);
  const query = compactIconName(search);
  const results = useMemo(
    () =>
      query ? TEMPLATE_ICON_NAMES.filter((name) => compactIconName(name).includes(query)) : [],
    [query]
  );

  function changeOpen(next: boolean) {
    setOpen(next);
    if (!next) setSearch("");
  }

  function choose(name: string | null) {
    onChange(name);
    changeOpen(false);
  }

  const label = value ? t("change_icon_current", { iconName: value }) : t("choose_template_icon");

  function iconButton(name: IconName) {
    const isSelected = value !== null && compactIconName(name) === compactIconName(value);
    return (
      <li key={name}>
        <button
          type="button"
          aria-label={t("select_icon", { iconName: name })}
          aria-pressed={isSelected}
          title={name}
          onClick={() => choose(storedTemplateIconName(name))}
          className={cn(
            "rounded-ax-inner focus-visible:outline-ring relative flex size-11 items-center justify-center border-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2",
            isSelected ? "border-primary bg-accent" : "hover:bg-muted border-transparent"
          )}
        >
          <TemplateIcon name={name} className="size-5" />
          {isSelected && (
            <Check
              aria-hidden="true"
              className="bg-primary text-primary-foreground absolute -end-1 -top-1 size-4 rounded-full p-0.5"
            />
          )}
        </button>
      </li>
    );
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={cn("size-11 shrink-0", !selected && "border-dashed")}
          aria-label={label}
          title={label}
        >
          {selected ? (
            <TemplateIcon name={selected} className="size-5" />
          ) : (
            <Sparkles aria-hidden="true" className="text-muted-foreground size-5" />
          )}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("choose_an_icon")}</DialogTitle>
          <DialogDescription>
            {query ? t("icons_found", { count: results.length }) : t("search_to_find_icon")}
          </DialogDescription>
        </DialogHeader>
        <ResourceFilterInput
          value={search}
          onChange={setSearch}
          label={t("search_icons")}
          placeholder={t("search_icons")}
          resultCount={results.length}
          className="max-w-none"
        />
        {!query ? (
          <section className="flex flex-col gap-2" aria-labelledby={popularId}>
            <h3
              id={popularId}
              className="text-muted-foreground text-xs font-medium tracking-wide uppercase"
            >
              {t("popular_icons")}
            </h3>
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(2.75rem,1fr))] gap-2">
              {POPULAR_ICONS.map(iconButton)}
            </ul>
          </section>
        ) : results.length > 0 ? (
          <div className="flex flex-col gap-2">
            <ul className="grid max-h-96 grid-cols-[repeat(auto-fill,minmax(2.75rem,1fr))] gap-2 overflow-y-auto p-1">
              {results.slice(0, MAX_RESULTS).map(iconButton)}
            </ul>
            {results.length > MAX_RESULTS && (
              <p className="text-muted-foreground text-center text-xs">
                {t("showing_first_icons", { total: results.length })}
              </p>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground py-8 text-center text-sm">
            {t("no_icons_found", { query: search.trim() })}
          </p>
        )}
        {/* The corner ✕ and Escape close it; clearing is the one footer action. */}
        {value && (
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => choose(null)}>
              {t("clear_selection")}
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

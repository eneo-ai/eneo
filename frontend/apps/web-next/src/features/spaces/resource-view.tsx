"use client";

import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu, DropdownMenuItem } from "@astryxdesign/core/DropdownMenu";
import type { UseTableSortableConfig } from "@astryxdesign/core/Table";
import { ArrowDown, ArrowUp, Check, LayoutGrid, List } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";

export type ResourceView = "cards" | "list";
type Surface = "apps" | "assistants" | "spaces";

/** One best-effort display preference for each resource surface. */
export function useResourceView(surface: Surface, defaultView: ResourceView) {
  const key = `eneo:resource-view:${surface}`;
  const [view, setView] = useState<ResourceView>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === "cards" || stored === "list" ? stored : defaultView;
    } catch {
      return defaultView;
    }
  });
  const chooseView = (next: ResourceView) => {
    setView(next);
    try {
      window.localStorage.setItem(key, next);
    } catch {
      /* The view remains usable when storage is unavailable. */
    }
  };
  return { view, chooseView };
}

/** Display controls share the table's sort state, including while cards are shown. */
export function ResourceViewControls<Key extends string>({
  view,
  onViewChange,
  sortConfig,
  options
}: {
  view: ResourceView;
  onViewChange: (view: ResourceView) => void;
  sortConfig: UseTableSortableConfig<Key>;
  options: { key: Key; label: string }[];
}) {
  const t = useTranslations();
  const phone = useMediaMatch(PHONE_QUERY);
  const selected = sortConfig.sort[0];
  const current = options.find((option) => option.key === selected?.sortKey) ?? options[0];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DropdownMenu
        button={{
          label: `${t("resource_sort")}: ${current?.label ?? ""}`,
          icon:
            selected?.direction === "descending" ? (
              <ArrowDown aria-hidden="true" />
            ) : (
              <ArrowUp aria-hidden="true" />
            )
        }}
      >
        {options.flatMap((option) =>
          (["ascending", "descending"] as const).map((direction) => (
            <DropdownMenuItem
              key={`${option.key}-${direction}`}
              label={`${option.label} · ${t(direction === "ascending" ? "resource_sort_ascending" : "resource_sort_descending")}`}
              icon={
                selected?.sortKey === option.key && selected.direction === direction
                  ? Check
                  : undefined
              }
              onClick={() => sortConfig.onSortChange([{ sortKey: option.key, direction }])}
            />
          ))
        )}
      </DropdownMenu>
      {phone !== true && (
        <div role="group" aria-label={t("resource_view")} className="flex gap-1 max-md:hidden">
          <Button
            label={t("list")}
            icon={<List aria-hidden="true" />}
            variant={view === "list" ? "secondary" : "ghost"}
            aria-pressed={view === "list"}
            onClick={() => onViewChange("list")}
          />
          <Button
            label={t("cards")}
            icon={<LayoutGrid aria-hidden="true" />}
            variant={view === "cards" ? "secondary" : "ghost"}
            aria-pressed={view === "cards"}
            onClick={() => onViewChange("cards")}
          />
        </div>
      )}
    </div>
  );
}

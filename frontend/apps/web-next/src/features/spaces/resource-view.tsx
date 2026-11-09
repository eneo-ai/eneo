import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import type { UseTableSortableConfig } from "@astryxdesign/core/Table";
import { ArrowDown, ArrowUp, ArrowUpDown, LayoutGrid, List } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";

export type ResourceView = "cards" | "list";
type Surface = "apps" | "assistants" | "flows" | "spaces";

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
  const phone = usePhoneScreen();
  const selected = sortConfig.sort[0];
  const choices = options.flatMap((option) =>
    (["ascending", "descending"] as const).map((direction) => ({
      sortKey: option.key,
      direction,
      value: `${option.key}:${direction}`,
      label: `${option.label} · ${t(direction === "ascending" ? "resource_sort_ascending" : "resource_sort_descending")}`
    }))
  );
  const current = choices.find(
    (choice) => choice.sortKey === selected?.sortKey && choice.direction === selected.direction
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DropdownMenu
        button={{
          label: `${t("resource_sort")}: ${current?.label ?? options[0]?.label ?? ""}`,
          // Beside the filter on a phone; the menu says what is chosen.
          isIconOnly: phone,
          // Alone, an arrow reads as a direction; both arrows read as sorting.
          icon: phone ? (
            <ArrowUpDown aria-hidden="true" />
          ) : selected?.direction === "descending" ? (
            <ArrowDown aria-hidden="true" />
          ) : (
            <ArrowUp aria-hidden="true" />
          )
        }}
        hasChevron={!phone}
      >
        <DropdownMenuRadioGroup
          label={t("resource_sort")}
          value={current?.value}
          onChange={(value) => {
            const choice = choices.find((choice) => choice.value === value);
            if (choice)
              sortConfig.onSortChange([{ sortKey: choice.sortKey, direction: choice.direction }]);
          }}
        >
          {choices.map((choice) => (
            <DropdownMenuRadioItem key={choice.value} value={choice.value} label={choice.label} />
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenu>
      {!phone && (
        <div role="group" aria-label={t("resource_view")} className="flex gap-1">
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

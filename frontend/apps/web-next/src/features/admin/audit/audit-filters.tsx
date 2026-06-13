"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ListFilter, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import {
  actionLabel,
  auditActionConfigQueryOptions,
  categoryLabel,
  type ActionType,
  type AuditFilters,
  type CategoryType
} from "./audit";

function ActionMultiSelect({
  selected,
  onChange
}: {
  selected: ActionType[];
  onChange: (actions: ActionType[]) => void;
}) {
  const t = useTranslations();
  const { data: actions = [] } = useQuery(auditActionConfigQueryOptions(browserApi));

  const grouped = useMemo(() => {
    const map = new Map<CategoryType, ActionType[]>();
    for (const config of actions) {
      const list = map.get(config.category) ?? [];
      list.push(config.action);
      map.set(config.category, list);
    }
    return [...map.entries()];
  }, [actions]);

  const selectedSet = new Set(selected);

  function toggle(action: ActionType) {
    onChange(
      selectedSet.has(action) ? selected.filter((item) => item !== action) : [...selected, action]
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="justify-start gap-2">
          <ListFilter className="size-4" />
          {selected.length === 0
            ? t("audit_all_actions")
            : t("audit_actions_selected", { count: selected.length })}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <Command>
          <CommandInput placeholder={t("search")} />
          <CommandList>
            <CommandEmpty>{t("no_results")}</CommandEmpty>
            {grouped.map(([category, categoryActions]) => (
              <CommandGroup key={category} heading={categoryLabel(t, category)}>
                {categoryActions.map((action) => (
                  <CommandItem
                    key={action}
                    value={`${actionLabel(t, action)} ${action}`}
                    onSelect={() => toggle(action)}
                  >
                    <Check
                      className={cn(
                        "size-4",
                        selectedSet.has(action) ? "opacity-100" : "opacity-0"
                      )}
                    />
                    {actionLabel(t, action)}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Audit log filter bar: actions, date range, free-text search. */
export function AuditFilterBar({
  filters,
  onChange
}: {
  filters: AuditFilters;
  onChange: (next: Partial<AuditFilters>) => void;
}) {
  const t = useTranslations();
  const hasFilters =
    filters.actions.length > 0 || filters.from_date || filters.to_date || filters.search;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs">{t("action")}</Label>
          <ActionMultiSelect
            selected={filters.actions}
            onChange={(actions) => onChange({ actions })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="audit-from" className="text-xs">
            {t("from")}
          </Label>
          <Input
            id="audit-from"
            type="date"
            className="w-40"
            value={filters.from_date ?? ""}
            onChange={(event) => onChange({ from_date: event.target.value || undefined })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="audit-to" className="text-xs">
            {t("to")}
          </Label>
          <Input
            id="audit-to"
            type="date"
            className="w-40"
            value={filters.to_date ?? ""}
            onChange={(event) => onChange({ to_date: event.target.value || undefined })}
          />
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <Label htmlFor="audit-search" className="text-xs">
            {t("search")}
          </Label>
          <Input
            id="audit-search"
            value={filters.search}
            placeholder={t("search")}
            onChange={(event) => onChange({ search: event.target.value })}
          />
        </div>
        {hasFilters && (
          <Button
            variant="ghost"
            onClick={() =>
              onChange({ actions: [], from_date: undefined, to_date: undefined, search: "" })
            }
          >
            <X className="size-4" /> {t("clear")}
          </Button>
        )}
      </div>

      {filters.actions.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {filters.actions.map((action) => (
            <Badge key={action} variant="secondary" className="gap-1">
              {actionLabel(t, action)}
              <button
                type="button"
                aria-label={t("remove")}
                onClick={() =>
                  onChange({ actions: filters.actions.filter((item) => item !== action) })
                }
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

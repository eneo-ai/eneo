"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ListFilter, User, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
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
import { adminUsersQueryOptions } from "@/features/admin/users/users";
import {
  actionLabel,
  auditActionConfigQueryOptions,
  categoryLabel,
  type ActionType,
  type AuditFilters,
  type CategoryType
} from "./audit";

/** Actor-by-user filter: search users and pin the per-user (GDPR) log view. */
function UserFilter({
  userId,
  userLabel,
  onChange
}: {
  userId?: string;
  userLabel?: string;
  onChange: (next: Partial<AuditFilters>) => void;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { data } = useQuery({
    ...adminUsersQueryOptions(browserApi, {
      page: 1,
      stateFilter: "active",
      search: search.trim()
    }),
    enabled: open
  });
  const users = data?.items ?? [];

  if (userId) {
    return (
      <Badge variant="secondary" className="h-9 gap-1 px-3 text-sm">
        <User className="size-3.5" />
        {userLabel}
        <button
          type="button"
          aria-label={t("audit_clear_user_filter")}
          onClick={() => onChange({ userId: undefined, userLabel: undefined })}
        >
          <X className="size-3" />
        </button>
      </Badge>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="justify-start gap-2">
          <User className="size-4" />
          {t("audit_user_filter")}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder={t("search")} value={search} onValueChange={setSearch} />
          <CommandList>
            <CommandEmpty>{t("no_results")}</CommandEmpty>
            <CommandGroup>
              {users.map((member) => (
                <CommandItem
                  key={member.id}
                  value={member.id}
                  onSelect={() => {
                    onChange({ userId: member.id, userLabel: member.email });
                    setOpen(false);
                  }}
                >
                  {member.email}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

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
  const filteringByUser = Boolean(filters.userId);
  const hasFilters =
    filters.actions.length > 0 ||
    filters.from_date ||
    filters.to_date ||
    filters.search ||
    filteringByUser;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs">{t("audit_user_filter")}</Label>
          <UserFilter userId={filters.userId} userLabel={filters.userLabel} onChange={onChange} />
        </div>
        {!filteringByUser && (
          <div className="flex flex-col gap-1">
            <Label className="text-xs">{t("action")}</Label>
            <ActionMultiSelect
              selected={filters.actions}
              onChange={(actions) => onChange({ actions })}
            />
          </div>
        )}
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
        {!filteringByUser && (
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
        )}
        {hasFilters && (
          <Button
            variant="ghost"
            onClick={() =>
              onChange({
                actions: [],
                from_date: undefined,
                to_date: undefined,
                search: "",
                userId: undefined,
                userLabel: undefined
              })
            }
          >
            <X className="size-4" /> {t("clear")}
          </Button>
        )}
      </div>

      {!filteringByUser && filters.actions.length > 0 && (
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

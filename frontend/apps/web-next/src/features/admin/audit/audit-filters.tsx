"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Button } from "@astryxdesign/core/Button";
import {
  DateRangeInput,
  type DateRange,
  type DateRangePreset
} from "@astryxdesign/core/DateRangeInput";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { MultiSelector, type MultiSelectorOptionType } from "@astryxdesign/core/MultiSelector";
import { Popover } from "@astryxdesign/core/Popover";
import { Token } from "@astryxdesign/core/Token";
import { Typeahead, type SearchableItem, type SearchSource } from "@astryxdesign/core/Typeahead";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListFilter, User, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { browserApi } from "@/lib/api/browser";
import { adminUsersQueryOptions, MIN_SEARCH_LENGTH } from "@/features/admin/users/users";
import {
  actionLabel,
  auditActionConfigQueryOptions,
  categoryLabel,
  type ActionType,
  type AuditFilters,
  type CategoryType
} from "./audit";

type IsoDate = DateRange["start"];
type Translate = ReturnType<typeof useTranslations>;
type OnChange = (next: Partial<AuditFilters>) => void;

const PRESET_DAYS = [
  { days: 7, key: "audit_last_7_days" },
  { days: 30, key: "audit_last_30_days" },
  { days: 90, key: "audit_last_90_days" }
] as const;

/** A local calendar date as YYYY-MM-DD. */
function isoDate(date: Date): IsoDate {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}` as IsoDate;
}

function isIsoDate(value: string | undefined): value is IsoDate {
  return value !== undefined && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function daysAgo(days: number): Date {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date;
}

/** "25 sep. 2026" for a YYYY-MM-DD string; noon UTC so no time zone moves the day. */
function formatDate(date: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric"
  }).format(new Date(`${date}T12:00:00Z`));
}

/** The filters the "Filter" button counts: user, each action and the period (search is visible). */
export function activeFilterCount(filters: AuditFilters): number {
  return (
    (filters.userId ? 1 : 0) +
    filters.actions.length +
    (filters.from_date || filters.to_date ? 1 : 0)
  );
}

const CLEARED: Partial<AuditFilters> = {
  actions: [],
  from_date: undefined,
  to_date: undefined,
  search: "",
  userId: undefined,
  userLabel: undefined
};

/** Actor-by-user filter: finds a user by email and pins the per-user (GDPR) log view. */
function UserField({
  userId,
  userLabel,
  onChange
}: {
  userId?: string;
  userLabel?: string;
  onChange: OnChange;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const source = useMemo<SearchSource<SearchableItem>>(
    () => ({
      search: async (query) => {
        const search = query.trim();
        if (search.length < MIN_SEARCH_LENGTH) return [];
        const page = await queryClient.query(
          adminUsersQueryOptions(browserApi, { page: 1, stateFilter: "active", search })
        );
        return page.items.map((member) => ({ id: member.id, label: member.email }));
      },
      bootstrap: () => []
    }),
    [queryClient]
  );

  return (
    <Typeahead
      label={t("user")}
      description={t("audit_user_search_hint", { count: MIN_SEARCH_LENGTH })}
      placeholder={t("audit_search_placeholder_user")}
      searchSource={source}
      value={userId ? { id: userId, label: userLabel ?? userId } : null}
      onChange={(item) =>
        onChange(
          item
            ? // The per-user endpoint takes only a date range: the other filters go.
              { userId: item.id, userLabel: item.label, actions: [], search: "" }
            : { userId: undefined, userLabel: undefined }
        )
      }
      minQueryLength={MIN_SEARCH_LENGTH}
      emptySearchResultsText={t("audit_user_search_empty")}
      width="100%"
    />
  );
}

function ActionField({
  selected,
  onChange
}: {
  selected: ActionType[];
  onChange: (actions: ActionType[]) => void;
}) {
  const t = useTranslations();
  const { data: actions = [] } = useQuery(auditActionConfigQueryOptions(browserApi));

  const options = useMemo<MultiSelectorOptionType[]>(() => {
    const byCategory = new Map<CategoryType, ActionType[]>();
    for (const config of actions) {
      const list = byCategory.get(config.category) ?? [];
      list.push(config.action);
      byCategory.set(config.category, list);
    }
    return [...byCategory.entries()].map(([category, categoryActions]) => ({
      type: "section",
      title: categoryLabel(t, category),
      options: categoryActions.map((action) => ({ value: action, label: actionLabel(t, action) }))
    }));
  }, [actions, t]);

  return (
    <MultiSelector
      label={t("action")}
      options={options}
      value={selected}
      onChange={(values) => onChange(values as ActionType[])}
      placeholder={t("audit_all_actions")}
      triggerDisplay="count"
      hasSearch
      searchPlaceholder={t("search")}
      emptySearchText={t("no_results")}
      presentation="popover"
      width="100%"
    />
  );
}

function PeriodField({ from, to, onChange }: { from?: string; to?: string; onChange: OnChange }) {
  const t = useTranslations();
  const presets = useMemo<DateRangePreset[]>(
    () =>
      PRESET_DAYS.map(({ days, key }) => ({
        label: t(key),
        getRange: () => ({ start: isoDate(daysAgo(days)), end: isoDate(new Date()) })
      })),
    [t]
  );
  const value: DateRange | null =
    isIsoDate(from) && isIsoDate(to) ? { start: from, end: to } : null;

  return (
    <DateRangeInput
      label={t("audit_period_label")}
      placeholder={t("audit_period_placeholder")}
      value={value}
      onChange={(next) => onChange({ from_date: next?.start, to_date: next?.end })}
      presets={presets}
      numberOfMonths={1}
      weekStartsOn="mon"
      width="100%"
    />
  );
}

/** The fields behind the "Filter" button; each change applies at once. */
function AuditFilterFields({
  filters,
  onChange,
  onDone
}: {
  filters: AuditFilters;
  onChange: OnChange;
  onDone: () => void;
}) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-4">
      <p className="text-ax-text-secondary text-sm">{t("audit_filters_description")}</p>
      <UserField userId={filters.userId} userLabel={filters.userLabel} onChange={onChange} />
      {!filters.userId && (
        <ActionField selected={filters.actions} onChange={(actions) => onChange({ actions })} />
      )}
      <PeriodField from={filters.from_date} to={filters.to_date} onChange={onChange} />
      <div className="flex justify-end">
        <Button variant="primary" label={t("done")} onClick={onDone} />
      </div>
    </div>
  );
}

/** The "Filter" button: a popover beside it on wide screens, a bottom sheet on phones. */
function FilterButton({ filters, onChange }: { filters: AuditFilters; onChange: OnChange }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const wide = useMediaQuery("(min-width: 768px)");
  const count = activeFilterCount(filters);
  const label = count > 0 ? t("audit_filters_button_count", { count }) : t("audit_filters_button");
  const fields = (
    <AuditFilterFields filters={filters} onChange={onChange} onDone={() => setOpen(false)} />
  );

  if (wide) {
    return (
      <Popover
        isOpen={open}
        onOpenChange={setOpen}
        placement="below"
        alignment="end"
        width={360}
        label={t("audit_filters_button")}
        closeButtonLabel={t("close")}
        // Mounted only while open: closed, Astryx keeps the popover element in
        // the DOM, and the fields' empty listboxes would be scanned as visible.
        content={open ? <div className="p-1">{fields}</div> : null}
      >
        {/* Popover attaches the click and aria-expanded to the button inside. */}
        <Button label={label} icon={<ListFilter aria-hidden="true" />} />
      </Popover>
    );
  }
  return (
    <>
      <Button
        label={label}
        icon={<ListFilter aria-hidden="true" />}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      />
      <BottomSheet
        isOpen={open}
        onOpenChange={setOpen}
        label={t("audit_filters_button")}
        height="tall"
      >
        <div className="p-4">{fields}</div>
      </BottomSheet>
    </>
  );
}

type Chip = { key: string; label: string; icon?: React.ReactNode; remove: Partial<AuditFilters> };

function chipsFor(filters: AuditFilters, t: Translate, locale: string): Chip[] {
  const chips: Chip[] = [];
  if (filters.userId) {
    chips.push({
      key: "user",
      label: filters.userLabel ?? filters.userId,
      icon: <User aria-hidden="true" className="size-3.5" />,
      remove: { userId: undefined, userLabel: undefined }
    });
  } else {
    for (const action of filters.actions) {
      chips.push({
        key: `action:${action}`,
        label: actionLabel(t, action),
        remove: { actions: filters.actions.filter((item) => item !== action) }
      });
    }
  }
  const { from_date: from, to_date: to } = filters;
  if (from || to) {
    chips.push({
      key: "period",
      label:
        from && to
          ? `${formatDate(from, locale)} – ${formatDate(to, locale)}`
          : from
            ? t("audit_period_from", { date: formatDate(from, locale) })
            : t("audit_period_to", { date: formatDate(to!, locale) }),
      remove: { from_date: undefined, to_date: undefined }
    });
  }
  return chips;
}

/**
 * Audit log filters: the search as the primary field, a "Filter" button that
 * opens user, action and period, and the active filters as removable chips.
 */
export function AuditFilterBar({
  filters,
  onChange
}: {
  filters: AuditFilters;
  onChange: OnChange;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const filteringByUser = Boolean(filters.userId);
  const chips = chipsFor(filters, t, locale);
  const hasFilters = chips.length > 0 || filters.search !== "";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          {/* The per-user endpoint has no free text: the field says why it waits. */}
          <TextInput
            label={t("search")}
            placeholder={t("audit_search_placeholder_entity")}
            value={filters.search}
            onChange={(value) => onChange({ search: value })}
            isDisabled={filteringByUser}
            disabledMessage={filteringByUser ? t("audit_filtering_by_user") : undefined}
            hasClear
            width="100%"
          />
        </div>
        <FilterButton filters={filters} onChange={onChange} />
        {hasFilters && (
          <Button
            variant="ghost"
            label={t("audit_filters_clear")}
            icon={<X aria-hidden="true" />}
            onClick={() => onChange(CLEARED)}
          />
        )}
      </div>

      {chips.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={t("audit_filters_button")}>
          {chips.map((chip) => (
            <li key={chip.key}>
              <Token
                label={chip.label}
                icon={chip.icon}
                size="sm"
                onRemove={() => onChange(chip.remove)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

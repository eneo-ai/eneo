"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useCollator } from "@astryxdesign/core/i18n";
import { Pagination } from "@astryxdesign/core/Pagination";
import {
  pixel,
  proportional,
  type TableColumn,
  type TableSortComparator,
  useTableSortable,
  useTableSortableState
} from "@astryxdesign/core/Table";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink, Search } from "lucide-react";
import Link from "@/lib/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { Table } from "@/components/astryx/table";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { PageHeader } from "@/components/composites/page-header";
import { blockingError, QueryStateBoundary } from "@/components/composites/query-state";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { replaceUrl, usePathname, useSearchParams } from "@/lib/navigation";
import { MemberStack } from "@/features/spaces/members/member-stack";
import {
  type CostRate,
  estimateCost,
  formatCost,
  isDefaultUsageRange,
  MAX_SEARCH_LENGTH,
  readUsageView,
  storageQueryOptions,
  storageSpacesQueryOptions,
  type StorageInfo,
  type StorageModel,
  type TokenUsage,
  tokenUsageQueryOptions,
  type UsageIntensity,
  USAGE_TABS,
  usageIntensity,
  type UsageRange,
  usageThresholds,
  type UsageView,
  usageViewSearch,
  USER_USAGE_PAGE_SIZE,
  type UserSortBy,
  userTokenUsageQueryOptions,
  type UserUsageRow,
  userUsageCost
} from "@/features/admin/usage/usage";
import {
  CostNote,
  type CostRates,
  DateRangeBar,
  percent,
  share,
  USAGE_LEVEL_CLASSES,
  UsageBadge,
  UsageBar,
  type UsageSegment,
  useCostRates
} from "@/features/admin/usage/usage-parts";

const NUMBER = new Intl.NumberFormat("sv-SE");
/** Rows the model and space tables show until "show all" (apps/web's page size). */
const SHORT_LIST = 10;
/** Provider segments take the categorical hues in order, so neighbours never share one. */
const PROVIDER_CLASSES = ["bg-ax-blue", "bg-ax-teal", "bg-ax-purple", "bg-ax-orange", "bg-ax-pink"];

type ChangeView = (change: Partial<UsageView>) => void;
type ModelRow = TokenUsage["models"][number] & { key: string; cost: number | null };
type SpaceRow = StorageInfo["items"][number];

function useCompact() {
  const format = useFormatter();
  return (value: number) => format.number(value, { notation: "compact", maximumFractionDigits: 1 });
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1 p-4">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
    </Card>
  );
}

function SectionHeading({
  id,
  title,
  description
}: {
  id?: string;
  title: string;
  description: string;
}) {
  return (
    <div>
      <h2 id={id} className="font-semibold">
        {title}
      </h2>
      <p className="text-muted-foreground text-sm">{description}</p>
    </div>
  );
}

function ShowAllToggle({
  count,
  showAll,
  onToggle,
  showAllLabel,
  showFewLabel
}: {
  count: number;
  showAll: boolean;
  onToggle: () => void;
  showAllLabel: string;
  showFewLabel: string;
}) {
  if (count <= SHORT_LIST) return null;
  return <AstryxButton label={showAll ? showFewLabel : showAllLabel} onClick={onToggle} />;
}

/** The last 30 days by provider, as apps/web's token overview shows them. */
function TokenOverview({ data }: { data: TokenUsage }) {
  const t = useTranslations();
  const compact = useCompact();
  const totals = new Map<string, number>();
  for (const model of data.models) {
    const provider = model.model_provider ?? model.model_org ?? "";
    totals.set(provider, (totals.get(provider) ?? 0) + model.total_token_usage);
  }
  const segments = [...totals]
    .sort((a, b) => b[1] - a[1])
    .map(([provider, tokens], index): UsageSegment => ({
      key: provider,
      name: provider || t("unknown_organization"),
      detail: compact(tokens),
      value: tokens,
      className: PROVIDER_CLASSES[index % PROVIDER_CLASSES.length]!
    }));

  return (
    <Card className="flex flex-col gap-4 p-4">
      <SectionHeading title={t("token_summary")} description={t("token_summary_description")} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("usage_total_tokens")} value={NUMBER.format(data.total_token_usage)} />
        <Stat label={t("input")} value={NUMBER.format(data.total_input_token_usage)} />
        <Stat label={t("output")} value={NUMBER.format(data.total_output_token_usage)} />
      </div>
      {segments.length > 0 ? <UsageBar segments={segments} total={data.total_token_usage} /> : null}
    </Card>
  );
}

function ModelTable({
  data,
  costRates: { rates, ratecard },
  labelledBy
}: {
  data: TokenUsage;
  costRates: CostRates;
  labelledBy: string;
}) {
  const t = useTranslations();
  const collator = useCollator();
  const [showAll, setShowAll] = useState(false);
  // apps/web lists the models by organisation until a column is sorted.
  const rows = useMemo(
    () =>
      data.models
        .map((model): ModelRow => ({
          ...model,
          key: `${model.model_id}-${model.model_name}`,
          cost: estimateCost(
            model.input_token_usage,
            model.output_token_usage,
            rates.get(model.model_id)
          )
        }))
        .sort((a, b) => collator.compare(a.model_org ?? "", b.model_org ?? "")),
    [collator, data.models, rates]
  );
  const comparators = useMemo(
    (): Record<string, TableSortComparator<ModelRow>> => ({
      model: (a, b) => collator.compare(a.model_nickname, b.model_nickname),
      input: (a, b) => a.input_token_usage - b.input_token_usage,
      output: (a, b) => a.output_token_usage - b.output_token_usage,
      total: (a, b) => a.total_token_usage - b.total_token_usage,
      cost: (a, b) => (a.cost ?? -1) - (b.cost ?? -1)
    }),
    [collator]
  );
  const { sortedData, sortConfig } = useTableSortableState<ModelRow, string>({
    data: rows,
    comparators
  });
  const sortPlugin = useTableSortable<ModelRow, string>(sortConfig);

  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("usage_no_model_data_available")}</p>;
  }

  const number = (value: number) => <span className="tabular-nums">{NUMBER.format(value)}</span>;
  const columns: TableColumn<ModelRow>[] = [
    {
      key: "model",
      header: t("model"),
      width: proportional(2),
      sortable: true,
      renderCell: (model) => (
        <span className="flex flex-col">
          <span className="font-medium">{model.model_nickname}</span>
          {model.model_org ? (
            <span className="text-ax-text-secondary text-xs">{model.model_org}</span>
          ) : null}
        </span>
      )
    },
    {
      key: "input",
      header: t("input_tokens"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (model) => number(model.input_token_usage)
    },
    {
      key: "output",
      header: t("output_tokens"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (model) => number(model.output_token_usage)
    },
    {
      key: "total",
      header: t("total_tokens"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (model) => number(model.total_token_usage)
    },
    {
      key: "cost",
      header: t("estimated_cost"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (model) => (
        <span className="text-ax-text-secondary tabular-nums">{formatCost(model.cost)}</span>
      )
    }
  ];

  return (
    <>
      <Table
        data={showAll ? sortedData : sortedData.slice(0, SHORT_LIST)}
        columns={columns}
        idKey="key"
        aria-labelledby={labelledBy}
        plugins={{ sort: sortPlugin }}
        className="min-w-160"
      />
      <CostNote ratecard={ratecard} />
      <ShowAllToggle
        count={rows.length}
        showAll={showAll}
        onToggle={() => setShowAll(!showAll)}
        showAllLabel={t("show_all_models", { count: rows.length })}
        showFewLabel={t("show_only_10_models")}
      />
    </>
  );
}

function TokensTab({
  range,
  onRangeChange
}: {
  range: UsageRange;
  onRangeChange: (range: UsageRange) => void;
}) {
  const t = useTranslations();
  const costRates = useCostRates();
  const headingId = useId();
  // As in apps/web, the overview stays on the last 30 days and the model table
  // follows the range. With the default range both read one query, whose
  // failure the overview reports alone.
  const overview = useQuery(tokenUsageQueryOptions(browserApi));
  const details = useQuery({
    ...tokenUsageQueryOptions(browserApi, range),
    placeholderData: keepPreviousData
  });
  const reportedAbove = isDefaultUsageRange(range) && blockingError(overview);

  return (
    <div className="flex flex-col gap-6">
      <QueryStateBoundary query={overview} rows={1} height={256}>
        {(data) => <TokenOverview data={data} />}
      </QueryStateBoundary>
      {/* Outside the boundaries: a period that failed can still be changed or reset. */}
      <DateRangeBar range={range} onChange={onRangeChange} />
      <Card className="flex flex-col gap-4 p-4" aria-busy={details.isPlaceholderData || undefined}>
        <SectionHeading
          id={headingId}
          title={t("usage_by_model")}
          description={t("see_token_usage_by_model")}
        />
        {reportedAbove ? null : (
          <QueryStateBoundary query={details} rows={3}>
            {(data) => <ModelTable data={data} costRates={costRates} labelledBy={headingId} />}
          </QueryStateBoundary>
        )}
      </Card>
    </div>
  );
}

/** apps/web's user summary: the page's users by usage level. */
function UserLevels({
  users,
  total,
  range
}: {
  users: UserUsageRow[];
  total: number;
  range: UsageRange;
}) {
  const t = useTranslations();
  const compact = useCompact();
  const { high, medium } = usageThresholds(range);
  const names: Record<UsageIntensity, string> = {
    high: `${t("high_usage_users")} (>${compact(high)} ${t("tokens")})`,
    medium: `${t("medium_usage_users")} (>${compact(medium)} ${t("tokens")})`,
    low: `${t("low_usage_users")} (≤${compact(medium)} ${t("tokens")})`
  };
  const segments = (["high", "medium", "low"] as const)
    .map((level) => {
      const members = users.filter((user) => usageIntensity(user.total_tokens, range) === level);
      const tokens = members.reduce((sum, user) => sum + user.total_tokens, 0);
      return {
        key: level,
        name: names[level],
        detail: `${NUMBER.format(members.length)} ${t("users")}, ${compact(tokens)} ${t("tokens")}`,
        value: tokens,
        count: members.length,
        className: USAGE_LEVEL_CLASSES[level].bar
      };
    })
    .filter((segment) => segment.count > 0)
    .sort((a, b) => b.value - a.value);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-medium">{t("user_summary")}</h3>
        <p className="text-muted-foreground text-sm">{t("user_summary_description")}</p>
      </div>
      <UsageBar segments={segments} total={total} />
    </div>
  );
}

function UserTable({
  users,
  view,
  rates,
  labelledBy,
  onSort
}: {
  users: UserUsageRow[];
  view: UsageView;
  rates: Map<string, CostRate>;
  labelledBy: string;
  onSort: (sortBy: UserSortBy, sortOrder: UsageView["sortOrder"]) => void;
}) {
  const t = useTranslations();
  // The user's page leads back to this view.
  const back = usageViewSearch(view);
  const sortPlugin = useTableSortable<UserUsageRow, UserSortBy>({
    sort: [
      { sortKey: view.sortBy, direction: view.sortOrder === "asc" ? "ascending" : "descending" }
    ],
    onSortChange: ([next]) => {
      if (!next) return;
      // A new column starts as in apps/web: names A–Z, figures largest first.
      if (next.sortKey !== view.sortBy) {
        onSort(next.sortKey, next.sortKey === "username" ? "asc" : "desc");
      } else {
        onSort(next.sortKey, next.direction === "ascending" ? "asc" : "desc");
      }
    }
  });
  const number = (value: number) => <span className="tabular-nums">{NUMBER.format(value)}</span>;
  const columns: TableColumn<UserUsageRow>[] = [
    {
      key: "username",
      header: t("user"),
      width: proportional(2),
      sortable: true,
      renderCell: (user) => (
        <span className="flex min-w-0 flex-col items-start">
          <Button variant="link" className="h-auto p-0 font-medium" asChild>
            <Link href={`/admin/usage/users/${user.user_id}${back}`}>
              {user.username}
              <ExternalLink className="size-3" />
            </Link>
          </Button>
          {user.email !== user.username ? (
            <span className="text-ax-text-secondary max-w-full truncate text-xs">{user.email}</span>
          ) : null}
        </span>
      )
    },
    {
      key: "level",
      header: t("usage_level"),
      width: pixel(150),
      renderCell: (user) => <UsageBadge level={usageIntensity(user.total_tokens, view.range)} />
    },
    {
      key: "input_tokens",
      header: t("input_tokens"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (user) => number(user.total_input_tokens)
    },
    {
      key: "output_tokens",
      header: t("output_tokens"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (user) => number(user.total_output_tokens)
    },
    {
      key: "total_tokens",
      header: t("total_tokens"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (user) => number(user.total_tokens)
    },
    {
      key: "requests",
      header: t("requests"),
      width: proportional(1),
      align: "end",
      sortable: true,
      renderCell: (user) => number(user.total_requests)
    },
    {
      key: "cost",
      header: t("estimated_cost"),
      width: proportional(1),
      align: "end",
      renderCell: (user) => (
        <span className="text-ax-text-secondary tabular-nums">
          {formatCost(userUsageCost(user, rates))}
        </span>
      )
    }
  ];

  return (
    <Table
      data={users}
      columns={columns}
      idKey="user_id"
      aria-labelledby={labelledBy}
      plugins={{ sort: sortPlugin }}
      className="min-w-200"
    />
  );
}

function UsersTab({ view, onChange }: { view: UsageView; onChange: ChangeView }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const { rates, ratecard } = useCostRates();
  const headingId = useId();
  // The search box is a draft until submitted; a search from the URL replaces it.
  const [draft, setDraft] = useState(view.search);
  const [draftFor, setDraftFor] = useState(view.search);
  if (draftFor !== view.search) {
    setDraftFor(view.search);
    setDraft(view.search);
  }
  const usage = useQuery({
    ...userTokenUsageQueryOptions(browserApi, view.range, {
      page: view.page,
      sortBy: view.sortBy,
      sortOrder: view.sortOrder,
      search: view.search
    }),
    placeholderData: keepPreviousData
  });
  const settled = usage.data !== undefined && !usage.isPlaceholderData;
  const total = usage.data?.total_users ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / USER_USAGE_PAGE_SIZE));
  const shown = t("pagination_showing_range", {
    start: (view.page - 1) * USER_USAGE_PAGE_SIZE + 1,
    end: Math.min(view.page * USER_USAGE_PAGE_SIZE, total),
    total
  });

  // A page past the end (an old link, or fewer users now): show the last page.
  useEffect(() => {
    if (settled && view.page > totalPages) onChange({ page: totalPages });
  }, [onChange, settled, totalPages, view.page]);

  // Announce the results of a new search, sort or range; not the first load,
  // and not a page change (Pagination announces those).
  const resultsFor = [
    view.search,
    view.sortBy,
    view.sortOrder,
    view.range.from,
    view.range.to
  ].join("|");
  const announcedFor = useRef(resultsFor);
  useEffect(() => {
    if (!settled || announcedFor.current === resultsFor) return;
    announcedFor.current = resultsFor;
    announce(total > 0 ? shown : t("no_user_token_usage_data"));
  }, [announce, resultsFor, settled, shown, t, total]);

  return (
    <div className="flex flex-col gap-6">
      <DateRangeBar range={view.range} onChange={(range) => onChange({ range })} />
      <Card className="flex flex-col gap-4 p-4">
        <SectionHeading
          id={headingId}
          title={t("usage_by_user")}
          description={t("usage_by_user_description")}
        />
        <form
          role="search"
          aria-label={t("usage_by_user")}
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onChange({ search: draft.trim().slice(0, MAX_SEARCH_LENGTH) });
          }}
        >
          <div className="min-w-48 flex-1">
            <TextInput
              label={t("usage_user_search")}
              isLabelHidden
              placeholder={t("usage_user_search")}
              startIcon={Search}
              value={draft}
              onChange={setDraft}
              autoComplete="off"
            />
          </div>
          <AstryxButton type="submit" variant="primary" label={t("search")} />
          <AstryxButton
            label={t("admin_users_clear_filters")}
            onClick={() => {
              setDraft("");
              onChange({ search: "" });
            }}
          />
        </form>
        <QueryStateBoundary query={usage} rows={5}>
          {(result) =>
            result.users.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("no_user_token_usage_data")}</p>
            ) : (
              <div className="flex flex-col gap-4" aria-busy={usage.isPlaceholderData || undefined}>
                <UserLevels users={result.users} total={result.total_tokens} range={view.range} />
                <p className="text-muted-foreground text-sm tabular-nums">{shown}</p>
                <UserTable
                  users={result.users}
                  view={view}
                  rates={rates}
                  labelledBy={headingId}
                  onSort={(sortBy, sortOrder) => onChange({ sortBy, sortOrder })}
                />
                <CostNote ratecard={ratecard} />
                {/* Never disabled while a page loads: the previous page stays (aria-busy). */}
                {total > USER_USAGE_PAGE_SIZE || view.page > 1 ? (
                  <Pagination
                    variant="input"
                    page={Math.min(view.page, totalPages)}
                    totalPages={totalPages}
                    onChange={(page) => onChange({ page })}
                    label={t("admin_users_pagination")}
                  />
                ) : null}
              </div>
            )
          }
        </QueryStateBoundary>
      </Card>
    </div>
  );
}

function SpaceTable({ spaces, labelledBy }: { spaces: SpaceRow[]; labelledBy: string }) {
  const t = useTranslations();
  const locale = useLocale();
  const collator = useCollator();
  const [showAll, setShowAll] = useState(false);
  // apps/web lists the largest spaces first until a column is sorted.
  const rows = useMemo(() => [...spaces].sort((a, b) => b.size - a.size), [spaces]);
  const comparators = useMemo(
    (): Record<string, TableSortComparator<SpaceRow>> => ({
      name: (a, b) => collator.compare(a.name, b.name),
      members: (a, b) => a.members.length - b.members.length,
      size: (a, b) => a.size - b.size
    }),
    [collator]
  );
  const { sortedData, sortConfig } = useTableSortableState<SpaceRow, string>({
    data: rows,
    comparators
  });
  const sortPlugin = useTableSortable<SpaceRow, string>(sortConfig);

  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("no_usage_data")}</p>;
  }

  const columns: TableColumn<SpaceRow>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (space) => (
        <span className="flex min-w-0 items-center gap-2">
          <EntityAvatar name={space.name} id={space.id} size="sm" />
          <span className="truncate font-medium">{space.name}</span>
        </span>
      )
    },
    {
      key: "members",
      header: t("members"),
      width: proportional(1),
      sortable: true,
      renderCell: (space) => <MemberStack members={space.members} />
    },
    {
      key: "size",
      header: t("storage"),
      width: pixel(140),
      align: "end",
      sortable: true,
      renderCell: (space) => (
        <span className="tabular-nums">{formatBytes(space.size, locale, 2)}</span>
      )
    }
  ];

  return (
    <>
      <Table
        data={showAll ? sortedData : sortedData.slice(0, SHORT_LIST)}
        columns={columns}
        idKey="id"
        aria-labelledby={labelledBy}
        plugins={{ sort: sortPlugin }}
        className="min-w-120"
      />
      <ShowAllToggle
        count={rows.length}
        showAll={showAll}
        onToggle={() => setShowAll(!showAll)}
        showAllLabel={t("show_all_spaces", { count: rows.length })}
        showFewLabel={t("show_only_10_spaces")}
      />
    </>
  );
}

function StorageOverview({ storage }: { storage: StorageModel }) {
  const t = useTranslations();
  const locale = useLocale();
  const { limit } = storage;
  const parts = [
    {
      key: "shared",
      name: t("public_spaces"),
      value: storage.shared_used,
      className: "bg-ax-green"
    },
    {
      key: "personal",
      name: t("personal_spaces"),
      value: storage.personal_used,
      className: "bg-ax-accent"
    },
    // More can be used than the limit allows: then nothing is free.
    {
      key: "free",
      name: t("free"),
      value: Math.max(limit - storage.total_used, 0),
      className: "bg-ax-muted"
    }
  ];
  const segments = parts.map((part): UsageSegment => ({
    ...part,
    detail: `${formatBytes(part.value, locale)} (${percent(share(part.value, limit), locale)})`
  }));

  return (
    <Card className="flex flex-col gap-4 p-4">
      <SectionHeading title={t("storage_summary")} description={t("storage_summary_description")} />
      <p className="text-sm">
        <span className="font-medium">{t("available")}</span>: {formatBytes(limit, locale)}
      </p>
      <UsageBar segments={segments} total={limit} />
    </Card>
  );
}

function StorageTab() {
  const t = useTranslations();
  const headingId = useId();
  const storage = useQuery(storageQueryOptions(browserApi));
  const spaces = useQuery(storageSpacesQueryOptions(browserApi));

  return (
    <QueryStateBoundary queries={[storage, spaces]} rows={1} height={256}>
      {() => (
        <div className="flex flex-col gap-6">
          <StorageOverview storage={storage.data!} />
          <Card className="flex flex-col gap-4 p-4">
            <SectionHeading
              id={headingId}
              title={t("public_spaces")}
              description={t("public_spaces_storage_description")}
            />
            <SpaceTable spaces={spaces.data!.items} labelledBy={headingId} />
          </Card>
        </div>
      )}
    </QueryStateBoundary>
  );
}

export function UsagePage() {
  const t = useTranslations();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // The URL owns the view: a reload, a link or a user's page leads back to it.
  const view = readUsageView(searchParams);
  // As in apps/web, any change but a page change starts on the first page.
  const change: ChangeView = (next) =>
    replaceUrl(
      `${pathname}${usageViewSearch({ ...view, page: 1, ...next }, searchParams.toString())}`
    );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("usage")} />
      <Tabs
        value={view.tab}
        onValueChange={(value) => {
          const tab = USAGE_TABS.find((candidate) => candidate === value);
          if (tab) change({ tab });
        }}
      >
        <TabsList>
          <TabsTrigger value="tokens">{t("tokens")}</TabsTrigger>
          <TabsTrigger value="users">{t("users")}</TabsTrigger>
          <TabsTrigger value="storage">{t("storage")}</TabsTrigger>
        </TabsList>
        <TabsContent value="tokens" className="pt-4">
          <TokensTab range={view.range} onRangeChange={(range) => change({ range })} />
        </TabsContent>
        <TabsContent value="users" className="pt-4">
          <UsersTab view={view} onChange={change} />
        </TabsContent>
        <TabsContent value="storage" className="pt-4">
          <StorageTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { type Dispatch, type SetStateAction, useMemo, useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import {
  buildRateMap,
  defaultUsageRange,
  formatCost,
  usageIntensity,
  userModelBreakdownQueryOptions,
  userTokenUsageSummaryQueryOptions,
  userUsageCost,
  type TokenUsage,
  type UsageRange,
  type UserUsageRow
} from "@/features/admin/usage/usage";

const NUMBER = new Intl.NumberFormat("sv-SE");

function Stat({ label, value, subvalue }: { label: string; value: string; subvalue?: string }) {
  return (
    <Card className="flex flex-col gap-1 p-4">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {subvalue ? <span className="text-muted-foreground text-xs">{subvalue}</span> : null}
    </Card>
  );
}

function percent(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1
  }).format(Number.isFinite(value) ? value : 0);
}

function share(part: number, total: number): number {
  return total > 0 ? part / total : 0;
}

function modelDisplayName(model: TokenUsage["models"][number]): string {
  return model.model_nickname || model.model_name;
}

function modelProvider(model: TokenUsage["models"][number], unknown: string): string {
  return model.model_provider || model.model_org || unknown;
}

function DateRangeBar({
  range,
  setRange
}: {
  range: UsageRange;
  setRange: Dispatch<SetStateAction<UsageRange>>;
}) {
  const t = useTranslations();
  return (
    <Card className="flex flex-wrap items-end gap-3 p-4">
      <label className="flex flex-col gap-1 text-xs">
        {t("from")}
        <Input
          type="date"
          className="h-8 w-36"
          value={range.from}
          onChange={(event) => {
            if (event.target.value)
              setRange((current) => ({ ...current, from: event.target.value }));
          }}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        {t("to")}
        <Input
          type="date"
          className="h-8 w-36"
          value={range.to}
          onChange={(event) => {
            if (event.target.value) setRange((current) => ({ ...current, to: event.target.value }));
          }}
        />
      </label>
      <Button variant="outline" size="sm" onClick={() => setRange(defaultUsageRange())}>
        <RotateCcw className="size-4" />
        {t("reset")}
      </Button>
    </Card>
  );
}

function UsageBadge({ user, range }: { user: UserUsageRow; range: UsageRange }) {
  const t = useTranslations();
  const intensity = usageIntensity(user.total_tokens, range);
  const className =
    intensity === "high"
      ? "border-destructive/40 text-destructive"
      : intensity === "medium"
        ? "border-warning/40 text-warning"
        : "border-success/40 text-success";
  return (
    <Badge variant="outline" className={className}>
      {t(`usage_level_${intensity}`)}
    </Badge>
  );
}

function UserSummary({
  user,
  range,
  cost
}: {
  user: UserUsageRow;
  range: UsageRange;
  cost: number | null;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const averageTokens =
    user.total_requests > 0 ? user.total_tokens / user.total_requests : user.total_tokens;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <Card className="flex flex-col gap-4 p-4">
        <div className="flex items-center gap-3">
          <div className="bg-primary text-primary-foreground grid size-12 shrink-0 place-items-center rounded-md text-lg font-semibold">
            {user.username.slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="truncate font-semibold">{user.username}</p>
            <p className="text-muted-foreground truncate text-sm">{user.email}</p>
          </div>
        </div>
        <UsageBadge user={user} range={range} />
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t("username")}</dt>
          <dd className="truncate">{user.username}</dd>
          <dt className="text-muted-foreground">{t("email")}</dt>
          <dd className="truncate">{user.email}</dd>
        </dl>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("usage_total_tokens")} value={NUMBER.format(user.total_tokens)} />
        <Stat
          label={t("usage_input_tokens")}
          value={NUMBER.format(user.total_input_tokens)}
          subvalue={`${percent(share(user.total_input_tokens, user.total_tokens), locale)} ${t(
            "usage_of_total"
          )}`}
        />
        <Stat
          label={t("usage_output_tokens")}
          value={NUMBER.format(user.total_output_tokens)}
          subvalue={`${percent(share(user.total_output_tokens, user.total_tokens), locale)} ${t(
            "usage_of_total"
          )}`}
        />
        <Stat
          label={t("usage_total_requests")}
          value={NUMBER.format(user.total_requests)}
          subvalue={`${NUMBER.format(Math.round(averageTokens))} ${t(
            "usage_tokens_avg_per_request"
          )} · ${formatCost(cost)}`}
        />
      </div>
    </div>
  );
}

function ProviderBreakdown({ data }: { data: TokenUsage }) {
  const t = useTranslations();
  const locale = useLocale();
  const unknown = t("unknown");
  const providers = useMemo(() => {
    const rows = new Map<string, { provider: string; tokens: number; requests: number }>();
    for (const model of data.models) {
      const provider = modelProvider(model, unknown);
      const row = rows.get(provider) ?? { provider, tokens: 0, requests: 0 };
      row.tokens += model.total_token_usage;
      row.requests += model.request_count;
      rows.set(provider, row);
    }
    return [...rows.values()].sort((a, b) => b.tokens - a.tokens);
  }, [data.models, unknown]);

  if (providers.length === 0) return null;

  return (
    <Card className="flex flex-col gap-4 p-4">
      <div>
        <h2 className="font-semibold">{t("usage_by_organization")}</h2>
        <p className="text-muted-foreground text-sm">{t("see_token_usage_by_model")}</p>
      </div>
      <div className="grid gap-3">
        {providers.map((provider) => (
          <div key={provider.provider} className="grid gap-1">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">{provider.provider}</span>
              <span className="text-muted-foreground tabular-nums">
                {NUMBER.format(provider.tokens)} ·{" "}
                {percent(share(provider.tokens, data.total_token_usage), locale)}
              </span>
            </div>
            <Progress value={share(provider.tokens, data.total_token_usage) * 100} />
          </div>
        ))}
      </div>
    </Card>
  );
}

function TopModels({ data }: { data: TokenUsage }) {
  const t = useTranslations();
  const topModels = useMemo(
    () => [...data.models].sort((a, b) => b.total_token_usage - a.total_token_usage).slice(0, 5),
    [data.models]
  );
  if (topModels.length === 0) return null;

  const topTotal = topModels[0]?.total_token_usage ?? 0;
  return (
    <Card className="flex flex-col gap-4 p-4">
      <h2 className="font-semibold">{t("usage_top_models")}</h2>
      <div className="grid gap-3">
        {topModels.map((model) => (
          <div key={`${model.model_id}-${model.model_name}`} className="grid gap-1">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate font-medium">{modelDisplayName(model)}</span>
              <span className="text-muted-foreground shrink-0 tabular-nums">
                {NUMBER.format(model.total_token_usage)} · {NUMBER.format(model.request_count)}{" "}
                {t("usage_requests_label")}
              </span>
            </div>
            <Progress value={share(model.total_token_usage, topTotal) * 100} />
          </div>
        ))}
      </div>
    </Card>
  );
}

function ModelBreakdownTable({
  data,
  rates
}: {
  data: TokenUsage;
  rates: ReturnType<typeof buildRateMap>;
}) {
  const t = useTranslations();
  const unknown = t("unknown");

  if (data.models.length === 0) {
    return (
      <Card className="p-6 text-center">
        <h2 className="font-semibold">{t("usage_no_model_usage")}</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {t("usage_no_model_usage_description")}
        </p>
      </Card>
    );
  }

  return (
    <Card className="flex flex-col gap-4 p-4">
      <h2 className="font-semibold">{t("usage_complete_model_breakdown")}</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("model")}</TableHead>
            <TableHead>{t("provider")}</TableHead>
            <TableHead className="text-right">{t("requests")}</TableHead>
            <TableHead className="text-right">{t("input_tokens")}</TableHead>
            <TableHead className="text-right">{t("output_tokens")}</TableHead>
            <TableHead className="text-right">{t("total_tokens")}</TableHead>
            <TableHead className="text-right">{t("estimated_cost")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.models.map((model) => {
            const cost = userUsageCost({ models_used: [model] }, rates);
            return (
              <TableRow key={`${model.model_id}-${model.model_name}`}>
                <TableCell className="font-medium">{modelDisplayName(model)}</TableCell>
                <TableCell className="text-muted-foreground">
                  {modelProvider(model, unknown)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.request_count)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.input_token_usage)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.output_token_usage)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.total_token_usage)}
                </TableCell>
                <TableCell className="text-muted-foreground text-right tabular-nums">
                  {formatCost(cost)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

export function UserUsagePage({
  userId,
  initialRange
}: {
  userId: string;
  initialRange: UsageRange;
}) {
  const t = useTranslations();
  const [range, setRange] = useState(initialRange);
  const user = useQuery(userTokenUsageSummaryQueryOptions(browserApi, userId, range));
  const breakdown = useQuery(userModelBreakdownQueryOptions(browserApi, userId, range));
  const models = useQuery(adminModelsQueryOptions(browserApi));
  const rates = useMemo(() => buildRateMap(models.data?.completion_models ?? []), [models.data]);
  const userRow = user.data?.user;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader title={userRow?.username ?? t("usage")}>
        <Button variant="outline" asChild>
          <Link href="/admin/usage">
            <ArrowLeft className="size-4" />
            {t("back")}
          </Link>
        </Button>
      </PageHeader>

      <DateRangeBar range={range} setRange={setRange} />

      {user.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : user.isError || !userRow ? (
        <Card className="p-6 text-center">
          <h2 className="font-semibold">{t("usage_user_not_found")}</h2>
          <p className="text-muted-foreground mt-1 text-sm">
            {user.isError ? t("request_failed") : t("usage_user_not_found_description")}
          </p>
        </Card>
      ) : (
        <>
          <UserSummary user={userRow} range={range} cost={userUsageCost(userRow, rates)} />

          {breakdown.isPending ? (
            <Skeleton className="h-72 w-full" />
          ) : breakdown.isError || !breakdown.data ? (
            <Card className="p-6 text-center">
              <h2 className="font-semibold">{t("usage_error_loading_model_breakdown")}</h2>
              <p className="text-muted-foreground mt-1 text-sm">{t("request_failed")}</p>
            </Card>
          ) : (
            <>
              <ProviderBreakdown data={breakdown.data} />
              <TopModels data={breakdown.data} />
              <ModelBreakdownTable data={breakdown.data} rates={rates} />
            </>
          )}
        </>
      )}
    </div>
  );
}

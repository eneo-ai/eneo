"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { Link } from "@astryxdesign/core/Link";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useId, useMemo, type ReactNode } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { actionLabel } from "@/features/admin/audit/audit";
import type { CrawlerSchedulerHealth } from "@/features/admin/crawler/crawler";
import {
  latestAuditEventsQueryOptions,
  overviewCrawlerQueryOptions,
  overviewUsageQueryOptions,
  overviewUsersQueryOptions
} from "./overview";

type CardQuery = Pick<
  UseQueryResult<unknown, Error>,
  "isPending" | "isError" | "isFetching" | "errorUpdatedAt" | "dataUpdatedAt" | "error" | "refetch"
>;

/**
 * A failed query, also while a retry without cached data is in flight: React
 * Query reports that as "pending" and clears isError, which would swap the
 * retry button for a skeleton under the keyboard user's focus.
 */
function hasFailed(query: CardQuery): boolean {
  return query.isError || (query.isFetching && query.errorUpdatedAt > query.dataUpdatedAt);
}

function useNumberFormat() {
  const locale = useLocale();
  return useMemo(() => new Intl.NumberFormat(locale), [locale]);
}

function CardEmpty({ title }: { title: string }) {
  return <EmptyState title={title} headingLevel={3} isCompact framed={false} />;
}

/**
 * One landing card: a titled region with its page's link, that always ends
 * in content, an empty state or an error with retry (never a stuck skeleton).
 * `renderError` lets a card show a specific error (the audit card's locked
 * state) instead of the generic one.
 */
function OverviewCard({
  title,
  href,
  linkLabel,
  query,
  renderError,
  children
}: {
  title: string;
  href: string;
  linkLabel: string;
  query: CardQuery;
  renderError?: (error: Error | null) => ReactNode;
  children: ReactNode;
}) {
  const headingId = useId();
  const failed = hasFailed(query);
  return (
    <section aria-labelledby={headingId} className="flex min-w-0">
      <Card className="flex min-w-0 flex-1 flex-col gap-4">
        <Heading level={2} id={headingId} className="text-base">
          {title}
        </Heading>
        <div className="flex flex-1 flex-col gap-3">
          {failed ? (
            (renderError?.(query.error) ?? (
              <ListError
                error={query.error}
                isRetrying={query.isFetching}
                onRetry={() => void query.refetch()}
              />
            ))
          ) : query.isPending ? (
            <LoadingState rows={2} />
          ) : (
            children
          )}
        </div>
        <Link href={href} className="self-start text-sm">
          {linkLabel}
        </Link>
      </Card>
    </section>
  );
}

function BigNumber({ value }: { value: string }) {
  return <p className="text-3xl font-semibold tabular-nums">{value}</p>;
}

function UsersCard() {
  const t = useTranslations();
  const format = useNumberFormat();
  const query = useQuery(overviewUsersQueryOptions(browserApi));
  const metadata = query.data?.metadata;
  // The query asks for active users, so total_count is their number; the
  // per-state counts (when the backend sends them) add the inactive ones.
  const active = metadata?.counts?.active ?? metadata?.total_count ?? 0;
  const inactive = metadata?.counts?.inactive;

  return (
    <OverviewCard
      title={t("active_users")}
      href="/admin/users"
      linkLabel={t("admin_overview_users_link")}
      query={query}
    >
      <BigNumber value={format.format(active)} />
      {inactive != null ? (
        <p className="text-ax-text-secondary text-sm">
          {t("admin_overview_users_inactive", { count: inactive })}
        </p>
      ) : null}
    </OverviewCard>
  );
}

function UsageCard() {
  const t = useTranslations();
  const format = useNumberFormat();
  const query = useQuery(overviewUsageQueryOptions(browserApi));
  const usage = query.data;

  return (
    <OverviewCard
      title={t("admin_overview_usage_title")}
      href="/admin/usage"
      linkLabel={t("admin_overview_usage_link")}
      query={query}
    >
      {usage && usage.total_token_usage === 0 ? (
        <CardEmpty title={t("admin_overview_usage_empty")} />
      ) : usage ? (
        <>
          <BigNumber value={format.format(usage.total_token_usage)} />
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-ax-text-secondary">{t("input")}</dt>
            <dd className="tabular-nums">{format.format(usage.total_input_token_usage)}</dd>
            <dt className="text-ax-text-secondary">{t("output")}</dt>
            <dd className="tabular-nums">{format.format(usage.total_output_token_usage)}</dd>
          </dl>
          <p className="text-ax-text-secondary text-sm">
            {t("admin_overview_usage_models", { count: usage.models.length })}
          </p>
        </>
      ) : null}
    </OverviewCard>
  );
}

const SCHEDULER_TONE: Record<CrawlerSchedulerHealth["status"], StatusTone> = {
  ok: "success",
  degraded: "warning",
  stale: "error",
  unknown: "neutral"
};

function CrawlerCard() {
  const t = useTranslations();
  const format = useNumberFormat();
  const query = useQuery(overviewCrawlerQueryOptions(browserApi));
  const overview = query.data;
  const summary = overview?.summary;
  const isIdle = summary ? summary.ongoing + summary.queued + summary.issues === 0 : false;

  const counts = summary
    ? [
        { key: "admin_crawler_ongoing", value: summary.ongoing },
        { key: "admin_crawler_queued", value: summary.queued },
        // Issues are the one count that asks for attention: coloured only above zero.
        { key: "admin_crawler_issues", value: summary.issues, attention: summary.issues > 0 }
      ]
    : [];

  return (
    <OverviewCard
      title={t("admin_crawler_title")}
      href="/admin/crawler"
      linkLabel={t("admin_overview_crawler_link")}
      query={query}
    >
      {overview ? (
        <>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span>{t("admin_crawler_scheduler")}</span>
            <StatusLabel
              status={SCHEDULER_TONE[overview.scheduler.status]}
              label={t(`admin_crawler_scheduler_${overview.scheduler.status}`)}
            />
          </p>
          {isIdle ? (
            <CardEmpty title={t("admin_overview_crawler_empty")} />
          ) : (
            <dl className="grid grid-cols-3 gap-3">
              {counts.map((count) => (
                <div key={count.key} className="flex min-w-0 flex-col gap-0.5">
                  <dt className="text-ax-text-secondary text-sm">{t(count.key)}</dt>
                  <dd
                    className={cn(
                      "text-2xl font-semibold tabular-nums",
                      count.attention && "text-ax-warning"
                    )}
                  >
                    {format.format(count.value)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </>
      ) : null}
    </OverviewCard>
  );
}

function AuditLocked() {
  const t = useTranslations();
  return (
    <EmptyState
      title={t("admin_overview_audit_locked")}
      headingLevel={3}
      isCompact
      framed={false}
      actions={
        <Button href="/admin/audit-logs" label={t("admin_overview_audit_unlock")} size="sm" />
      }
    />
  );
}

function AuditCard() {
  const t = useTranslations();
  const query = useQuery(latestAuditEventsQueryOptions(browserApi));
  const logs = query.data?.logs ?? [];

  return (
    <OverviewCard
      title={t("admin_overview_audit_title")}
      href="/admin/audit-logs"
      linkLabel={t("admin_overview_audit_link")}
      query={query}
      renderError={(error) =>
        // 401: the audit logs need a justified access session (the page's gate).
        error instanceof EneoApiError && error.status === 401 ? <AuditLocked /> : undefined
      }
    >
      {query.data && logs.length === 0 ? (
        <CardEmpty title={t("admin_overview_audit_empty")} />
      ) : query.data ? (
        <ul className="divide-ax-border -my-1 divide-y">
          {logs.map((log) => (
            <li key={log.id} className="flex min-w-0 items-start gap-3 py-2 text-sm">
              <Badge label={actionLabel(t, log.action)} />
              <span className="min-w-0 flex-1 truncate" title={log.description}>
                {log.description}
              </span>
              <span className="text-ax-text-secondary shrink-0 text-xs">
                <ClientTime value={log.timestamp} format="auto" />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </OverviewCard>
  );
}

/**
 * The admin landing: what is going on in the organisation, one card per
 * area with a link to its page. The audit card appears only when audit
 * logging is on (otherwise there is nothing to list).
 */
export function AdminOverviewPage() {
  const t = useTranslations();
  const { settings } = useAppContext();

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader title={t("overview")} description={t("admin_overview_description")} />
      <div className="grid gap-4 md:grid-cols-2">
        <UsersCard />
        <UsageCard />
        <CrawlerCard />
        {settings.audit_logging_enabled ? <AuditCard /> : null}
      </div>
    </div>
  );
}

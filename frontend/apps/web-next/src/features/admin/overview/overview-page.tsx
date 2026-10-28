"use client";

import { modelEntries } from "../models/provider-sections";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Heading } from "@astryxdesign/core/Heading";
import { Link } from "@astryxdesign/core/Link";
import { List, ListItem } from "@astryxdesign/core/List";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Activity, ChevronRight, Cpu, Globe, History, Users, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useMemo, useRef, useState, type ReactNode } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { blockingError, ListError, RefreshError } from "@/components/composites/query-state";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { useFocusAcrossLayouts } from "@/lib/hooks/use-focus-across-layouts";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { cn } from "@/lib/utils";
import { actionLabel } from "@/features/admin/audit/audit";
import type { CrawlerSchedulerHealth } from "@/features/admin/crawler/crawler";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { AttentionSection, useAdminAttention } from "./attention";
import {
  latestAuditEventsQueryOptions,
  overviewCrawlerQueryOptions,
  overviewUsageQueryOptions,
  overviewUsersQueryOptions
} from "./overview";

type CardQuery = Pick<
  UseQueryResult<unknown, Error>,
  | "data"
  | "isPending"
  | "isError"
  | "isFetching"
  | "errorUpdatedAt"
  | "dataUpdatedAt"
  | "error"
  | "refetch"
>;

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
  const failed = blockingError(query);
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
            <>
              <RefreshError queries={[query]} />
              {children}
            </>
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

/**
 * Whether the audit logs are locked: they answer 401 until the admin opens a
 * justified access session (the page's gate). Remembered while the query
 * retries, which clears its error, so the lock does not flip to a load error.
 */
function useAuditLocked(query: UseQueryResult<unknown, Error>): boolean {
  const [locked, setLocked] = useState(false);
  const now = query.error
    ? query.error instanceof EneoApiError && query.error.status === 401
    : query.data !== undefined
      ? false
      : locked;
  if (now !== locked) setLocked(now);
  return now;
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
  const locked = useAuditLocked(query);
  const logs = query.data?.logs ?? [];

  return (
    <OverviewCard
      title={t("admin_overview_audit_title")}
      href="/admin/audit-logs"
      linkLabel={t("admin_overview_audit_link")}
      query={query}
      renderError={() => (locked ? <AuditLocked /> : undefined)}
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

/** A query with nothing to wait for or fail: a locked area's row. */
const SETTLED: CardQuery = {
  data: null,
  isPending: false,
  isError: false,
  isFetching: false,
  errorUpdatedAt: 0,
  dataUpdatedAt: 0,
  error: null,
  refetch: () => Promise.reject(new Error("settled"))
};

/** One area on a phone: its name, how it stands now, and its page. */
function AreaRow({
  href,
  icon: Icon,
  label,
  query,
  state
}: {
  href: string;
  icon: LucideIcon;
  label: string;
  query: CardQuery;
  /** How the area stands, once its data is in. */
  state: ReactNode;
}) {
  const t = useTranslations();
  const description = blockingError(query)
    ? t("query_error_title")
    : query.isPending
      ? t("loading")
      : state;
  return (
    <ListItem
      href={href}
      className="min-h-14"
      label={
        <span className="block break-words">
          {label}
          <span className="sr-only">, </span>
        </span>
      }
      description={
        <span className="flex flex-wrap items-center gap-x-1 break-words">{description}</span>
      }
      startContent={<Icon aria-hidden="true" className="text-ax-text-secondary size-5" />}
      endContent={<ChevronRight aria-hidden="true" className="text-ax-text-secondary size-4" />}
    />
  );
}

/**
 * "Läget just nu" on a phone (decision 30): each area as a row with its live
 * state, in place of the cards. An area whose problem leads the page says so
 * here too, so the row never contradicts it.
 */
function AreaRows({ className }: { className?: string }) {
  const t = useTranslations();
  const id = useId();
  const format = useNumberFormat();
  const { settings } = useAppContext();
  const users = useQuery(overviewUsersQueryOptions(browserApi));
  const models = useQuery(adminModelsQueryOptions(browserApi));
  const usage = useQuery(overviewUsageQueryOptions(browserApi));
  const crawler = useQuery(overviewCrawlerQueryOptions(browserApi));
  const audit = useQuery({
    ...latestAuditEventsQueryOptions(browserApi),
    enabled: settings.audit_logging_enabled
  });
  const auditLocked = useAuditLocked(audit);
  // What leads the page is said here too, so a row never reads as fine.
  const attention = useAdminAttention();
  const modelsAttention = attention.filter((row) => row.href.startsWith("/admin/models"));
  const scheduler = attention.find((row) => row.key === "crawler-scheduler");

  const metadata = users.data?.metadata;
  const active = metadata?.counts?.active ?? metadata?.total_count ?? 0;
  const inactive = metadata?.counts?.inactive;
  // The models the Modeller page lists: those of a provider (built-in global
  // models without one are not managed there).
  const providerModels = models.data
    ? modelEntries(models.data)
        .map(({ model }) => model)
        .filter((model) => model.provider_id != null)
    : [];
  const summary = crawler.data?.summary;
  const latest = audit.data?.logs[0];

  return (
    <section aria-labelledby={id} className={cn("flex flex-col gap-2", className)}>
      <Heading level={2} id={id} className="text-lg">
        {t("admin_areas_title")}
      </Heading>
      <List hasDividers edgeCompensation="inline">
        <AreaRow
          href="/admin/users"
          icon={Users}
          label={t("users")}
          query={users}
          state={
            metadata
              ? inactive != null
                ? t("admin_area_users", { active, inactive })
                : t("admin_area_users_active", { active })
              : null
          }
        />
        <AreaRow
          href="/admin/models"
          icon={Cpu}
          label={t("models")}
          query={models}
          state={
            models.data ? (
              <>
                {modelsAttention.length > 0 ? (
                  <>
                    <StatusLabel
                      status={
                        modelsAttention.some((row) => row.tone === "error") ? "error" : "warning"
                      }
                      label={t("admin_attention_title")}
                      className="text-[length:inherit]"
                    />
                    {" · "}
                  </>
                ) : null}
                {t("admin_area_models", {
                  active: providerModels.filter((model) => model.is_org_enabled).length,
                  total: providerModels.length
                })}
              </>
            ) : null
          }
        />
        <AreaRow
          href="/admin/usage"
          icon={Activity}
          label={t("usage")}
          query={usage}
          state={
            usage.data
              ? usage.data.total_token_usage === 0
                ? t("admin_overview_usage_empty")
                : t("admin_area_usage", {
                    tokens: format.format(usage.data.total_token_usage),
                    count: usage.data.models.length
                  })
              : null
          }
        />
        <AreaRow
          href="/admin/crawler"
          icon={Globe}
          label={t("admin_crawler_title")}
          query={crawler}
          state={
            summary ? (
              <>
                {scheduler ? (
                  <>
                    <StatusLabel
                      status={scheduler.tone}
                      label={scheduler.description}
                      className="text-[length:inherit]"
                    />
                    {" · "}
                  </>
                ) : null}
                {[
                  summary.issues > 0
                    ? t("admin_attention_crawler_issues", { count: summary.issues })
                    : null,
                  t("admin_area_crawler", {
                    ongoing: format.format(summary.ongoing),
                    queued: format.format(summary.queued)
                  })
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </>
            ) : null
          }
        />
        {settings.audit_logging_enabled ? (
          <AreaRow
            href="/admin/audit-logs"
            icon={History}
            label={t("audit_logs")}
            // Locked until an access session (401) is a state, not a failure.
            query={auditLocked ? SETTLED : audit}
            state={
              auditLocked
                ? t("admin_overview_audit_locked")
                : audit.data
                  ? latest
                    ? t.rich("admin_area_audit", {
                        event: latest.description,
                        time: () => <ClientTime value={latest.timestamp} format="auto" />
                      })
                    : t("admin_overview_audit_empty")
                  : null
            }
          />
        ) : null}
      </List>
    </section>
  );
}

/**
 * The admin landing: what needs an admin first, when anything does
 * (decision 30), then what is going on in the organisation, one card per
 * area with a link to its page, or on a phone one row per area. The audit
 * area appears only when audit logging is on (otherwise there is nothing to
 * list). Both layouts render until the width is known; CSS shows one.
 */
export function AdminOverviewPage() {
  const t = useTranslations();
  const { settings } = useAppContext();
  const phone = useMediaMatch(PHONE_QUERY);
  const layouts = useRef<HTMLDivElement>(null);
  useFocusAcrossLayouts(layouts, phone);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader
        title={t("overview")}
        // The cards' summary; a phone's rows say it themselves ("Läget just nu").
        description={<span className="max-md:hidden">{t("admin_overview_description")}</span>}
      />
      <AttentionSection />
      <div ref={layouts} className="contents">
        {phone !== false ? <AreaRows className="md:hidden" /> : null}
        {phone !== true ? (
          <div className="grid gap-4 max-md:hidden md:grid-cols-2">
            <UsersCard />
            <UsageCard />
            <CrawlerCard />
            {settings.audit_logging_enabled ? <AuditCard /> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

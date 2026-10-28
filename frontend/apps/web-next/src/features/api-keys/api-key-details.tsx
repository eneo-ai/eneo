"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DEFAULT_AUDIT_FILTERS,
  auditFiltersSearchParams
} from "@/features/admin/audit/audit-url-filters";
import { browserApi } from "@/lib/api/browser";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import Link from "@/lib/link";
import { RESOURCE_KEYS } from "./api-key-draft";
import { RESOURCE_LEVEL_LABEL, resourceLabelKey } from "./api-key-form";
import {
  apiKeyUsagePage,
  type ApiKey,
  type ApiKeyMode,
  type ResourcePermissionLevel
} from "./api-keys";

export type ApiKeyDetailsTab = "overview" | "usage";

/** Who a user is, as an admin reads it: the username, else the e-mail, else the id's start. */
export function userLabel(
  user: { email?: string | null; username?: string | null } | null | undefined,
  id: string | null | undefined
): string {
  return user?.username || user?.email || (id ? `${id.slice(0, 8)}…` : "—");
}

/** Where the audit log lists a key's calls and refused calls. */
export function apiKeyAuditHref(apiKey: ApiKey): string {
  const params = auditFiltersSearchParams({
    ...DEFAULT_AUDIT_FILTERS,
    search: apiKey.key_suffix,
    actions: ["api_key_used", "api_key_auth_failed"]
  });
  return `/admin/audit-logs?${params.toString()}`;
}

/**
 * A key's details from its actions menu: what bounds it (scope, access,
 * allowed origins or IPs, rate limit, expiry, owner) and why it was suspended
 * or revoked; and its usage: totals, when it was last seen and its calls,
 * page by page. An admin also gets the owner's page and the audit log.
 */
export function ApiKeyDetailsDialog({
  apiKey,
  mode,
  tab,
  open,
  onOpenChange,
  scopeName
}: {
  apiKey: ApiKey;
  mode: ApiKeyMode;
  /** The tab it opens on. */
  tab: ApiKeyDetailsTab;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The scope's space, assistant or app by name, when the caller knows it. */
  scopeName?: string;
}) {
  const t = useTranslations();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{apiKey.name}</DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {apiKey.key_prefix}…{apiKey.key_suffix}
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue={tab} className="gap-4">
          <TabsList>
            <TabsTrigger value="overview">{t("api_keys_admin_tab_overview")}</TabsTrigger>
            <TabsTrigger value="usage">{t("api_keys_admin_tab_usage")}</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">
            <Overview apiKey={apiKey} mode={mode} scopeName={scopeName} />
          </TabsContent>
          <TabsContent value="usage">
            <Usage apiKey={apiKey} mode={mode} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
      <dt className="text-muted-foreground w-44 shrink-0 text-sm">{label}</dt>
      <dd className="min-w-0 text-sm wrap-anywhere">{children}</dd>
    </div>
  );
}

function List({ values }: { values: string[] | null | undefined }) {
  if (!values?.length) return <>—</>;
  return (
    <ul className="font-mono text-xs">
      {values.map((value) => (
        <li key={value}>{value}</li>
      ))}
    </ul>
  );
}

function Overview({
  apiKey,
  mode,
  scopeName
}: {
  apiKey: ApiKey;
  mode: ApiKeyMode;
  scopeName?: string;
}) {
  const t = useTranslations();
  const never = t("api_keys_never");
  const permissions = apiKey.resource_permissions;
  const reason = (code: string | null | undefined, text: string | null | undefined) =>
    [code ? t(`api_keys_reason_${code}`) : null, text].filter(Boolean).join(" · ");
  const suspendedReason = reason(apiKey.suspended_reason_code, apiKey.suspended_reason_text);
  const revokedReason = reason(apiKey.revoked_reason_code, apiKey.revoked_reason_text);

  return (
    <dl className="flex flex-col gap-3">
      {apiKey.description && <Row label={t("description")}>{apiKey.description}</Row>}
      <Row label={t("api_keys_key_type")}>
        {apiKey.key_type === "pk_" ? t("api_keys_public_key") : t("api_keys_secret_key")}
        {apiKey.ownership === "service" ? ` · ${t("api_keys_ownership_service")}` : null}
      </Row>
      {apiKey.owner_user_id && (
        <Row label={t("api_keys_admin_owner_label")}>
          {userLabel(apiKey.owner_user, apiKey.owner_user_id)}
          {mode === "admin" && apiKey.owner_user?.email ? (
            <>
              {" · "}
              <Link
                href={`/admin/users?search=${encodeURIComponent(apiKey.owner_user.email)}`}
                className="underline"
              >
                {t("api_keys_admin_view_user")}
              </Link>
            </>
          ) : null}
        </Row>
      )}
      {apiKey.created_by_user_id && apiKey.created_by_user_id !== apiKey.owner_user_id && (
        <Row label={t("api_keys_admin_created_by_label")}>
          {userLabel(apiKey.created_by_user, apiKey.created_by_user_id)}
        </Row>
      )}
      <Row label={t("api_keys_scope")}>
        {t(`api_keys_scope_${apiKey.scope_type}`)}
        {apiKey.scope_id ? (
          <>
            {" · "}
            {scopeName ?? <span className="font-mono">{apiKey.scope_id}</span>}
          </>
        ) : null}
      </Row>
      <Row label={t("api_keys_permission_level")}>
        {permissions ? (
          <ul className="flex flex-col gap-0.5">
            {RESOURCE_KEYS.filter((key) => permissions[key] && permissions[key] !== "none").map(
              (key) => (
                <li key={key}>
                  {t(resourceLabelKey(key, apiKey.scope_type))}:{" "}
                  {t(RESOURCE_LEVEL_LABEL[permissions[key] as ResourcePermissionLevel])}
                </li>
              )
            )}
          </ul>
        ) : (
          t(`api_keys_permission_${apiKey.permission}`)
        )}
      </Row>
      {apiKey.key_type === "pk_" ? (
        <Row label={t("api_keys_allowed_origins")}>
          <List values={apiKey.allowed_origins} />
        </Row>
      ) : (
        <Row label={t("api_keys_allowed_ips")}>
          <List values={apiKey.allowed_ips} />
        </Row>
      )}
      <Row label={t("api_keys_rate_limit_label")}>
        {apiKey.rate_limit
          ? t("api_keys_rate_limit_value", { count: apiKey.rate_limit })
          : t("api_keys_default")}
      </Row>
      <Row label={t("api_keys_created")}>
        {apiKey.created_at ? <ClientTime value={apiKey.created_at} format="date_time" /> : "—"}
      </Row>
      <Row label={t("api_keys_last_used")}>
        {apiKey.last_used_at ? (
          <ClientTime value={apiKey.last_used_at} format="date_time" />
        ) : (
          never
        )}
      </Row>
      <Row label={t("api_keys_expires")}>
        {apiKey.expires_at ? <ClientTime value={apiKey.expires_at} format="date_time" /> : never}
      </Row>
      {apiKey.state === "suspended" && apiKey.suspended_at && (
        <Row label={t("api_keys_key_suspended")}>
          <ClientTime value={apiKey.suspended_at} format="date_time" />
          {suspendedReason && ` · ${suspendedReason}`}
        </Row>
      )}
      {apiKey.state === "revoked" && apiKey.revoked_at && (
        <Row label={t("api_keys_key_revoked")}>
          <ClientTime value={apiKey.revoked_at} format="date_time" />
          {revokedReason && ` · ${revokedReason}`}
        </Row>
      )}
    </dl>
  );
}

/** The key's calls: totals, when it was last seen and the events, page by page. */
function Usage({ apiKey, mode }: { apiKey: ApiKey; mode: ApiKeyMode }) {
  const t = useTranslations();
  const query = useInfiniteQuery({
    queryKey: ["api-key-usage", mode, apiKey.id],
    ...cursorPagination,
    queryFn: ({ pageParam }) => apiKeyUsagePage(browserApi, mode, apiKey.id, pageParam)
  });
  const pages = query.data?.pages ?? [];
  const summary = pages[0]?.summary;
  const events = flattenPages(pages);

  return (
    <QueryStateBoundary query={query} rows={4}>
      {() => (
        <div className="flex flex-col gap-4">
          {summary && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label={t("api_keys_admin_usage_total_events")} value={summary.total_events} />
              <Stat label={t("api_keys_admin_usage_success_events")} value={summary.used_events} />
              <Stat
                label={t("api_keys_admin_usage_failed_events")}
                value={summary.auth_failed_events}
              />
              <Stat
                label={t("api_keys_last_used")}
                value={
                  summary.last_seen_at ? (
                    <ClientTime value={summary.last_seen_at} format="relative" />
                  ) : (
                    t("api_keys_never")
                  )
                }
              />
            </div>
          )}

          {summary?.sampled_used_events && (
            <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-xs">
              {t("api_keys_admin_usage_sampled_notice")}
            </p>
          )}

          {events.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {t("api_keys_admin_usage_empty")}
            </p>
          ) : (
            <Table aria-label={t("api_keys_admin_tab_usage")}>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">{t("audit_timestamp")}</TableHead>
                  <TableHead>{t("action")}</TableHead>
                  <TableHead>{t("api_keys_admin_usage_request")}</TableHead>
                  <TableHead>{t("api_keys_admin_usage_ip_origin")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {events.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                      <ClientTime value={event.timestamp} format="date_time" />
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={
                          event.outcome === "used" || event.outcome === "success"
                            ? "border-success/40 text-success"
                            : "border-destructive/40 text-destructive"
                        }
                      >
                        {event.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground font-mono text-xs">
                      {[event.method, event.request_path].filter(Boolean).join(" ") || "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground font-mono text-xs">
                      {event.ip_address || event.origin || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          <div className="flex items-center justify-between">
            {mode === "admin" ? (
              <Button variant="link" size="sm" className="px-0" asChild>
                <Link href={apiKeyAuditHref(apiKey)}>
                  <ExternalLink className="size-3.5" />
                  {t("api_keys_admin_usage_open_audit_logs")}
                </Link>
              </Button>
            ) : (
              <span />
            )}
            <LoadMore query={query} label={t("api_keys_admin_usage_load_more")} />
          </div>
        </div>
      )}
    </QueryStateBoundary>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-muted-foreground text-xs">{label}</div>
    </div>
  );
}

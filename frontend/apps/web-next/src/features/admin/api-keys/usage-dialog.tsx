"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
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
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { formatDateTime } from "@/lib/format";

type ApiKey = Schema<"ApiKeyV2">;

/** Per-key usage drill-down: summary stats + paginated event log. */
export function ApiKeyUsageDialog({
  apiKey,
  open,
  onOpenChange
}: {
  apiKey: ApiKey;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();

  const query = useInfiniteQuery({
    queryKey: ["admin-api-key-usage", apiKey.id],
    enabled: open,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        browserApi.GET("/api/v1/admin/api-keys/{id}/usage", {
          params: {
            path: { id: apiKey.id },
            query: { cursor: pageParam ?? undefined, limit: 50 }
          }
        })
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined
  });

  const pages = query.data?.pages ?? [];
  const summary = pages[0]?.summary;
  const events = pages.flatMap((page) => page.items);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {apiKey.name} · {t("api_keys_admin_tab_usage")}
          </DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {apiKey.key_prefix}…{apiKey.key_suffix}
          </DialogDescription>
        </DialogHeader>

        {query.isPending ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <div className="flex flex-col gap-4">
            {summary && (
              <div className="grid grid-cols-3 gap-2">
                <Stat label={t("api_keys_admin_usage_total_events")} value={summary.total_events} />
                <Stat
                  label={t("api_keys_admin_usage_success_events")}
                  value={summary.used_events}
                />
                <Stat
                  label={t("api_keys_admin_usage_failed_events")}
                  value={summary.auth_failed_events}
                />
              </div>
            )}

            {summary?.sampled_used_events && (
              <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                {t("api_keys_admin_usage_sampled_notice")}
              </p>
            )}

            {events.length === 0 ? (
              <p className="text-muted-foreground py-6 text-center text-sm">
                {t("api_keys_admin_usage_empty")}
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="whitespace-nowrap">{t("audit_timestamp")}</TableHead>
                    <TableHead>{t("action")}</TableHead>
                    <TableHead>{t("api_keys_admin_usage_request")}</TableHead>
                    <TableHead>IP</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((event) => (
                    <TableRow key={event.id}>
                      <TableCell className="text-muted-foreground font-mono text-xs whitespace-nowrap">
                        {formatDateTime(event.timestamp)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            event.outcome === "used" || event.outcome === "success"
                              ? "border-green-200 text-green-700 dark:border-green-900 dark:text-green-400"
                              : "border-red-200 text-red-700 dark:border-red-900 dark:text-red-400"
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
              <Button variant="link" size="sm" className="px-0" asChild>
                <Link href={`/admin/audit-logs?search=${apiKey.key_suffix}`}>
                  <ExternalLink className="size-3.5" />
                  {t("api_keys_admin_usage_open_audit_logs")}
                </Link>
              </Button>
              {query.hasNextPage && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={query.isFetchingNextPage}
                  onClick={() => query.fetchNextPage()}
                >
                  {t("api_keys_admin_usage_load_more")}
                </Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-muted-foreground text-xs">{label}</div>
    </div>
  );
}

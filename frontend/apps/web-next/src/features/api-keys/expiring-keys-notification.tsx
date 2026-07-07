"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { summaryToDisplayItems, type ExpiringKeyDisplayItem } from "./expiration-utils";

const MAX_VISIBLE = 5;

function hasDuplicateName(name: string, items: ExpiringKeyDisplayItem[]): boolean {
  return items.filter((item) => item.name === name).length > 1;
}

function itemExpiryText(
  item: ExpiringKeyDisplayItem,
  t: ReturnType<typeof useTranslations>
): string {
  if (item.level === "expired") return t("api_keys_expiring_item_expired");
  if (item.daysRemaining === 0) return t("api_keys_expiring_item_today");
  if (item.daysRemaining === 1) return t("api_keys_expiring_item_tomorrow");
  return t("api_keys_expiring_item_days", { days: item.daysRemaining });
}

export function ExpiringKeysNotification() {
  const t = useTranslations();
  const { settings } = useAppContext();
  const featureEnabled = settings.api_key_expiry_notifications !== false;

  const preferences = useQuery({
    queryKey: ["api-key-notification-preferences"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/api-keys/notification-preferences")),
    enabled: featureEnabled,
    staleTime: 60_000
  });
  const subscriptions = useQuery({
    queryKey: ["api-key-notification-subscriptions"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/api-keys/notification-subscriptions")),
    enabled: featureEnabled,
    staleTime: 60_000
  });

  const daysWindow = Math.max(...(preferences.data?.days_before_expiry ?? [30]), 1);
  const hasSubscriptions = (subscriptions.data?.items.length ?? 0) > 0;
  const summary = useQuery({
    queryKey: ["api-keys", "expiring-soon", "subscribed", daysWindow],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/api-keys/expiring-soon", {
          params: { query: { days: daysWindow, mode: "subscribed" } }
        })
      ),
    enabled: featureEnabled && (preferences.data?.enabled ?? false) && hasSubscriptions,
    staleTime: 60_000
  });

  const items = summary.data ? summaryToDisplayItems(summary.data.items) : [];
  if (items.length === 0) return null;

  const counts = summary.data?.counts_by_severity ?? {};
  const expiredCount = counts.expired ?? 0;
  const urgentCount = counts.urgent ?? 0;
  const warningCount = counts.warning ?? 0;
  const hasUrgent = expiredCount + urgentCount > 0;
  const visibleItems = items.slice(0, MAX_VISIBLE);
  const overflowCount = items.length - MAX_VISIBLE;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("api_keys_expiring_bell_title")}
          className="relative"
        >
          <Bell className="size-4" />
          <span
            className={`absolute top-1.5 right-1.5 size-2 rounded-full ${
              hasUrgent ? "bg-destructive" : "bg-warning"
            }`}
          />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-96 p-2">
        <div className="flex flex-col gap-2" role="status">
          <div className="px-2">
            <p className="font-medium">{t("api_keys_expiring_bell_title")}</p>
            <p className="text-muted-foreground text-xs">
              {expiredCount > 0
                ? t("api_keys_expiring_bell_summary_expired", { count: expiredCount })
                : null}
              {expiredCount > 0 && urgentCount > 0 ? ", " : null}
              {urgentCount > 0
                ? t("api_keys_expiring_bell_summary_urgent", { count: urgentCount })
                : null}
              {(expiredCount > 0 || urgentCount > 0) && warningCount > 0 ? ", " : null}
              {warningCount > 0
                ? t("api_keys_expiring_bell_summary_warning", { count: warningCount })
                : null}
            </p>
          </div>
          <div
            className={`rounded-lg border px-2 py-1 shadow-sm ${
              hasUrgent ? "bg-destructive/5" : warningCount > 0 ? "bg-warning/5" : "bg-card"
            }`}
          >
            {visibleItems.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between gap-3 border-b px-1 py-2 last:border-b-0"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={`shrink-0 rounded-full ${
                      item.level === "expired" || item.level === "urgent"
                        ? "bg-destructive size-2.5"
                        : "bg-warning size-2"
                    }`}
                  />
                  <span className="truncate text-sm" title={item.name}>
                    {item.name}
                  </span>
                  {item.keySuffix && hasDuplicateName(item.name, items) ? (
                    <span className="text-muted-foreground shrink-0 font-mono text-xs">
                      ...{item.keySuffix}
                    </span>
                  ) : null}
                </div>
                <span
                  className={`shrink-0 text-xs ${
                    item.level === "expired" || item.level === "urgent"
                      ? "text-destructive"
                      : "text-warning"
                  }`}
                >
                  {itemExpiryText(item, t)}
                </span>
              </div>
            ))}
            {overflowCount > 0 ? (
              <div className="text-muted-foreground px-1 py-2 text-xs">
                {t("api_keys_expiring_bell_more", { count: overflowCount })}
              </div>
            ) : null}
          </div>
          <Button asChild variant="ghost" className="justify-between">
            <Link href="/account/api-keys">
              {t("api_keys_expiring_bell_manage")}
              <ChevronRight className="size-4" />
            </Link>
          </Button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

"use client";

import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { summaryToDisplayItems, type ExpiringKeyDisplayItem } from "./expiration-utils";

const MAX_VISIBLE = 5;

function hasDuplicateName(name: string, items: ExpiringKeyDisplayItem[]): boolean {
  return items.filter((item) => item.name === name).length > 1;
}

function isUrgent(item: ExpiringKeyDisplayItem): boolean {
  return item.level === "expired" || item.level === "urgent";
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

/**
 * The bell for API keys the user follows that expire soon (shown only when
 * there are any), with the list in a popover. An Astryx Popover lives in the
 * top layer next to its trigger, so it also opens inside the navigation drawer.
 */
export function ExpiringKeysNotification({ alignment = "end" }: { alignment?: "start" | "end" }) {
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
  const summaryParts = [
    expiredCount > 0 ? t("api_keys_expiring_bell_summary_expired", { count: expiredCount }) : null,
    urgentCount > 0 ? t("api_keys_expiring_bell_summary_urgent", { count: urgentCount }) : null,
    warningCount > 0 ? t("api_keys_expiring_bell_summary_warning", { count: warningCount }) : null
  ].filter((part): part is string => part !== null);

  return (
    <Popover
      label={t("api_keys_expiring_bell_title")}
      placement="below"
      alignment={alignment}
      width={384}
      content={
        <div className="flex flex-col gap-2">
          <div className="px-2">
            <p className="font-medium">{t("api_keys_expiring_bell_title")}</p>
            <p className="text-ax-text-secondary text-xs">{summaryParts.join(", ")}</p>
          </div>
          <ul
            className={cn(
              "border-ax-border rounded-ax-container border px-2 py-1",
              hasUrgent ? "bg-ax-error-muted" : warningCount > 0 ? "bg-ax-warning-muted" : ""
            )}
          >
            {visibleItems.map((item) => (
              <li
                key={item.id}
                className="border-ax-border flex items-center justify-between gap-3 border-b px-1 py-2 last:border-b-0"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "shrink-0 rounded-full",
                      isUrgent(item) ? "bg-ax-error size-2.5" : "bg-ax-warning size-2"
                    )}
                  />
                  <span className="truncate text-sm" title={item.name}>
                    {item.name}
                  </span>
                  {item.keySuffix && hasDuplicateName(item.name, items) ? (
                    <span className="text-ax-text-secondary shrink-0 font-mono text-xs">
                      ...{item.keySuffix}
                    </span>
                  ) : null}
                </span>
                <span
                  className={cn(
                    "shrink-0 text-xs",
                    isUrgent(item) ? "text-ax-error" : "text-ax-warning"
                  )}
                >
                  {itemExpiryText(item, t)}
                </span>
              </li>
            ))}
            {overflowCount > 0 ? (
              <li className="text-ax-text-secondary px-1 py-2 text-xs">
                {t("api_keys_expiring_bell_more", { count: overflowCount })}
              </li>
            ) : null}
          </ul>
          <Button
            href="/account/api-keys"
            variant="ghost"
            label={t("api_keys_expiring_bell_manage")}
            endContent={<Icon icon={ChevronRight} />}
            width="100%"
            className="justify-between"
          />
        </div>
      }
    >
      <IconButton
        variant="ghost"
        label={t("api_keys_expiring_bell_title")}
        tooltip={t("api_keys_expiring_bell_title")}
        icon={
          <span className="relative inline-flex">
            <Icon icon={Bell} />
            <span
              aria-hidden="true"
              className={cn(
                "absolute -end-0.5 -top-0.5 size-2 rounded-full",
                hasUrgent ? "bg-ax-error" : "bg-ax-warning"
              )}
            />
          </span>
        }
      />
    </Popover>
  );
}

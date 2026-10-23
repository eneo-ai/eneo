"use client";

import { CircleAlert, Database, HardDrive, Info } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Schema } from "@/lib/api/models";
import {
  managedContentBytes,
  moveCounts,
  storageSize,
  type Inventory,
  type Moves
} from "./storage-facts";
import type { StorageKind } from "./storage-policy";

export function StorageOverview({
  inventory,
  inventoryLoading,
  inventoryError,
  moves,
  movesLoading,
  movesError,
  activeTarget,
  objectStoreCapability,
  onInventoryRetry
}: {
  inventory: Inventory | null;
  inventoryLoading: boolean;
  inventoryError: boolean;
  moves: Moves | null;
  movesLoading: boolean;
  movesError: boolean;
  activeTarget: StorageKind;
  objectStoreCapability: Schema<"CapabilityPublic"> | undefined;
  onInventoryRetry: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const managed = inventory ? managedContentBytes(inventory) : null;
  const counts = moves ? moveCounts(moves) : { pending: 0, failed: 0 };
  const ready = objectStoreCapability?.readiness_code === "ready";
  const notConfigured =
    !objectStoreCapability ||
    objectStoreCapability.readiness_code === "object_store_not_configured";
  const targetLabel = (target: StorageKind) =>
    t(
      target === "postgres_inline"
        ? "storage_target_postgres_inline"
        : "storage_target_object_store"
    );
  const formatCount = (value: number) => new Intl.NumberFormat(locale).format(value);
  const formatBytes = (value: number, digits = 0) => {
    const display = storageSize(value, locale, digits);
    return `${display.amount} ${t(`storage_unit_${display.unit.toLowerCase()}`)}`;
  };
  const formatDate = (value: string | null) => {
    if (!value) return t("storage_inventory_not_available");
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? t("storage_inventory_not_available")
      : new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(date);
  };
  const moveStatus = movesLoading
    ? { label: t("loading"), detail: t("storage_moves_loading"), variant: "outline" as const }
    : movesError || !moves
      ? {
          label: t("storage_inventory_not_available"),
          detail: t("storage_moves_load_error_title"),
          variant: "destructive" as const
        }
      : counts.failed > 0
        ? {
            label: t("storage_overview_move_attention"),
            detail: t("storage_overview_move_failed", { count: formatCount(counts.failed) }),
            variant: "destructive" as const
          }
        : counts.pending > 0 && moves.paused
          ? {
              label: t("storage_moves_status_paused"),
              detail: t("storage_overview_move_waiting", { count: formatCount(counts.pending) }),
              variant: "outline" as const
            }
          : counts.pending > 0
            ? {
                label: t("storage_moves_status_running"),
                detail: t("storage_overview_move_waiting", { count: formatCount(counts.pending) }),
                variant: "default" as const
              }
            : {
                label: t("storage_overview_move_idle"),
                detail: moves.paused
                  ? t("storage_overview_move_idle_paused")
                  : t("storage_overview_move_empty"),
                variant: "outline" as const
              };

  return (
    <section aria-labelledby="storage-overview-title" className="space-y-4">
      <div>
        <h2 id="storage-overview-title" className="text-lg font-semibold">
          {t("storage_overview_title")}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">{t("storage_overview_description")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="flex items-center justify-between">
            <CardTitle className="text-sm">{t("storage_overview_active_target")}</CardTitle>
            <Badge variant="outline">{t("storage_overview_active")}</Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              {activeTarget === "postgres_inline" ? (
                <Database className="size-5" />
              ) : (
                <HardDrive className="size-5" />
              )}
              <strong>{targetLabel(activeTarget)}</strong>
            </div>
            <p className="text-muted-foreground text-sm">
              {t("storage_overview_active_target_help")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex items-center justify-between">
            <CardTitle className="text-sm">{t("storage_target_object_store")}</CardTitle>
            <Badge variant={ready || notConfigured ? "outline" : "destructive"}>
              {ready
                ? t("storage_connection_summary_configured")
                : notConfigured
                  ? t("storage_connection_summary_unconfigured")
                  : t("storage_overview_attention")}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            <strong>
              {ready
                ? t("storage_target_ready")
                : notConfigured
                  ? t("storage_connection_empty_title")
                  : t(`storage_readiness_${objectStoreCapability.readiness_code}`)}
            </strong>
            <p className="text-muted-foreground text-sm">
              {ready
                ? t("storage_overview_object_store_ready")
                : t("storage_overview_object_store_help")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("storage_inventory_managed_total")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {managed ? (
              <>
                <strong className="tabular-nums">{formatBytes(managed.total, 2)}</strong>
                <div
                  className="bg-muted flex h-2 overflow-hidden rounded-full"
                  role="img"
                  aria-label={t("storage_overview_distribution_label", {
                    postgresql: formatBytes(managed.postgresql, 2),
                    objectStore: formatBytes(managed.objectStore, 2)
                  })}
                >
                  {managed.total > 0 && (
                    <>
                      <span
                        className="bg-primary h-full"
                        style={{ width: `${(managed.postgresql / managed.total) * 100}%` }}
                      />
                      <span
                        className="bg-success h-full"
                        style={{ width: `${(managed.objectStore / managed.total) * 100}%` }}
                      />
                    </>
                  )}
                </div>
                <dl className="text-muted-foreground space-y-1 text-xs">
                  <div className="flex justify-between">
                    <dt>{targetLabel("postgres_inline")}</dt>
                    <dd>{formatBytes(managed.postgresql, 2)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>{targetLabel("object_store")}</dt>
                    <dd>{formatBytes(managed.objectStore, 2)}</dd>
                  </div>
                </dl>
              </>
            ) : (
              <p className="text-muted-foreground text-sm">
                {inventoryLoading
                  ? t("storage_inventory_loading")
                  : t("storage_inventory_not_available")}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex items-center justify-between">
            <CardTitle className="text-sm">{t("storage_overview_moves")}</CardTitle>
            <Badge variant={moveStatus.variant}>{moveStatus.label}</Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            <strong className="tabular-nums">
              {formatCount(counts.pending + counts.failed)}{" "}
              <span className="text-muted-foreground text-sm font-normal">
                {t("storage_overview_items")}
              </span>
            </strong>
            <p className="text-muted-foreground text-sm">{moveStatus.detail}</p>
          </CardContent>
        </Card>
      </div>

      {inventoryError && (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" />
          <AlertTitle>{t("storage_inventory_error_title")}</AlertTitle>
          <AlertDescription>
            <p>{t("storage_inventory_error_description")}</p>
            <Button variant="outline" size="sm" onClick={onInventoryRetry}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {inventory && (
        <div>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={detailsOpen}
            aria-controls="storage-inventory-details"
            onClick={() => setDetailsOpen((open) => !open)}
          >
            {detailsOpen ? t("storage_inventory_hide_details") : t("storage_inventory_caption")}
          </Button>
          {detailsOpen && (
            <div id="storage-inventory-details" className="mt-3 space-y-5 rounded-lg border p-4">
              <div>
                <h3 className="text-sm font-semibold">{t("storage_inventory_managed_caption")}</h3>
                <p className="text-muted-foreground text-sm">
                  {t("storage_inventory_managed_note")}
                </p>
              </div>
              {inventory.inventory.length === 0 ? (
                <p className="text-muted-foreground text-sm">{t("storage_inventory_empty")}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[740px] text-sm">
                    <caption className="sr-only">{t("storage_inventory_managed_caption")}</caption>
                    <thead>
                      <tr className="border-b text-left">
                        <th className="p-2">{t("storage_inventory_owner")}</th>
                        <th className="p-2">{t("storage_inventory_target")}</th>
                        <th className="p-2">{t("storage_inventory_state")}</th>
                        <th className="p-2">{t("storage_inventory_count")}</th>
                        <th className="p-2">{t("storage_inventory_bytes")}</th>
                        <th className="p-2">{t("storage_inventory_oldest")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inventory.inventory.map((item) => (
                        <tr
                          key={`${item.owner}-${item.target}-${item.state}`}
                          className="border-b last:border-0"
                        >
                          <td className="p-2 font-medium">
                            {t(`storage_inventory_owner_${item.owner}`)}
                          </td>
                          <td className="p-2">{targetLabel(item.target)}</td>
                          <td className="p-2">{t(`storage_content_state_${item.state}`)}</td>
                          <td className="p-2 tabular-nums">{formatCount(item.count)}</td>
                          <td className="p-2 tabular-nums">{formatBytes(item.bytes)}</td>
                          <td className="p-2">{formatDate(item.oldest_created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {inventory.postgresql_allocation ? (
                <div className="space-y-2 border-t pt-4">
                  <h3 className="text-sm font-semibold">
                    {t("storage_inventory_allocation_caption")}
                  </h3>
                  <p className="text-muted-foreground text-sm">
                    {t("storage_inventory_allocation_note")}
                  </p>
                  <dl className="grid gap-2 text-sm sm:grid-cols-2">
                    {(
                      [
                        "inline_content_bytes",
                        "searchable_knowledge_bytes",
                        "other_bytes",
                        "total_bytes"
                      ] as const
                    ).map((field) => (
                      <div key={field} className="flex justify-between gap-3 border-b py-1">
                        <dt>
                          {t(
                            field === "inline_content_bytes"
                              ? "storage_inventory_allocation_inline"
                              : field === "searchable_knowledge_bytes"
                                ? "storage_inventory_allocation_searchable_knowledge"
                                : field === "other_bytes"
                                  ? "storage_inventory_allocation_other"
                                  : "storage_inventory_allocation_total"
                          )}
                        </dt>
                        <dd className="tabular-nums">
                          {formatBytes(inventory.postgresql_allocation![field], 1)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ) : (
                <Alert>
                  <Info className="size-4" />
                  <AlertTitle>{t("storage_inventory_allocation_unavailable_title")}</AlertTitle>
                  <AlertDescription>
                    {t("storage_inventory_allocation_unavailable_description")}
                  </AlertDescription>
                </Alert>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

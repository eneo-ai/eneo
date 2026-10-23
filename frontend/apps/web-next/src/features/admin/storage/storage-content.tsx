"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Info } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { reconcileMoves, storageSize, type Moves } from "./storage-facts";
import { StorageOverview } from "./storage-overview";
import type { DeploymentPolicy, StorageKind } from "./storage-policy";

export function StorageContent({
  policy,
  dirtyPolicyDraft,
  policyBusy,
  onAuthorityRevoked,
  onPolicyPaused,
  onRefreshPolicy
}: {
  policy: DeploymentPolicy;
  dirtyPolicyDraft: boolean;
  policyBusy: boolean;
  onAuthorityRevoked: () => void;
  onPolicyPaused: (previousRevision: number, nextRevision: number, paused: boolean) => void;
  onRefreshPolicy: (preserveDraft: boolean) => Promise<void>;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [moveTarget, setMoveTarget] = useState<StorageKind>(policy.policy.new_write_storage_target);
  const [moveLimit, setMoveLimit] = useState(25);
  const [pending, setPending] = useState<"queue" | "pause" | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [outcomeUnknown, setOutcomeUnknown] = useState(false);
  const [actionStale, setActionStale] = useState(false);
  const [queueResult, setQueueResult] = useState<{
    queued_count: number;
    target_too_large_count: number;
  } | null>(null);
  const capability = policy.capabilities.find((item) => item.target === "object_store");
  const objectStoreUnavailable = capability?.selectable !== true;

  const inventory = useQuery({
    queryKey: ["storage-inventory"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/admin/object-content-inventory")),
    retry: false,
    refetchOnWindowFocus: false
  });
  const moves = useQuery({
    queryKey: ["storage-moves"],
    queryFn: async () => {
      const next = await unwrap(browserApi.GET("/api/v1/admin/object-content-moves"));
      const previous = queryClient.getQueryData<Moves>(["storage-moves"]) ?? null;
      return reconcileMoves(previous, next, policy);
    },
    retry: false,
    refetchOnWindowFocus: false
  });

  useEffect(() => {
    if (
      (inventory.error instanceof EneoApiError && inventory.error.status === 403) ||
      (moves.error instanceof EneoApiError && moves.error.status === 403)
    )
      onAuthorityRevoked();
  }, [inventory.error, moves.error, onAuthorityRevoked]);

  const moveData: Moves | null = moves.data ? reconcileMoves(null, moves.data, policy) : null;
  const formatCount = (value: number) => new Intl.NumberFormat(locale).format(value);
  const formatBytes = (value: number) => {
    const size = storageSize(value, locale);
    return `${size.amount} ${t(`storage_unit_${size.unit.toLowerCase()}`)}`;
  };
  const formatDate = (value: string | null) => {
    if (!value) return t("storage_inventory_not_available");
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? t("storage_inventory_not_available")
      : new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(date);
  };
  const targetLabel = (target: StorageKind) =>
    t(
      target === "postgres_inline"
        ? "storage_target_postgres_inline"
        : "storage_target_object_store"
    );
  const validLimit = Number.isSafeInteger(moveLimit) && moveLimit >= 1 && moveLimit <= 100;
  const queueUnavailable =
    (moveTarget === "object_store" && objectStoreUnavailable) ||
    !validLimit ||
    moves.isFetching ||
    moves.isError ||
    !moveData ||
    pending !== null;
  const pauseUnavailable =
    !moveData || moves.isFetching || moves.isError || pending !== null || policyBusy;

  function resetAction() {
    setActionError(false);
    setOutcomeUnknown(false);
    setActionStale(false);
    setQueueResult(null);
  }

  async function queueMoves() {
    if (queueUnavailable) return;
    setPending("queue");
    resetAction();
    try {
      const result = await unwrap(
        browserApi.POST("/api/v1/admin/object-content-moves", {
          body: { target: moveTarget, limit: moveLimit }
        })
      );
      setQueueResult(result);
      await moves.refetch();
    } catch (error) {
      if (error instanceof EneoApiError && error.status === 403) onAuthorityRevoked();
      else if (error instanceof EneoApiError && error.status === 503) setActionError(true);
      else {
        setOutcomeUnknown(true);
        await moves.refetch();
      }
    } finally {
      setPending(null);
      setConfirmOpen(false);
    }
  }

  async function setPaused() {
    if (pauseUnavailable || !moveData) return;
    setPending("pause");
    resetAction();
    try {
      const result = await unwrap(
        browserApi.PUT("/api/v1/admin/object-content-moves/pause", {
          body: { expected_revision: moveData.policy_revision, moves_paused: !moveData.paused }
        })
      );
      queryClient.setQueryData<Moves>(["storage-moves"], {
        ...moveData,
        policy_revision: result.policy_revision,
        paused: result.paused
      });
      onPolicyPaused(moveData.policy_revision, result.policy_revision, result.paused);
    } catch (error) {
      if (error instanceof EneoApiError && error.status === 403) onAuthorityRevoked();
      else if (error instanceof EneoApiError && error.status === 409) setActionStale(true);
      else {
        setOutcomeUnknown(true);
        await onRefreshPolicy(dirtyPolicyDraft);
        setOutcomeUnknown(true);
      }
    } finally {
      setPending(null);
    }
  }

  return (
    <>
      <StorageOverview
        inventory={inventory.data ?? null}
        inventoryLoading={inventory.isPending || inventory.isFetching}
        inventoryError={inventory.isError}
        moves={moveData}
        movesLoading={moves.isPending || moves.isFetching}
        movesError={moves.isError}
        activeTarget={policy.policy.new_write_storage_target}
        objectStoreCapability={capability}
        onInventoryRetry={() => void inventory.refetch()}
      />
      <SettingsGroup title={t("storage_moves_title")} description={t("storage_moves_description")}>
        {objectStoreUnavailable && (
          <Alert>
            <Info className="size-4" />
            <AlertTitle>{t("storage_moves_store_unavailable")}</AlertTitle>
            <AlertDescription>{t("storage_moves_store_unavailable_description")}</AlertDescription>
          </Alert>
        )}
        {actionStale && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_moves_stale_title")}</AlertTitle>
            <AlertDescription>
              <p>{t("storage_moves_stale_description")}</p>
              <Button variant="outline" size="sm" onClick={() => void onRefreshPolicy(false)}>
                {t("storage_settings_reload_latest")}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {actionError && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_moves_action_error_title")}</AlertTitle>
            <AlertDescription>{t("storage_moves_action_error_description")}</AlertDescription>
          </Alert>
        )}
        {outcomeUnknown && (
          <Alert>
            <Info className="size-4" />
            <AlertTitle>{t("storage_moves_outcome_unknown_title")}</AlertTitle>
            <AlertDescription>{t("storage_moves_outcome_unknown_description")}</AlertDescription>
          </Alert>
        )}
        {queueResult && (
          <Alert>
            <CircleCheck className="size-4" />
            <AlertTitle>
              {t("storage_moves_queue_result", {
                queued: formatCount(queueResult.queued_count),
                tooLarge: formatCount(queueResult.target_too_large_count)
              })}
            </AlertTitle>
          </Alert>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="move-target">{t("storage_moves_target")}</Label>
            <select
              id="move-target"
              value={moveTarget}
              onChange={(event) => setMoveTarget(event.target.value as StorageKind)}
              disabled={pending !== null}
              aria-invalid={moveTarget === "object_store" && objectStoreUnavailable}
              className="bg-background border-input h-9 w-full rounded-md border px-3 text-sm"
            >
              <option value="object_store">{targetLabel("object_store")}</option>
              <option value="postgres_inline">{targetLabel("postgres_inline")}</option>
            </select>
            <p className="text-muted-foreground text-sm">{t("storage_settings_target_help")}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="move-limit">{t("storage_moves_limit")}</Label>
            <Input
              id="move-limit"
              type="number"
              min="1"
              max="100"
              step="1"
              value={Number.isNaN(moveLimit) ? "" : moveLimit}
              aria-invalid={!validLimit}
              disabled={pending !== null}
              onChange={(event) =>
                setMoveLimit(event.target.value === "" ? Number.NaN : Number(event.target.value))
              }
            />
            <p className="text-muted-foreground text-sm">{t("storage_moves_limit_help")}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button disabled={queueUnavailable} onClick={() => setConfirmOpen(true)}>
            {t("storage_moves_queue")}
          </Button>
          {moveData && (
            <Button variant="outline" disabled={pauseUnavailable} onClick={() => void setPaused()}>
              {moveData.paused ? t("storage_moves_resume") : t("storage_moves_pause")}
            </Button>
          )}
        </div>
        {moves.isError && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_moves_load_error_title")}</AlertTitle>
            <AlertDescription>
              <p>{t("storage_moves_load_error_description")}</p>
              <Button variant="outline" size="sm" onClick={() => void moves.refetch()}>
                {t("storage_moves_retry")}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {moveData?.moves.length === 0 ? (
          <Alert>
            <CircleCheck className="size-4" />
            <AlertTitle>{t("storage_overview_move_idle")}</AlertTitle>
            <AlertDescription>{t("storage_moves_empty")}</AlertDescription>
          </Alert>
        ) : moveData ? (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-sm">
              <caption className="sr-only">{t("storage_moves_caption")}</caption>
              <thead>
                <tr className="border-b text-left">
                  <th className="p-2">{t("storage_moves_target")}</th>
                  <th className="p-2">{t("storage_moves_state")}</th>
                  <th className="p-2">{t("storage_moves_failure")}</th>
                  <th className="p-2">{t("storage_moves_count")}</th>
                  <th className="p-2">{t("storage_moves_bytes")}</th>
                  <th className="p-2">{t("storage_moves_oldest_update")}</th>
                </tr>
              </thead>
              <tbody>
                {moveData.moves.map((item) => (
                  <tr
                    key={`${item.target}-${item.state}-${item.failure_code}`}
                    className="border-b last:border-0"
                  >
                    <td className="p-2">{targetLabel(item.target)}</td>
                    <td className="p-2">{t(`storage_move_state_${item.state}`)}</td>
                    <td className="p-2">
                      {item.failure_code
                        ? t(`storage_move_failure_${item.failure_code}`)
                        : t("storage_moves_failure_none")}
                    </td>
                    <td className="p-2 tabular-nums">{formatCount(item.count)}</td>
                    <td className="p-2 tabular-nums">{formatBytes(item.bytes)}</td>
                    <td className="p-2">{formatDate(item.oldest_updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : moves.isPending ? (
          <p className="text-muted-foreground text-sm">{t("storage_moves_loading")}</p>
        ) : null}
      </SettingsGroup>
      <ConfirmDialogControlled
        open={confirmOpen}
        onOpenChange={(open) => {
          if (pending === null) setConfirmOpen(open);
        }}
        title={t("storage_moves_confirm_title")}
        description={t("storage_moves_confirm_description", {
          count: formatCount(moveLimit),
          target: targetLabel(moveTarget)
        })}
        confirmLabel={t("storage_moves_confirm_action")}
        pending={pending === "queue"}
        onConfirm={() => void queueMoves()}
      />
    </>
  );
}

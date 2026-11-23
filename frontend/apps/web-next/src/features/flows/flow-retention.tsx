import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { flowKeys, type FlowPublic } from "./flows-api";

/** The backend's bounds (MIN_RETENTION_DAYS, MAX_RETENTION_DAYS); it checks them again. */
const MIN_DAYS = 1;
const MAX_DAYS = 2555;

const policyKey = (flowId: string) => ["flows", "retention", flowId] as const;
type PolicySettings = Schema<"FlowRunRetentionPolicySettings">;

export function retentionDaysValid(days: number | null): days is number {
  return days !== null && Number.isInteger(days) && days >= MIN_DAYS && days <= MAX_DAYS;
}

/** The space's cap from a 9086 refusal, or null for any other error. */
function refusedCap(error: unknown): number | null {
  if (!(error instanceof EneoApiError) || error.code !== 9086) return null;
  const { cap_days: days, cap_origin: origin } = error.context ?? {};
  return origin === "space" && typeof days === "number" ? days : null;
}

/**
 * What applies to the flow's run history, in a line: the days and where from. A saved
 * flow time longer than the space's is shown too, since the space's shorter time wins.
 */
export function FlowRetentionSummary({ flow }: { flow: FlowPublic }) {
  const t = useTranslations();
  const retention = flow.run_history_retention;
  if (retention.state === "off") return <>{t("flows_retention_off")}</>;
  const saved = retention.contributors.flow?.days;
  return (
    <>
      {t("flows_retention_days", { days: retention.effective_days })},{" "}
      {t(`flows_retention_source_${retention.source}`)}
      {saved !== undefined && saved > retention.effective_days ? (
        <span className="text-ax-text-secondary mt-0.5 block text-sm">
          {t("flows_retention_longer_saved", { days: saved })}
        </span>
      ) : null}
    </>
  );
}

/**
 * The flow's own time, or none to use the space's. It has an endpoint of its own and
 * stays open on a published flow: it changes when runs may be purged, not the
 * definition, so it is no part of the settings form. Saving deletes nothing.
 */
export function FlowRetentionDialog({
  flow,
  open,
  onOpenChange
}: {
  flow: FlowPublic;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const phone = usePhoneScreen();
  const policy = useQuery({
    queryKey: policyKey(flow.id),
    enabled: open,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
          params: { path: { flow_id: flow.id } },
          signal
        })
      )
  });
  return (
    <Dialog
      isOpen={open}
      onOpenChange={onOpenChange}
      purpose="form"
      width={480}
      variant={phone ? "fullscreen" : "standard"}
      // Astryx finds the title when the dialog mounts, and a closed one renders nothing.
      aria-label={t("flows_retention_heading")}
    >
      {!open ? null : policy.data ? (
        <RetentionForm flow={flow} settings={policy.data} onClose={() => onOpenChange(false)} />
      ) : (
        <Layout
          header={
            <DialogHeader
              title={t("flows_retention_heading")}
              subtitle={t("flows_retention_dialog_subtitle")}
              onOpenChange={onOpenChange}
            />
          }
          content={
            <LayoutContent>
              {policy.isError ? (
                <ListError
                  error={policy.error}
                  title={t("flows_retention_load_failed")}
                  onRetry={() => void policy.refetch()}
                  isRetrying={policy.isFetching}
                />
              ) : (
                <LoadingState rows={2} label={t("flows_retention_heading")} />
              )}
            </LayoutContent>
          }
        />
      )}
    </Dialog>
  );
}

function RetentionForm({
  flow,
  settings,
  onClose
}: {
  flow: FlowPublic;
  settings: PolicySettings;
  onClose: () => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const queryClient = useQueryClient();
  const savedDays = settings.local_policy?.days ?? null;
  const [days, setDays] = useState(savedDays);
  const [refused, setRefused] = useState(false);
  // The space's time as the server last gave it, by a read or by a refusal.
  const spaceDays = settings.inherited_policy?.days ?? null;
  // The field's value is over the space's time; a new value clears it.
  const [overCap, setOverCap] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  /** Writes what the server just said; an older read still in flight must not replace it. */
  const writeAnswer = async <T,>(key: QueryKey, update: (current?: T) => T | undefined) => {
    await queryClient.cancelQueries({ queryKey: key, exact: true });
    queryClient.setQueryData<T>(key, update);
  };

  const save = useMutation({
    mutationFn: (sent: number | null) =>
      unwrap(
        browserApi.PUT("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
          params: { path: { flow_id: flow.id } },
          body: { policy: sent === null ? null : { days: sent } }
        })
      ),
    onSuccess: async (saved) => {
      await writeAnswer<PolicySettings>(policyKey(flow.id), () => saved);
      await writeAnswer<FlowPublic>(flowKeys.flow(flow.id), (current) =>
        current ? { ...current, run_history_retention: saved.effective } : current
      );
      toast.success(t("flows_retention_saved"));
      onClose();
    },
    onError: async (error) => {
      const refusedAt = refusedCap(error);
      if (refusedAt === null) {
        toastApiError(error, t);
        return;
      }
      // The refusal names a newer space time than the one read; an empty field inherits it.
      await writeAnswer<PolicySettings>(policyKey(flow.id), (current) =>
        current ? { ...current, inherited_policy: { days: refusedAt } } : current
      );
      // The summary shows the server's projection, which the newer space time changes.
      // Not awaited: the cap error does not wait for the read.
      void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flow.id), exact: true });
      setOverCap(true);
      field.current?.focus();
    }
  });

  // The cap error shows only while it holds: a later read may give the space a longer time.
  const problem =
    refused && days !== null && !retentionDaysValid(days)
      ? t("flows_retention_days_range", { min: MIN_DAYS, max: MAX_DAYS })
      : overCap && spaceDays !== null && days !== null && days > spaceDays
        ? t("flows_retention_cap_space", { days: spaceDays })
        : undefined;
  const applies =
    days !== null
      ? spaceDays !== null && days === savedDays && days > spaceDays
        ? t("flows_retention_longer_saved", { days })
        : undefined
      : spaceDays !== null
        ? t("flows_retention_applies_space", { days: spaceDays })
        : t("flows_retention_applies_none");

  return (
    <Layout
      header={
        <DialogHeader
          title={t("flows_retention_heading")}
          subtitle={t("flows_retention_dialog_subtitle")}
          onOpenChange={(next) => {
            if (!next) onClose();
          }}
        />
      }
      content={
        <LayoutContent>
          <form
            id={formId}
            noValidate
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (save.isPending) return;
              if (days === null || retentionDaysValid(days)) save.mutate(days);
              else setRefused(true);
            }}
          >
            <NumberInput
              ref={field}
              label={t("flows_retention_days_label")}
              description={applies}
              value={days}
              onChange={(next) => {
                setDays(next);
                setOverCap(false);
              }}
              min={MIN_DAYS}
              max={MAX_DAYS}
              hasClear
              // Read-only, not disabled: it keeps focus, and a refusal marks the value sent.
              isReadOnly={save.isPending}
              status={problem ? { type: "error", message: problem } : undefined}
            />
          </form>
        </LayoutContent>
      }
      footer={
        <LayoutFooter>
          <div className="flex flex-wrap justify-end gap-2">
            <Button label={t("cancel")} isDisabled={save.isPending} onClick={onClose} />
            <Button
              type="submit"
              form={formId}
              variant="primary"
              label={t("flows_settings_save")}
              isLoading={save.isPending}
              isInterruptible
            />
          </div>
        </LayoutFooter>
      }
    />
  );
}

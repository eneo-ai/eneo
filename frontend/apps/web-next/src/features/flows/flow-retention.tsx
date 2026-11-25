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
 * flow time longer than the space's is shown too, since the space's shorter time wins,
 * and so is a flow time that waits for the space's: without it nothing is removed. Runs
 * in a personal space are never removed automatically, so it says that instead.
 */
export function FlowRetentionSummary({
  flow,
  personalSpace = false
}: {
  flow: FlowPublic;
  personalSpace?: boolean;
}) {
  const t = useTranslations();
  const retention = flow.run_history_retention;
  if (retention.state === "off") return <>{t("flows_retention_off")}</>;
  const saved = retention.contributors.flow?.days;
  const note = personalSpace
    ? t("flows_retention_personal")
    : retention.contributors.space === null
      ? t("flows_retention_applies_none")
      : saved !== undefined && saved > retention.effective_days
        ? t("flows_retention_longer_saved", { days: saved })
        : null;
  return (
    <>
      {t("flows_retention_days", { days: retention.effective_days })},{" "}
      {t(`flows_retention_source_${retention.source}`)}
      {note ? <span className="text-ax-text-secondary mt-0.5 block text-sm">{note}</span> : null}
    </>
  );
}

/**
 * The flow's own time, or none to use the space's. It has an endpoint of its own and
 * stays open on a published flow: it changes when runs may be purged, not the
 * definition, so it is no part of the settings form. Saving deletes nothing itself, but
 * a shorter time lets the space's automatic removal take older runs at a coming check,
 * so the first press of Save for a shorter time shows a warning instead of saving. In
 * a personal space nothing is removed automatically, so it neither warns nor waits.
 */
export function FlowRetentionDialog({
  flow,
  open,
  onOpenChange,
  personalSpace = false
}: {
  flow: FlowPublic;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Runs in a personal space are not removed automatically; the time serves the purge. */
  personalSpace?: boolean;
}) {
  const t = useTranslations();
  const subtitle = t(
    personalSpace ? "flows_retention_personal" : "flows_retention_dialog_subtitle"
  );
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
        <RetentionForm
          flow={flow}
          settings={policy.data}
          personalSpace={personalSpace}
          subtitle={subtitle}
          onClose={() => onOpenChange(false)}
        />
      ) : (
        <Layout
          header={
            <DialogHeader
              title={t("flows_retention_heading")}
              subtitle={subtitle}
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
  personalSpace,
  subtitle,
  onClose
}: {
  flow: FlowPublic;
  settings: PolicySettings;
  personalSpace: boolean;
  subtitle: string;
  onClose: () => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const queryClient = useQueryClient();
  const savedDays = settings.local_policy?.days ?? null;
  // Until the person edits it, the field shows the Flow's time as last read, so a
  // read that brings another admin's change replaces it. A clear is an edit too.
  const [draft, setDraft] = useState<{ days: number | null } | null>(null);
  const days = draft ? draft.days : savedDays;
  const [refused, setRefused] = useState(false);
  // The space's time as the server last gave it, by a read or by a refusal.
  const spaceDays = settings.inherited_policy?.days ?? null;
  // The field's value is over the space's time; a new value clears it.
  const [overCap, setOverCap] = useState(false);
  // The shorter time the warning has been shown for; Save then sends it.
  const [warnedFor, setWarnedFor] = useState<number | null>(null);
  const field = useRef<HTMLInputElement>(null);

  /** Writes what the server just said; an older read still in flight must not replace it. */
  const writeAnswer = async <T,>(key: QueryKey, update: (current?: T) => T | undefined) => {
    await queryClient.cancelQueries({ queryKey: key, exact: true });
    queryClient.setQueryData<T>(key, update);
  };

  const save = useMutation({
    // `expected` and `expectedSpace` are the time that applied and the space's time when the
    // warning was decided; the server refuses the save (409 `retention_time_changed`) when
    // another administrator has changed either since. The space's time counts on its own:
    // giving the space a time starts the removal without changing the time that applies.
    mutationFn: ({
      sent,
      expected,
      expectedSpace
    }: {
      sent: number | null;
      expected: number | null;
      expectedSpace: number | null;
    }) =>
      unwrap(
        browserApi.PUT("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
          params: { path: { flow_id: flow.id } },
          body: {
            policy: sent === null ? null : { days: sent },
            expected_effective_days: expected,
            expected_inherited_days: expectedSpace
          }
        })
      ),
    onSuccess: async (saved) => {
      await writeAnswer<PolicySettings>(policyKey(flow.id), () => saved);
      await writeAnswer<FlowPublic>(flowKeys.flow(flow.id), (current) =>
        current ? { ...current, run_history_retention: saved.effective } : current
      );
      // The answer is the server's as of the save, and the writes cancelled any read in
      // flight: a read started now sees a later change, such as a shorter space time.
      // Not awaited: the dialog closes without waiting for the reads.
      void queryClient.invalidateQueries({ queryKey: policyKey(flow.id), exact: true });
      void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flow.id), exact: true });
      toast.success(t("flows_retention_saved"));
      onClose();
    },
    onError: async (error) => {
      if (error instanceof EneoApiError && error.reason === "retention_time_changed") {
        // Changed by someone else: nothing was saved. The draft is dropped and the times are
        // read again, so the field shows the time read and a time typed again is warned
        // about against what applies now.
        toastApiError(error, t);
        setWarnedFor(null);
        setDraft(null);
        void queryClient.invalidateQueries({ queryKey: policyKey(flow.id), exact: true });
        void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flow.id), exact: true });
        field.current?.focus();
        return;
      }
      const refusedAt = refusedCap(error);
      if (refusedAt === null) {
        toastApiError(error, t);
        return;
      }
      // The refusal names a newer space time than the one read; an empty field inherits it.
      await writeAnswer<PolicySettings>(policyKey(flow.id), (current) =>
        current ? { ...current, inherited_policy: { days: refusedAt } } : current
      );
      // The refusal is the server's as of the save, and the write cancelled any read in
      // flight: a read started now sees a later change, such as a longer space time, and the
      // summary's projection, which the space time changes. Not awaited: the cap error does
      // not wait for the reads.
      void queryClient.invalidateQueries({ queryKey: policyKey(flow.id), exact: true });
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
    spaceDays === null
      ? personalSpace
        ? undefined
        : t("flows_retention_applies_none")
      : days === null
        ? t("flows_retention_applies_space", { days: spaceDays })
        : days === savedDays && days > spaceDays
          ? t("flows_retention_longer_saved", { days })
          : // The space's time caps the flow's; an error in the field already names the cap.
            problem
            ? undefined
            : t("flows_retention_applies_space_cap", { days: spaceDays });
  // Only a space time removes runs, and never in a personal space, so a shorter time
  // matters only under one in a shared space.
  const applied = (flowDays: number | null) =>
    spaceDays === null || personalSpace ? null : Math.min(flowDays ?? spaceDays, spaceDays);
  const current = applied(savedDays);
  const next = applied(days);
  const shortens = draft !== null && current !== null && next !== null && next < current;
  const warning =
    shortens && warnedFor === days && !problem ? t("flows_retention_shorter_warning") : undefined;

  return (
    <Layout
      header={
        <DialogHeader
          title={t("flows_retention_heading")}
          subtitle={subtitle}
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
              // Nothing edited is nothing to save: resending the time as read could
              // overwrite a newer one.
              if (!draft) onClose();
              else if (days !== null && !retentionDaysValid(days)) setRefused(true);
              else if (shortens && warnedFor !== days) {
                setWarnedFor(days);
                field.current?.focus();
              } else
                save.mutate({
                  sent: days,
                  expected: settings.effective.effective_days ?? null,
                  expectedSpace: spaceDays
                });
            }}
          >
            <NumberInput
              ref={field}
              label={t("flows_retention_days_label")}
              description={applies}
              value={days}
              onChange={(next) => {
                setDraft({ days: next });
                setOverCap(false);
              }}
              min={MIN_DAYS}
              max={MAX_DAYS}
              hasClear
              // Read-only, not disabled: it keeps focus, and a refusal marks the value sent.
              isReadOnly={save.isPending}
              status={
                problem
                  ? { type: "error", message: problem }
                  : warning
                    ? { type: "warning", message: warning }
                    : undefined
              }
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

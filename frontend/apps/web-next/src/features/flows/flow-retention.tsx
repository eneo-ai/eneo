import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { flowKeys, type FlowPublic } from "./flows-api";

type Policy = Schema<"FlowRunRetentionPolicy">;
type Mode = Policy["mode"];

/** The backend's bounds (MIN_RETENTION_DAYS, MAX_RETENTION_DAYS); it checks them again. */
const MIN_DAYS = 1;
const MAX_DAYS = 2555;
const MODES: Record<
  Mode,
  "flows_retention_mode_preserve" | "flows_retention_mode_review_required"
> = {
  preserve: "flows_retention_mode_preserve",
  review_required: "flows_retention_mode_review_required"
};

const policyKey = (flowId: string) => ["flows", "retention", flowId] as const;

/** What applies to the flow's run history, in a line: the days, what follows and where from. */
export function FlowRetentionSummary({ flow }: { flow: FlowPublic }) {
  const t = useTranslations();
  const retention = flow.run_history_retention;
  if (retention.state === "off") return <>{t("flows_retention_off")}</>;
  return (
    <>
      {t("flows_retention_days", { days: retention.effective_days })},{" "}
      {t(`flows_retention_source_${retention.source}`)}
      <span className="text-ax-text-secondary mt-0.5 block text-sm">
        {t(MODES[retention.mode])}
      </span>
    </>
  );
}

/**
 * The flow's own retention, or none to inherit. It has an endpoint of its own and
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
    >
      {open && policy.data ? (
        <RetentionForm
          key={policy.dataUpdatedAt}
          flow={flow}
          settings={policy.data}
          onClose={() => onOpenChange(false)}
        />
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
  settings: Schema<"FlowRunRetentionPolicySettings">;
  onClose: () => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const queryClient = useQueryClient();
  const inherited = settings.inherited_policy;
  const [own, setOwn] = useState(settings.local_policy !== null);
  const [days, setDays] = useState<number | null>(
    settings.local_policy?.days ?? inherited?.days ?? null
  );
  const [mode, setMode] = useState<Mode>(
    settings.local_policy?.mode ?? inherited?.mode ?? "review_required"
  );
  const [refused, setRefused] = useState(false);
  const daysValid = days !== null && Number.isInteger(days) && days >= MIN_DAYS && days <= MAX_DAYS;

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PUT("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
          params: { path: { flow_id: flow.id } },
          body: { policy: own ? { days: days!, mode } : null }
        })
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(policyKey(flow.id), saved);
      queryClient.setQueryData<FlowPublic>(flowKeys.flow(flow.id), (current) =>
        current ? { ...current, run_history_retention: saved.effective } : current
      );
      toast.success(t("flows_retention_saved"));
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

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
              if (!own || daysValid) save.mutate();
              else setRefused(true);
            }}
          >
            <RadioList
              label={t("flows_retention_choice_label")}
              value={own ? "own" : "inherit"}
              onChange={(value) => setOwn(value === "own")}
            >
              <RadioListItem
                value="inherit"
                label={t("flows_retention_inherit")}
                description={
                  inherited
                    ? t("flows_retention_inherit_policy", { days: inherited.days })
                    : t("flows_retention_inherit_none")
                }
              />
              <RadioListItem value="own" label={t("flows_retention_own")} />
            </RadioList>
            {own ? (
              <>
                <NumberInput
                  label={t("flows_retention_days_label")}
                  value={days}
                  onChange={setDays}
                  min={MIN_DAYS}
                  max={MAX_DAYS}
                  isRequired
                  status={
                    daysValid || !refused
                      ? undefined
                      : {
                          type: "error",
                          message: t("flows_retention_days_range", {
                            min: MIN_DAYS,
                            max: MAX_DAYS
                          })
                        }
                  }
                />
                <Selector
                  label={t("flows_retention_mode_label")}
                  value={mode}
                  onChange={(value) => setMode(value as Mode)}
                  options={(Object.keys(MODES) as Mode[]).map((value) => ({
                    value,
                    label: t(MODES[value])
                  }))}
                />
              </>
            ) : null}
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

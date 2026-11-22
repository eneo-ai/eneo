import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { useQueryClient } from "@tanstack/react-query";
import type { Schema } from "@/lib/api/models";
import { isTerminal } from "./run-status";
import { runKeys, type RunSummary } from "./runs-api";

export type Delivery = Schema<"FlowRunWebhookDeliveryStatePublic">;

/**
 * Whether the delivery is still under way: being sent, or a new attempt is
 * planned. The core's `state` says which; the count of attempts does not, as
 * it counts an attempt while it is being sent.
 */
export function deliveryUnderWay(delivery: Pick<Delivery, "state"> | null | undefined): boolean {
  return delivery?.state === "sending" || delivery?.state === "retry_scheduled";
}

/**
 * The delivery of the run's result the page goes by. Once the run has finished, the result moves
 * on without it, and only the result's own status read (`followed`) sees it move: that read counts
 * while the run's own status says the result is on its way. Otherwise the run's own status counts,
 * also when the result's read, kept from earlier, still says it is on its way.
 */
export function currentResultDelivery(
  run: Pick<RunSummary, "status" | "result_delivery"> | null | undefined,
  followed: Pick<RunSummary, "result_delivery"> | null | undefined
): Delivery | null {
  const own = run?.result_delivery ?? null;
  if (!run || !isTerminal(run.status) || !deliveryUnderWay(own)) return own;
  return followed?.result_delivery ?? own;
}

/**
 * How a read of the run's own data behaves when the person comes back to the tab or the network
 * returns: as the app's default, except while the run has finished and its result is on its way.
 * Then only the result's status is read (`runKeys.delivery`); the run's other reads, the audited
 * ones among them, wait until the result has settled. Decided when the person comes back, from
 * what the page last read.
 */
export function useReadsOnReturn(flowId: string, runId: string) {
  const queryClient = useQueryClient();
  const readAgain = () => {
    const run = queryClient.getQueryData<{ status: RunSummary }>(runKeys.progress(flowId, runId));
    const followed = queryClient.getQueryData<RunSummary>(runKeys.delivery(flowId, runId));
    return !(
      run &&
      isTerminal(run.status.status) &&
      deliveryUnderWay(currentResultDelivery(run.status, followed))
    );
  };
  return { refetchOnWindowFocus: readAgain, refetchOnReconnect: readAgain };
}

/**
 * The deliveries as they stand: the detail's list, with the run's latest
 * delivery as its status last said it (`latest`), which is newer than the
 * detail once the run has completed.
 */
export function currentDeliveries(
  deliveries: readonly Delivery[],
  latest: Delivery | null | undefined
): Delivery[] {
  if (!latest) return [...deliveries];
  const listed = deliveries.some((delivery) => delivery.id === latest.id);
  return listed
    ? deliveries.map((delivery) => (delivery.id === latest.id ? latest : delivery))
    : [...deliveries, latest];
}

const TONES: Record<Delivery["state"], StatusTone> = {
  sending: "neutral",
  retry_scheduled: "warning",
  delivered: "success",
  dead_lettered: "error"
};

/** A plain POST's words: the run waits for it, and fails when it cannot be delivered. */
const POST_LABELS: Record<Delivery["state"], string> = {
  sending: "flow_run_extras_webhook_pending",
  retry_scheduled: "flow_run_extras_webhook_retrying",
  delivered: "flow_run_extras_webhook_delivered",
  dead_lettered: "flow_run_extras_webhook_dead_lettered"
};

/** The words for the run's result, sent once the run has completed: never about the run failing. */
const SENT_LABELS: Record<Exclude<Delivery["state"], "retry_scheduled">, string> = {
  sending: "flow_run_extras_send_sending",
  delivered: "flow_run_extras_send_delivered",
  dead_lettered: "flow_run_extras_send_dead_lettered"
};

function DeliveryState({ delivery, afterRun }: { delivery: Delivery; afterRun: boolean }) {
  const t = useTranslations();
  const retryAt = useClientTimeText(delivery.next_delivery_at, "time");
  const label = !afterRun
    ? t(POST_LABELS[delivery.state])
    : delivery.state === "retry_scheduled"
      ? t("flow_run_extras_send_retry_at", { time: retryAt ?? "" })
      : t(SENT_LABELS[delivery.state]);
  return <StatusLabel status={TONES[delivery.state]} label={label} />;
}

/** How many tries so far, and when it landed, was given up or will be tried next. */
function DeliveryDetail({ delivery, afterRun }: { delivery: Delivery; afterRun: boolean }) {
  const t = useTranslations();
  const settled = delivery.delivered_at ?? delivery.dead_lettered_at;
  // The run's result says its next attempt in its state already.
  const retryAt =
    !afterRun && delivery.state === "retry_scheduled" ? delivery.next_delivery_at : null;
  // An attempt being sent is counted already; it is said once it has an outcome.
  const attempts =
    delivery.delivery_attempts > 0 && delivery.state !== "sending"
      ? t("flow_run_extras_webhook_attempts_count", { count: delivery.delivery_attempts })
      : null;
  if (!attempts && !settled && !retryAt) return null;
  return (
    <span className="text-wrap">
      {attempts}
      {attempts && (settled || retryAt) ? " · " : null}
      {settled ? (
        <ClientTime value={settled} format="date_time" />
      ) : retryAt ? (
        <>
          {t("flow_run_extras_webhook_next_at")} <ClientTime value={retryAt} format="date_time" />
        </>
      ) : null}
    </span>
  );
}

/**
 * Where the run's result went: per step that sends it on, whether the
 * receiver got it, is being retried or was given up, after how many tries,
 * and when, in the state the core gives. A step that sends the run's result
 * once the run has completed (`sentAfterRun`) has words of its own: its
 * delivery never makes the run fail.
 */
export function RunWebhookDeliveries({
  deliveries,
  stepName,
  sentAfterRun
}: {
  deliveries: readonly Delivery[];
  /** The step's title in this run, by its order. */
  stepName: (order: number) => string;
  /** Whether the step at `order` sends the run's result once the run has completed. */
  sentAfterRun: (order: number) => boolean;
}) {
  const t = useTranslations();
  // The note on trying again holds only while an attempt is still to come.
  const unsettled = deliveries.filter(deliveryUnderWay);
  return (
    <div className="flex flex-col gap-2">
      <List hasDividers density="compact" edge="flush">
        {[...deliveries]
          .sort((a, b) => a.step_order - b.step_order)
          .map((delivery) => {
            const afterRun = sentAfterRun(delivery.step_order);
            return (
              <ListItem
                key={delivery.id}
                // A long step name wraps; a phone would cut it off.
                label={<span className="text-pretty">{stepName(delivery.step_order)}</span>}
                description={<DeliveryDetail delivery={delivery} afterRun={afterRun} />}
                endContent={<DeliveryState delivery={delivery} afterRun={afterRun} />}
              />
            );
          })}
      </List>
      {unsettled.length > 0 && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 text-pretty">
          {t(
            unsettled.every((delivery) => sentAfterRun(delivery.step_order))
              ? "flow_run_extras_send_retry_note"
              : "flow_run_extras_webhook_retry_note"
          )}
        </Text>
      )}
    </div>
  );
}

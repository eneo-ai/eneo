import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import type { Schema } from "@/lib/api/models";

type Delivery = Schema<"FlowRunWebhookDeliveryPublic">;

/** A pending delivery that has failed once is retrying, not on its way for the first time. */
function deliveryView(delivery: Delivery): { tone: StatusTone; labelKey: string } {
  switch (delivery.delivery_status) {
    case "delivered":
      return { tone: "success", labelKey: "flow_run_extras_webhook_delivered" };
    case "dead_lettered":
      return { tone: "error", labelKey: "flow_run_extras_webhook_dead_lettered" };
    case "pending":
      return delivery.delivery_attempts > 0
        ? { tone: "warning", labelKey: "flow_run_extras_webhook_retrying" }
        : { tone: "neutral", labelKey: "flow_run_extras_webhook_pending" };
  }
}

/** How many tries so far, and when it landed, was given up or will be tried next. */
function DeliveryDetail({ delivery }: { delivery: Delivery }) {
  const t = useTranslations();
  const settled = delivery.delivered_at ?? delivery.dead_lettered_at;
  const retryAt = delivery.delivery_attempts > 0 ? delivery.next_delivery_at : null;
  const attempts =
    delivery.delivery_attempts > 0
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
 * and when. Part of the run detail already read.
 */
export function RunWebhookDeliveries({
  deliveries,
  stepName
}: {
  deliveries: readonly Delivery[];
  /** The step's title in this run, by its order. */
  stepName: (order: number) => string;
}) {
  const t = useTranslations();
  const unsettled = deliveries.some((delivery) => delivery.delivery_status !== "delivered");
  return (
    <div className="flex flex-col gap-2">
      <List hasDividers density="compact" edge="flush">
        {[...deliveries]
          .sort((a, b) => a.step_order - b.step_order)
          .map((delivery) => {
            const view = deliveryView(delivery);
            return (
              <ListItem
                key={delivery.id}
                // A long step name wraps; a phone would cut it off.
                label={<span className="text-pretty">{stepName(delivery.step_order)}</span>}
                description={<DeliveryDetail delivery={delivery} />}
                endContent={<StatusLabel status={view.tone} label={t(view.labelKey)} />}
              />
            );
          })}
      </List>
      {unsettled && (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 text-pretty">
          {t("flow_run_extras_webhook_retry_note")}
        </Text>
      )}
    </div>
  );
}

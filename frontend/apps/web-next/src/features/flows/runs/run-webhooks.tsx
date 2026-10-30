"use client";

import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useTranslations } from "use-intl";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import type { Schema } from "@/lib/api/models";

type Delivery = Schema<"FlowRunWebhookDeliveryPublic">;
type Row = Delivery & Record<string, unknown>;

const DELIVERY_VIEWS: Record<Delivery["delivery_status"], { tone: StatusTone; labelKey: string }> =
  {
    pending: { tone: "neutral", labelKey: "flow_run_extras_webhook_pending" },
    delivered: { tone: "success", labelKey: "flow_run_extras_webhook_delivered" },
    dead_lettered: { tone: "error", labelKey: "flow_run_extras_webhook_dead_lettered" }
  };

/** When a delivery landed or was given up (the status says which), or will be tried next. */
function DeliveryTime({ delivery }: { delivery: Delivery }) {
  const t = useTranslations();
  const settled = delivery.delivered_at ?? delivery.dead_lettered_at;
  if (settled) return <ClientTime value={settled} format="date_time" />;
  if (!delivery.next_delivery_at) return <>–</>;
  return (
    <span>
      {t("flow_run_extras_webhook_next_at")}{" "}
      <ClientTime value={delivery.next_delivery_at} format="date_time" />
    </span>
  );
}

/**
 * The run's outbound webhook deliveries: per step, whether the call landed,
 * is waiting for its next try or was given up, after how many tries, and
 * when. Part of the run detail already read.
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
  const columns: TableColumn<Row>[] = [
    {
      key: "step",
      header: t("flow_run_extras_webhook_step"),
      width: proportional(3),
      renderCell: (delivery) => stepName(delivery.step_order)
    },
    {
      key: "status",
      header: t("flow_run_extras_webhook_status"),
      width: proportional(2),
      renderCell: (delivery) => {
        const view = DELIVERY_VIEWS[delivery.delivery_status];
        return <StatusLabel status={view.tone} label={t(view.labelKey)} />;
      }
    },
    {
      key: "attempts",
      header: t("flow_run_extras_webhook_attempts"),
      width: pixel(96),
      renderCell: (delivery) => delivery.delivery_attempts
    },
    {
      key: "when",
      header: t("flow_run_extras_webhook_when"),
      width: proportional(3),
      renderCell: (delivery) => <DeliveryTime delivery={delivery} />
    }
  ];
  return (
    <Table<Row>
      data={[...deliveries].sort((a, b) => a.step_order - b.step_order) as Row[]}
      columns={columns}
      idKey="id"
      aria-label={t("flow_run_extras_webhook_heading")}
    />
  );
}

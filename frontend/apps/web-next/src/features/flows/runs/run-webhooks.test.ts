import { describe, expect, it } from "vitest";
import { makeRunSummary } from "./run-fixtures";
import { currentResultDelivery, type Delivery } from "./run-webhooks";

type State = Delivery["state"];

function delivery(state: State): Delivery {
  return {
    id: "delivery-1",
    step_id: "step-2",
    step_order: 2,
    attempt_no: 1,
    delivery_status: state === "delivered" ? "delivered" : "pending",
    delivery_attempts: 1,
    next_delivery_at: null,
    delivered_at: null,
    dead_lettered_at: null,
    created_at: "2026-10-21T08:01:07Z",
    updated_at: "2026-10-21T08:01:07Z",
    state
  } as Delivery;
}

// The run's own status, the result's own status read as cached ("none": not read), and the run's
// status: the delivery the page goes by. The result's read counts only while the run is finished
// and its own status says the result is on its way.
const table: [State | null, "none" | State, "running" | "completed", State | null][] = [
  ["sending", "none", "running", "sending"],
  ["sending", "sending", "running", "sending"],
  ["sending", "delivered", "running", "sending"],
  ["retry_scheduled", "none", "running", "retry_scheduled"],
  ["retry_scheduled", "sending", "running", "retry_scheduled"],
  ["retry_scheduled", "delivered", "running", "retry_scheduled"],
  ["delivered", "none", "running", "delivered"],
  ["delivered", "sending", "running", "delivered"],
  ["delivered", "delivered", "running", "delivered"],
  ["dead_lettered", "none", "running", "dead_lettered"],
  ["dead_lettered", "sending", "running", "dead_lettered"],
  ["dead_lettered", "delivered", "running", "dead_lettered"],
  [null, "none", "running", null],
  [null, "sending", "running", null],
  [null, "delivered", "running", null],
  ["sending", "none", "completed", "sending"],
  ["sending", "sending", "completed", "sending"],
  ["sending", "delivered", "completed", "delivered"],
  ["retry_scheduled", "none", "completed", "retry_scheduled"],
  ["retry_scheduled", "sending", "completed", "sending"],
  ["retry_scheduled", "delivered", "completed", "delivered"],
  ["delivered", "none", "completed", "delivered"],
  ["delivered", "sending", "completed", "delivered"],
  ["delivered", "delivered", "completed", "delivered"],
  ["dead_lettered", "none", "completed", "dead_lettered"],
  ["dead_lettered", "sending", "completed", "dead_lettered"],
  ["dead_lettered", "delivered", "completed", "dead_lettered"],
  [null, "none", "completed", null],
  [null, "sending", "completed", null],
  [null, "delivered", "completed", null]
];

describe("the delivery of the run's result the page goes by", () => {
  it.each(table)("own %s, read %s, run %s: %s", (own, read, status, expected) => {
    const run = makeRunSummary({ status, result_delivery: own ? delivery(own) : null });
    const followed =
      read === "none" ? undefined : makeRunSummary({ result_delivery: delivery(read) });
    expect(currentResultDelivery(run, followed)?.state ?? null).toBe(expected);
  });
});

import { describe, expect, it } from "vitest";
import { makeRunSummary } from "./run-fixtures";
import { currentResultDelivery, deliveryUnderWay, type Delivery } from "./run-webhooks";

type State = Delivery["state"];

function delivery(state: State, updatedAt = "2026-10-21T08:01:07Z"): Delivery {
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
    updated_at: updatedAt,
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
  // The same row read twice: the read that came later is the later one. The result's read polls
  // only while the run's own status says the result is on its way, and the run's own read comes
  // later once it says the result has settled.
  it.each(table)("own %s, read %s, run %s: %s", (own, read, status, expected) => {
    const ownLater = !deliveryUnderWay(own ? { state: own } : null);
    const run = {
      summary: makeRunSummary({ status, result_delivery: own ? delivery(own) : null }),
      readAt: ownLater ? 2 : 1
    };
    const followed =
      read === "none"
        ? undefined
        : {
            summary: makeRunSummary({ result_delivery: delivery(read) }),
            readAt: ownLater ? 1 : 2
          };
    expect(currentResultDelivery(run, followed)?.state ?? null).toBe(expected);
  });

  // A finished run: the row's own time decides which read is newer, as an instant; when both reads
  // saw the row at the same time, the one read later. The run's own read, then the result's: each
  // as state, the row's `updated_at` and when it was read.
  const ordered: [[State, string, number], [State, string, number], State][] = [
    // Sent again after it was given up: the run's own read sees it first.
    [
      ["sending", "2026-10-21T08:03:00Z", 1],
      ["dead_lettered", "2026-10-21T08:02:00Z", 2],
      "sending"
    ],
    // The result's read saw the newer row, though the run's own was read after it.
    [["sending", "2026-10-21T08:03:00Z", 2], ["delivered", "2026-10-21T08:04:00Z", 1], "delivered"],
    [
      ["dead_lettered", "2026-10-21T08:02:00Z", 2],
      ["sending", "2026-10-21T08:03:00Z", 1],
      "sending"
    ],
    [["delivered", "2026-10-21T08:04:00Z", 1], ["sending", "2026-10-21T08:03:00Z", 2], "delivered"],
    // Instants, not text: an offset, and a fraction of a second, order as times.
    [
      ["sending", "2026-10-21T08:03:00Z", 1],
      ["dead_lettered", "2026-10-21T10:02:00+02:00", 2],
      "sending"
    ],
    [
      ["sending", "2026-10-21T08:03:00.500+00:00", 1],
      ["dead_lettered", "2026-10-21T08:03:00Z", 2],
      "sending"
    ],
    // Same row time: the later read wins, either way round.
    [
      ["sending", "2026-10-21T08:03:00Z", 2],
      ["retry_scheduled", "2026-10-21T08:03:00Z", 1],
      "sending"
    ],
    [
      ["sending", "2026-10-21T08:03:00Z", 1],
      ["retry_scheduled", "2026-10-21T08:03:00Z", 2],
      "retry_scheduled"
    ]
  ];

  it.each(ordered)(
    "own %j, read %j: %s",
    ([own, ownAt, ownRead], [read, readAt, readRead], expected) => {
      const run = {
        summary: makeRunSummary({ status: "completed", result_delivery: delivery(own, ownAt) }),
        readAt: ownRead
      };
      const followed = {
        summary: makeRunSummary({ result_delivery: delivery(read, readAt) }),
        readAt: readRead
      };
      expect(currentResultDelivery(run, followed)?.state).toBe(expected);
    }
  );
});

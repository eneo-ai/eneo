import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import {
  connectionErrorKeys,
  outcomeMayBeUnknown,
  pendingOutcome,
  previousOutcome,
  type Connection
} from "./object-store-connection";

const connection = (overrides: Partial<Connection> = {}): Connection => ({
  source: "admin",
  configured: true,
  credentials_can_be_managed: true,
  revision: 9,
  endpoint_url: "https://new.example",
  bucket: "new",
  previous_destination: {
    revision: 5,
    endpoint_url: "https://old.example",
    bucket: "old",
    region: "se-1",
    addressing_style: "path",
    updated_at: "2026-09-25T00:00:00Z"
  },
  ...overrides
});

describe("object-store recovery", () => {
  it("never retries a committed switch-back against the archived destination", () => {
    const attempt = {
      kind: "switch-back" as const,
      endpointUrl: "https://old.example",
      bucket: "old",
      revision: 5
    };
    expect(
      previousOutcome(connection({ endpoint_url: attempt.endpointUrl, bucket: "old" }), attempt)
    ).toBe("committed");
    expect(previousOutcome(connection(), attempt)).toBe("not-applied");
    expect(previousOutcome(connection({ previous_destination: null }), attempt)).toBe("diverged");
  });

  it("distinguishes a forgotten archive from an untouched or replaced one", () => {
    const attempt = { kind: "forget" as const, revision: 5 };
    expect(previousOutcome(connection({ previous_destination: null }), attempt)).toBe("committed");
    expect(previousOutcome(connection(), attempt)).toBe("not-applied");
    expect(
      previousOutcome(
        connection({
          previous_destination: { ...connection().previous_destination!, revision: 6 }
        }),
        attempt
      )
    ).toBe("diverged");
  });

  it("distinguishes an abandoned pending claim from a newer attempt", () => {
    expect(pendingOutcome(connection({ pending_destination: null }), 3)).toBe("committed");
    const pending = {
      revision: 3,
      endpoint_url: "https://pending.example",
      bucket: "pending",
      region: "se-1",
      addressing_style: "path" as const,
      updated_at: "2026-09-25T00:00:00Z"
    };
    expect(pendingOutcome(connection({ pending_destination: pending }), 3)).toBe("not-applied");
    expect(
      pendingOutcome(connection({ pending_destination: { ...pending, revision: 4 } }), 3)
    ).toBe("diverged");
  });

  it("requires a read after transport failure or an explicit uncertain response", () => {
    expect(outcomeMayBeUnknown(new TypeError("Failed to fetch"))).toBe(true);
    expect(
      outcomeMayBeUnknown(
        new EneoApiError("unknown", {
          status: 503,
          reason: "object_store_connection_mutation_outcome_unknown"
        })
      )
    ).toBe(true);
    expect(
      outcomeMayBeUnknown(
        new EneoApiError("blocked", {
          status: 409,
          reason: "object_store_destination_switch_blocked"
        })
      )
    ).toBe(false);
    expect(connectionErrorKeys("object_store_moves_not_paused").title).toBe(
      "storage_switch_error_moves_not_paused_title"
    );
  });
});

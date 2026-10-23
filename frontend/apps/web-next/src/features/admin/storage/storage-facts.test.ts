import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { managedContentBytes, moveCounts, reconcileMoves, storageSize } from "./storage-facts";

describe("storage overview facts", () => {
  it("excludes tombstones from managed content but retains other states", () => {
    const inventory: Schema<"ObjectContentInventoryPublic"> = {
      inventory: [
        {
          owner: "file_content",
          target: "postgres_inline",
          state: "available",
          count: 1,
          bytes: 100,
          oldest_created_at: null
        },
        {
          owner: "icon",
          target: "object_store",
          state: "retained",
          count: 1,
          bytes: 200,
          oldest_created_at: null
        },
        {
          owner: "icon",
          target: "object_store",
          state: "tombstoned",
          count: 1,
          bytes: 300,
          oldest_created_at: null
        }
      ],
      postgresql_allocation: null
    };
    expect(managedContentBytes(inventory)).toEqual({
      total: 300,
      postgresql: 100,
      objectStore: 200
    });
  });

  it("counts pending and verified moves as remaining, and failures separately", () => {
    const moves: Schema<"ObjectContentMovesPublic"> = {
      policy_revision: 3,
      paused: false,
      moves: [
        {
          target: "object_store",
          state: "pending",
          failure_code: null,
          count: 2,
          bytes: 100,
          oldest_updated_at: null
        },
        {
          target: "object_store",
          state: "target_verified",
          failure_code: null,
          count: 3,
          bytes: 100,
          oldest_updated_at: null
        },
        {
          target: "object_store",
          state: "failed",
          failure_code: "target_corrupt",
          count: 4,
          bytes: 100,
          oldest_updated_at: null
        }
      ]
    };
    expect(moveCounts(moves)).toEqual({ pending: 5, failed: 4 });
    expect(storageSize(1536, "en", 1)).toEqual({ amount: "1.5", unit: "KB" });
  });

  it("keeps the newer pause revision when an older status response arrives", () => {
    const policy = {
      policy: { revision: 6, moves_paused: true }
    } as Schema<"DeploymentPolicyPublic">;
    const previous = { policy_revision: 6, paused: true, moves: [] };
    const stale = { policy_revision: 5, paused: false, moves: [] };
    expect(reconcileMoves(previous, stale, policy)).toBe(previous);
    expect(reconcileMoves(null, stale, policy)).toEqual({
      ...stale,
      policy_revision: 6,
      paused: true
    });
  });
});

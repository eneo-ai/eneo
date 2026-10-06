import type { Schema } from "@/lib/api/models";
import { UNIT_BYTES } from "./storage-policy";

export type Inventory = Schema<"ObjectContentInventoryPublic">;
export type Moves = Schema<"ObjectContentMovesPublic">;

export function managedContentBytes(inventory: Inventory): {
  total: number;
  postgresql: number;
  objectStore: number;
} {
  const active = inventory.inventory.filter((item) => item.state !== "tombstoned");
  const postgresql = active
    .filter((item) => item.target === "postgres_inline")
    .reduce((total, item) => total + item.bytes, 0);
  const objectStore = active
    .filter((item) => item.target === "object_store")
    .reduce((total, item) => total + item.bytes, 0);
  return { total: postgresql + objectStore, postgresql, objectStore };
}

export function moveCounts(moves: Moves): { pending: number; failed: number } {
  return moves.moves.reduce(
    (counts, item) => {
      if (item.state === "failed") counts.failed += item.count;
      else counts.pending += item.count;
      return counts;
    },
    { pending: 0, failed: 0 }
  );
}

/** A late status request cannot move the visible pause revision backwards. */
export function reconcileMoves(
  previous: Moves | null,
  next: Moves,
  policy: Schema<"DeploymentPolicyPublic">
): Moves {
  if (
    previous &&
    next.policy_revision < previous.policy_revision &&
    previous.policy_revision >= policy.policy.revision
  )
    return previous;
  if (next.policy_revision < policy.policy.revision)
    return { ...next, policy_revision: policy.policy.revision, paused: policy.policy.moves_paused };
  return next;
}

/** Display size by magnitude; policy fields use exact divisors instead. */
export function storageSize(
  value: number,
  locale: string,
  fractionDigits = 0
): { amount: string; unit: keyof typeof UNIT_BYTES } {
  const unit =
    (["GB", "MB", "KB", "B"] as const).find((candidate) => value >= UNIT_BYTES[candidate]) ?? "B";
  return {
    amount: new Intl.NumberFormat(locale, { maximumFractionDigits: fractionDigits }).format(
      value / UNIT_BYTES[unit]
    ),
    unit
  };
}

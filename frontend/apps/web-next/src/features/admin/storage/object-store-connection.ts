import type { Schema } from "@/lib/api/models";
import { EneoApiError } from "@/lib/api/errors";

export type Connection = Schema<"ObjectStoreConnectionPublic">;
export type ConnectionInput = Schema<"ObjectStoreConnectionInput">;
export type PreviousAction =
  | { kind: "switch-back"; endpointUrl: string; bucket: string; revision: number }
  | { kind: "forget"; revision: number };

export function previousOutcome(
  current: Connection,
  attempt: PreviousAction
): "committed" | "not-applied" | "diverged" {
  if (attempt.kind === "switch-back") {
    if (current.endpoint_url === attempt.endpointUrl && current.bucket === attempt.bucket)
      return "committed";
  } else if (current.previous_destination == null) {
    return "committed";
  }
  return current.previous_destination?.revision === attempt.revision ? "not-applied" : "diverged";
}

export function pendingOutcome(
  current: Connection,
  revision: number
): "committed" | "not-applied" | "diverged" {
  if (current.pending_destination == null) return "committed";
  return current.pending_destination.revision === revision ? "not-applied" : "diverged";
}

/** A lost response can follow a committed write. Read state before permitting a retry. */
export function outcomeMayBeUnknown(error: unknown): boolean {
  return (
    !(error instanceof EneoApiError) ||
    error.reason === "object_store_connection_mutation_outcome_unknown"
  );
}

export const CONNECTION_ERROR_KEYS = {
  object_store_probe_authentication_failed: "auth",
  object_store_probe_tls_failed: "tls",
  object_store_plain_http_not_permitted: "http",
  object_store_probe_binding_mismatch: "binding",
  object_store_probe_integrity_failed: "integrity",
  object_store_credential_encryption_unavailable: "encryption",
  object_store_connection_revision_conflict: "conflict",
  object_store_policy_changed_during_switch: "policy_changed",
  object_store_switch_back_diverged: "diverged",
  object_store_destination_switch_blocked: "blocked",
  object_store_new_writes_not_redirected: "new_writes",
  object_store_moves_not_paused: "moves_not_paused",
  object_store_destination_copy_incomplete: "copy_incomplete",
  object_store_previous_destination_present: "previous_present",
  object_store_connection_mutation_outcome_unknown: "not_applied",
  object_store_destination_already_bound: "already_bound"
} as const;

export function connectionErrorKeys(reason: string | null): {
  title: string;
  description: string;
} {
  const suffix =
    reason && reason in CONNECTION_ERROR_KEYS
      ? CONNECTION_ERROR_KEYS[reason as keyof typeof CONNECTION_ERROR_KEYS]
      : null;
  if (suffix === null) {
    const kind = reason === null ? "unknown" : "unavailable";
    return {
      title: `storage_connection_error_${kind}_title`,
      description: `storage_connection_error_${kind}_description`
    };
  }
  const prefix = [
    "policy_changed",
    "diverged",
    "blocked",
    "new_writes",
    "moves_not_paused",
    "copy_incomplete",
    "previous_present",
    "already_bound"
  ].includes(suffix)
    ? `storage_switch_error_${suffix}`
    : suffix === "not_applied"
      ? "storage_switch_outcome_not_applied"
      : `storage_connection_error_${suffix}`;
  return { title: `${prefix}_title`, description: `${prefix}_description` };
}

import * as m from "$lib/paraglide/messages";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Who acted, as recorded with the event. A recorded actor without a name was
 * already deleted when the event happened, so it is named by its kind; only a
 * system actor or a row without an actor reads "System".
 */
export function auditActorLabel(metadata: unknown): string {
  const actor = isRecord(metadata) ? metadata.actor : undefined;
  if (!isRecord(actor)) return m.audit_actor_system();
  if (typeof actor.name === "string" && actor.name) return actor.name;
  if (actor.type === "user") return m.audit_actor_deleted_user();
  if (actor.type === "service_key" || actor.type === "service_principal") {
    return m.audit_actor_deleted_key();
  }
  if (typeof actor.id === "string" && actor.id && actor.type !== "system") return actor.id;
  return m.audit_actor_system();
}

export function auditActorEmail(metadata: unknown): string | undefined {
  const actor = isRecord(metadata) ? metadata.actor : undefined;
  return isRecord(actor) && typeof actor.email === "string" && actor.email
    ? actor.email
    : undefined;
}

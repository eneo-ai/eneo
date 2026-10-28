import type { FederationPatch, FederationView } from "./federation";

/** The editable settings as the form holds them. */
export type FederationDraft = {
  provider: string;
  clientId: string;
  /** One domain per line (commas and spaces also separate). */
  domains: string;
  /** null while the stored secret is kept; the replacement while one is typed. */
  secret: string | null;
};

export type FederationField = "provider" | "client_id" | "client_secret" | "allowed_domains";

/** A translation key and its values, shown at the field. */
export type FieldProblemKey = { key: string; values?: Record<string, string | number> };

export const FEDERATION_FIELDS: readonly FederationField[] = [
  "provider",
  "client_id",
  "client_secret",
  "allowed_domains"
];

// The backend's rule (tenant_federation_service._DOMAIN_PATTERN), so a bad
// domain is explained at the field instead of by a 422.
const DOMAIN = /^[a-z0-9]+([-.][a-z0-9]+)*\.[a-z]{2,}$/;
// TenantAdminFederationPatch.client_secret min_length.
const SECRET_MIN_LENGTH = 8;

export function draftFromView(view: FederationView): FederationDraft {
  return {
    provider: view.provider ?? "",
    clientId: view.client_id ?? "",
    domains: (view.allowed_domains ?? []).join("\n"),
    secret: null
  };
}

export function parseDomains(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((domain) => domain.toLowerCase())
    .filter(Boolean);
}

function sameList(a: readonly string[], b: readonly string[]) {
  return a.length === b.length && a.every((item, index) => item === b[index]);
}

/** The settings the draft changes, in form order. */
export function changedFields(view: FederationView, draft: FederationDraft): FederationField[] {
  const changed: Record<FederationField, boolean> = {
    provider: draft.provider.trim() !== (view.provider ?? ""),
    client_id: draft.clientId.trim() !== (view.client_id ?? ""),
    client_secret: draft.secret !== null,
    allowed_domains: !sameList(parseDomains(draft.domains), view.allowed_domains ?? [])
  };
  return FEDERATION_FIELDS.filter((field) => changed[field]);
}

/** What the backend would refuse, per field. */
export function validate(
  draft: FederationDraft
): Partial<Record<FederationField, FieldProblemKey>> {
  const problems: Partial<Record<FederationField, FieldProblemKey>> = {};
  if (!draft.provider.trim()) problems.provider = { key: "required_field" };
  if (!draft.clientId.trim()) problems.client_id = { key: "required_field" };
  if (draft.secret !== null) {
    const secret = draft.secret.trim();
    if (!secret) problems.client_secret = { key: "required_field" };
    else if (secret.length < SECRET_MIN_LENGTH) {
      problems.client_secret = {
        key: "federation_admin_secret_too_short",
        values: { min: SECRET_MIN_LENGTH }
      };
    }
  }
  const invalid = parseDomains(draft.domains).find((domain) => !DOMAIN.test(domain));
  if (invalid !== undefined) {
    problems.allowed_domains = {
      key: "federation_admin_domain_invalid",
      values: { domain: invalid }
    };
  }
  return problems;
}

/** The PATCH body: only what changed, with the revision the draft was made against. */
export function toPatch(view: FederationView, draft: FederationDraft): FederationPatch {
  const changed = new Set(changedFields(view, draft));
  const body: FederationPatch = { revision: view.revision ?? "" };
  if (changed.has("provider")) body.provider = draft.provider.trim();
  if (changed.has("client_id")) body.client_id = draft.clientId.trim();
  if (draft.secret !== null) body.client_secret = draft.secret.trim();
  if (changed.has("allowed_domains")) body.allowed_domains = parseDomains(draft.domains);
  return body;
}

import type { FederationAdminPatch, FederationAdminView } from "@eneo/eneo-js";

/** The organisation's sign-in settings as its admin sees them: never the secret. */
export type FederationView = FederationAdminView;

/** The settings an admin may change; everything else belongs to the operator. */
export type FederationField = "provider" | "client_id" | "client_secret" | "allowed_domains";

export const FEDERATION_FIELDS: readonly FederationField[] = [
  "provider",
  "client_id",
  "client_secret",
  "allowed_domains"
];

/** A wrong value here locks every SSO user out; the label is only a label. */
export const RISKY: ReadonlySet<FederationField> = new Set([
  "client_id",
  "client_secret",
  "allowed_domains"
]);

/** The editable settings as the form holds them. */
export type FederationDraft = {
  provider: string;
  clientId: string;
  /** One domain per line (commas and spaces also separate). */
  domains: string;
  /** null while the stored secret is kept; the replacement while one is typed. */
  secret: string | null;
};

/** Why a field cannot be saved, shown at the field. */
export type FieldProblem =
  | { code: "required" }
  | { code: "secret_too_short"; min: number }
  | { code: "domain_invalid"; domain: string }
  | { code: "refused" }
  | { code: "secret_masked" };

// The backend's rules (tenant_federation_service): _DOMAIN_PATTERN and the
// secret's minimum length, so a bad value is explained before a 422.
const DOMAIN = /^[a-z0-9]+([-.][a-z0-9]+)*\.[a-z]{2,}$/;
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

function sameDomains(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((domain, index) => domain === b[index].toLowerCase());
}

/** The settings the draft changes, in form order: what the dialog lists and the save sends. */
export function changedFields(view: FederationView, draft: FederationDraft): FederationField[] {
  const changed: Record<FederationField, boolean> = {
    provider: draft.provider.trim() !== (view.provider ?? ""),
    client_id: draft.clientId.trim() !== (view.client_id ?? ""),
    client_secret: draft.secret !== null,
    allowed_domains: !sameDomains(parseDomains(draft.domains), view.allowed_domains ?? [])
  };
  return FEDERATION_FIELDS.filter((field) => changed[field]);
}

export function validate(draft: FederationDraft): Partial<Record<FederationField, FieldProblem>> {
  const problems: Partial<Record<FederationField, FieldProblem>> = {};
  if (!draft.provider.trim()) problems.provider = { code: "required" };
  if (!draft.clientId.trim()) problems.client_id = { code: "required" };
  if (draft.secret !== null) {
    const secret = draft.secret.trim();
    if (!secret) problems.client_secret = { code: "required" };
    else if (secret.length < SECRET_MIN_LENGTH) {
      problems.client_secret = { code: "secret_too_short", min: SECRET_MIN_LENGTH };
    }
  }
  const invalid = parseDomains(draft.domains).find((domain) => !DOMAIN.test(domain));
  if (invalid !== undefined) problems.allowed_domains = { code: "domain_invalid", domain: invalid };
  return problems;
}

/** The save's form: the revision the draft was made against and only what changed. */
export function toFormData(view: FederationView, draft: FederationDraft): FormData {
  const values: Record<FederationField, () => string> = {
    provider: () => draft.provider.trim(),
    client_id: () => draft.clientId.trim(),
    client_secret: () => (draft.secret ?? "").trim(),
    allowed_domains: () => parseDomains(draft.domains).join("\n")
  };
  const form = new FormData();
  form.set("revision", view.revision ?? "");
  for (const field of changedFields(view, draft)) form.set(field, values[field]());
  return form;
}

function text(form: FormData, name: string): string | undefined {
  const value = form.get(name);
  return typeof value === "string" ? value : undefined;
}

/**
 * The PATCH for a posted form: the four settings an admin owns and nothing
 * else, so no operator-owned field can be smuggled in. A missing setting is
 * unchanged; an empty domain list removes the domains. null without a revision.
 */
export function patchFromForm(form: FormData): FederationAdminPatch | null {
  const revision = text(form, "revision");
  if (!revision) return null;
  const patch: FederationAdminPatch = { revision };
  const provider = text(form, "provider");
  const clientId = text(form, "client_id");
  const clientSecret = text(form, "client_secret");
  const domains = text(form, "allowed_domains");
  if (provider !== undefined) patch.provider = provider;
  if (clientId !== undefined) patch.client_id = clientId;
  if (clientSecret !== undefined) patch.client_secret = clientSecret;
  if (domains !== undefined) patch.allowed_domains = parseDomains(domains);
  return patch;
}

import type { Schema } from "@/lib/api/models";
import type { FederationPatch, FederationView } from "./federation";

/** The editable settings as the form holds them. */
export type FederationDraft = {
  provider: string;
  clientId: string;
  /** One domain per line (commas and spaces also separate). */
  domains: string;
  /** null while the stored secret is kept; the replacement while one is typed. */
  secret: string | null;
  /** The claim that says MFA; "" while the organisation has no rule. */
  mfaClaim: MfaClaim | "";
  /** One value per line (commas and spaces also separate). */
  mfaValues: string;
  /** How Eneo asks for MFA; "" when it does not ask. Only with an acr rule. */
  mfaRequest: MfaRequest | "";
};

export type MfaRule = Schema<"MfaRuleSetting">;
export type MfaClaim = MfaRule["claim"];
export type MfaRequest = NonNullable<MfaRule["request"]>;

export type FederationField =
  "provider" | "client_id" | "client_secret" | "allowed_domains" | "mfa";

/** A translation key and its values, shown at the field. */
export type FieldProblemKey = { key: string; values?: Record<string, string | number> };

export const FEDERATION_FIELDS: readonly FederationField[] = [
  "provider",
  "client_id",
  "client_secret",
  "allowed_domains",
  "mfa"
];

/**
 * A wrong value here locks every SSO user out; the name is only a label, and
 * the MFA rule decides what a session may reach, not whether a person signs in.
 */
export const RISKY: ReadonlySet<FederationField> = new Set([
  "client_id",
  "client_secret",
  "allowed_domains"
]);

// The backend's rule (tenant_federation_service._DOMAIN_PATTERN), so a bad
// domain is explained at the field instead of by a 422.
const DOMAIN = /^[a-z0-9]+([-.][a-z0-9]+)*\.[a-z]{2,}$/;
// TenantAdminFederationPatch.client_secret min_length.
const SECRET_MIN_LENGTH = 8;
// MfaRuleSetting.values max_length, and each value's.
export const MFA_VALUES_MAX = 20;
const MFA_VALUE_MAX_LENGTH = 255;

export function draftFromView(view: FederationView): FederationDraft {
  return {
    provider: view.provider ?? "",
    clientId: view.client_id ?? "",
    domains: (view.allowed_domains ?? []).join("\n"),
    secret: null,
    mfaClaim: view.mfa?.claim ?? "",
    mfaValues: (view.mfa?.values ?? []).join("\n"),
    mfaRequest: view.mfa?.request ?? ""
  };
}

/** The values as typed, each once and in order: an acr rule asks for them in it. */
export function parseMfaValues(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).filter(Boolean))];
}

/** The rule the draft states; null for none. Only an acr rule has values to ask by. */
export function draftRule(draft: FederationDraft): MfaRule | null {
  if (draft.mfaClaim === "") return null;
  const rule: MfaRule = { claim: draft.mfaClaim, values: parseMfaValues(draft.mfaValues) };
  if (draft.mfaClaim === "acr" && draft.mfaRequest !== "") rule.request = draft.mfaRequest;
  return rule;
}

function sameRule(a: MfaRule | null | undefined, b: MfaRule | null | undefined) {
  if (!a || !b) return !a && !b;
  return (
    a.claim === b.claim &&
    (a.request ?? null) === (b.request ?? null) &&
    a.values.length === b.values.length &&
    a.values.every((value, index) => value === b.values[index])
  );
}

/**
 * Whether two rules accept the same sign-ins, whatever order the values are
 * in and however Eneo asks (MfaRule.accepts in the backend). A session that
 * met one of them has met the other.
 */
function acceptSame(a: MfaRule | null | undefined, b: MfaRule | null | undefined) {
  if (!a || !b) return !a && !b;
  return (
    a.claim === b.claim &&
    a.values.length === b.values.length &&
    a.values.every((value) => b.values.includes(value))
  );
}

export function parseDomains(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((domain) => domain.toLowerCase())
    .filter(Boolean);
}

/** Stored domains may be upper case; sign-in compares them lower-cased. */
function sameDomains(a: readonly string[], b: readonly string[]) {
  return a.length === b.length && a.every((domain, index) => domain === b[index]?.toLowerCase());
}

/** The settings the draft changes, in form order. */
export function changedFields(view: FederationView, draft: FederationDraft): FederationField[] {
  const changed: Record<FederationField, boolean> = {
    provider: draft.provider.trim() !== (view.provider ?? ""),
    client_id: draft.clientId.trim() !== (view.client_id ?? ""),
    client_secret: draft.secret !== null,
    allowed_domains: !sameDomains(parseDomains(draft.domains), view.allowed_domains ?? []),
    mfa: !sameRule(view.mfa, draftRule(draft))
  };
  return FEDERATION_FIELDS.filter((field) => changed[field]);
}

/** The allowed domains a draft adds and removes, as sign-in compares them. */
export function domainChange(
  view: FederationView,
  draft: FederationDraft
): { added: string[]; removed: string[] } {
  const before = (view.allowed_domains ?? []).map((domain) => domain.toLowerCase());
  const after = parseDomains(draft.domains);
  return {
    added: after.filter((domain) => !before.includes(domain)),
    removed: before.filter((domain) => !after.includes(domain))
  };
}

/** What a save does to the people who sign in, one entry per effect. */
export type Consequence =
  | { code: "client_id" }
  | { code: "secret" }
  /** From no list to a list: everyone outside it is refused. */
  | { code: "domains_restricted"; domains: string[] }
  /** From a list to none: every member signs in, no account is created. */
  | { code: "domains_emptied" }
  | { code: "domains_removed"; domains: string[] }
  | { code: "domains_added"; domains: string[] }
  /** The first rule: sessions already open were judged under none. */
  | { code: "mfa_first" }
  /** The rule, or the client it trusts, changes: every session loses MFA. */
  | { code: "mfa_sessions" };

/**
 * Whether a save changes what the sessions' MFA rests on: an existing rule,
 * or the client ID it trusts (tenant_federation_service.mfa_trust). Such a
 * save needs a session with MFA, and takes MFA from every session.
 */
export function changesMfaTrust(view: FederationView, draft: FederationDraft): boolean {
  if (!view.mfa) return false;
  return (
    !acceptSame(view.mfa, draftRule(draft)) || draft.clientId.trim() !== (view.client_id ?? "")
  );
}

/**
 * The effects the confirmation names. With domains, sign-in admits only the
 * listed ones; without, it checks none and creates no account automatically
 * (user_service.resolve_federated_user). The name is only a label.
 */
export function consequences(view: FederationView, draft: FederationDraft): Consequence[] {
  const changed = changedFields(view, draft);
  const effects: Consequence[] = [];
  if (changed.includes("client_id")) effects.push({ code: "client_id" });
  if (changed.includes("client_secret")) effects.push({ code: "secret" });
  if (changesMfaTrust(view, draft)) effects.push({ code: "mfa_sessions" });
  else if (!view.mfa && draftRule(draft)) effects.push({ code: "mfa_first" });
  if (!changed.includes("allowed_domains")) return effects;

  const { added, removed } = domainChange(view, draft);
  const hadList = (view.allowed_domains ?? []).length > 0;
  const hasList = parseDomains(draft.domains).length > 0;
  if (!hadList && hasList) effects.push({ code: "domains_restricted", domains: added });
  else if (hadList && !hasList) effects.push({ code: "domains_emptied" });
  else {
    if (removed.length) effects.push({ code: "domains_removed", domains: removed });
    if (added.length) effects.push({ code: "domains_added", domains: added });
  }
  return effects;
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
  if (draft.mfaClaim !== "") {
    const values = parseMfaValues(draft.mfaValues);
    if (values.length === 0) problems.mfa = { key: "federation_admin_mfa_values_required" };
    else if (values.length > MFA_VALUES_MAX) {
      problems.mfa = {
        key: "federation_admin_mfa_values_too_many",
        values: { max: MFA_VALUES_MAX }
      };
    } else if (values.some((value) => value.length > MFA_VALUE_MAX_LENGTH)) {
      problems.mfa = { key: "federation_admin_field_refused" };
    }
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
  // null removes the rule; leaving the field out keeps it.
  if (changed.has("mfa")) body.mfa = draftRule(draft);
  return body;
}

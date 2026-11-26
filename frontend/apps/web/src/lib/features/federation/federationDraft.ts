import type { FederationAdminPatch, FederationAdminView } from "@eneo/eneo-js";

/** The organisation's sign-in settings as its admin sees them: never the secret. */
export type FederationView = FederationAdminView;

/** The settings an admin may change; everything else belongs to the operator. */
export type FederationField =
  "provider" | "client_id" | "client_secret" | "allowed_domains" | "mfa";

export const FEDERATION_FIELDS: readonly FederationField[] = [
  "provider",
  "client_id",
  "client_secret",
  "allowed_domains",
  "mfa"
];

/** The organisation's rule for what counts as multi-factor authentication. */
export type MfaRule = NonNullable<FederationAdminView["mfa"]>;
export type MfaClaim = MfaRule["claim"];
export type MfaRequest = NonNullable<MfaRule["request"]>;

/**
 * A wrong value here locks every SSO user out; the label is only a label, and
 * the MFA rule decides what a session may reach, not whether a person signs in.
 */
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
  /** The claim that says MFA; "" while the organisation has no rule. */
  mfaClaim: MfaClaim | "";
  /** One value per line (commas and spaces also separate). */
  mfaValues: string;
  /** How Eneo asks for MFA; "" when it does not ask. Only with an acr rule. */
  mfaRequest: MfaRequest | "";
};

/** Why a field cannot be saved, shown at the field. */
export type FieldProblem =
  | { code: "required" }
  | { code: "secret_required" }
  | { code: "secret_too_short"; min: number }
  | { code: "domain_invalid"; domain: string }
  | { code: "mfa_values_required" }
  | { code: "mfa_values_too_many"; max: number }
  | { code: "refused" }
  | { code: "secret_masked" };

// The backend's rules (tenant_federation_service): _DOMAIN_PATTERN and the
// secret's minimum length, so a bad value is explained before a 422.
const DOMAIN = /^[a-z0-9]+([-.][a-z0-9]+)*\.[a-z]{2,}$/;
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

function sameRule(a: MfaRule | null | undefined, b: MfaRule | null | undefined): boolean {
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
function acceptSame(a: MfaRule | null | undefined, b: MfaRule | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  return (
    a.claim === b.claim &&
    a.values.length === b.values.length &&
    a.values.every((value) => b.values.includes(value))
  );
}

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
    allowed_domains: !sameDomains(parseDomains(draft.domains), view.allowed_domains ?? []),
    mfa: !sameRule(view.mfa, draftRule(draft))
  };
  return FEDERATION_FIELDS.filter((field) => changed[field]);
}

export function validate(draft: FederationDraft): Partial<Record<FederationField, FieldProblem>> {
  const problems: Partial<Record<FederationField, FieldProblem>> = {};
  if (!draft.provider.trim()) problems.provider = { code: "required" };
  if (!draft.clientId.trim()) problems.client_id = { code: "required" };
  if (draft.secret !== null) {
    const secret = draft.secret.trim();
    if (!secret) problems.client_secret = { code: "secret_required" };
    else if (secret.length < SECRET_MIN_LENGTH) {
      problems.client_secret = { code: "secret_too_short", min: SECRET_MIN_LENGTH };
    }
  }
  const invalid = parseDomains(draft.domains).find((domain) => !DOMAIN.test(domain));
  if (invalid !== undefined) problems.allowed_domains = { code: "domain_invalid", domain: invalid };
  if (draft.mfaClaim !== "") {
    const values = parseMfaValues(draft.mfaValues);
    if (values.length === 0) problems.mfa = { code: "mfa_values_required" };
    else if (values.length > MFA_VALUES_MAX) {
      problems.mfa = { code: "mfa_values_too_many", max: MFA_VALUES_MAX };
    } else if (values.some((value) => value.length > MFA_VALUE_MAX_LENGTH)) {
      problems.mfa = { code: "refused" };
    }
  }
  return problems;
}

/** The allowed domains a draft adds and removes, as the backend compares them. */
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

/** The save's form: the revision the draft was made against and only what changed. */
export function toFormData(view: FederationView, draft: FederationDraft): FormData {
  const values: Record<FederationField, () => string> = {
    provider: () => draft.provider.trim(),
    client_id: () => draft.clientId.trim(),
    client_secret: () => (draft.secret ?? "").trim(),
    allowed_domains: () => parseDomains(draft.domains).join("\n"),
    // JSON: the rule or null, which removes it.
    mfa: () => JSON.stringify(draftRule(draft))
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
 * The rule a posted form states: the three fields of a rule and nothing else.
 * null removes the rule; undefined when the form's value is not a rule.
 */
function ruleFromForm(value: string): MfaRule | null | undefined {
  let posted: unknown;
  try {
    posted = JSON.parse(value);
  } catch {
    return undefined;
  }
  if (posted === null) return null;
  if (typeof posted !== "object" || Array.isArray(posted)) return undefined;
  const { claim, values, request } = posted as Record<string, unknown>;
  if (claim !== "acr" && claim !== "amr") return undefined;
  if (!Array.isArray(values) || !values.every((item) => typeof item === "string")) {
    return undefined;
  }
  const rule: MfaRule = { claim, values: values as string[] };
  if (request === "acr_values" || request === "claims") rule.request = request;
  return rule;
}

/**
 * The PATCH for a posted form: the five settings an admin owns and nothing
 * else, so no operator-owned field can be smuggled in. A missing setting is
 * unchanged; an empty domain list removes the domains. null without a revision,
 * or when the posted rule is not one.
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
  const mfa = text(form, "mfa");
  if (mfa !== undefined) {
    const rule = ruleFromForm(mfa);
    if (rule === undefined) return null;
    patch.mfa = rule;
  }
  return patch;
}

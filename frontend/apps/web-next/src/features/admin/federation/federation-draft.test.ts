import { describe, expect, it } from "vitest";
import type { FederationView } from "./federation";
import {
  changedFields,
  changesMfaTrust,
  consequences,
  domainChange,
  draftFromView,
  draftRule,
  MFA_VALUES_MAX,
  parseDomains,
  toPatch,
  validate,
  type FederationDraft
} from "./federation-draft";

const view: FederationView = {
  configured: true,
  provider: "Entra ID",
  discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
  issuer: "https://idp.example",
  client_id: "eneo-client",
  client_secret_set: true,
  client_secret_updated_at: "2026-10-01T08:00:00Z",
  encryption_status: "encrypted",
  allowed_domains: ["sundsvall.se", "example.se"],
  redirect_uris: ["https://eneo.example/login/callback"],
  redirect_uris_problem: null,
  scopes: ["openid", "email", "profile"],
  token_endpoint_auth_method: "client_secret_post",
  revision: "rev-1",
  configured_at: "2026-10-01T08:00:00Z"
};

const edit = (changes: Partial<FederationDraft>): FederationDraft => ({
  ...draftFromView(view),
  ...changes
});

describe("draftFromView", () => {
  it("starts from the saved values and keeps the stored secret", () => {
    expect(draftFromView(view)).toEqual({
      provider: "Entra ID",
      clientId: "eneo-client",
      domains: "sundsvall.se\nexample.se",
      secret: null,
      mfaClaim: "",
      mfaValues: "",
      mfaRequest: ""
    });
  });
});

describe("parseDomains", () => {
  it("takes one domain per line or comma, lower-cased, without blanks", () => {
    expect(parseDomains(" Sundsvall.SE,example.se\n\n  b.se ")).toEqual([
      "sundsvall.se",
      "example.se",
      "b.se"
    ]);
  });
});

describe("changedFields", () => {
  it("is empty for an untouched draft", () => {
    expect(changedFields(view, draftFromView(view))).toEqual([]);
  });

  it("ignores the case of stored domains", () => {
    const stored = { ...view, allowed_domains: ["Example.SE"] };
    expect(changedFields(stored, draftFromView(stored))).toEqual([]);
  });

  it("ignores surrounding space and how the domains are separated", () => {
    expect(
      changedFields(view, edit({ clientId: " eneo-client ", domains: "Sundsvall.se, example.se" }))
    ).toEqual([]);
  });

  it("names each changed setting, the secret only while it is being replaced", () => {
    expect(
      changedFields(
        view,
        edit({ provider: "Entra", clientId: "next", domains: "sundsvall.se", secret: "" })
      )
    ).toEqual(["provider", "client_id", "client_secret", "allowed_domains"]);
  });
});

describe("validate", () => {
  it("passes the saved settings", () => {
    expect(validate(draftFromView(view))).toEqual({});
  });

  it("requires a client ID and a label", () => {
    expect(validate(edit({ clientId: "  ", provider: "" }))).toEqual({
      provider: { key: "required_field" },
      client_id: { key: "required_field" }
    });
  });

  it("names the first domain the backend would refuse", () => {
    expect(validate(edit({ domains: "sundsvall.se\nnot a domain\nalso bad" }))).toEqual({
      allowed_domains: { key: "federation_admin_domain_invalid", values: { domain: "not" } }
    });
    expect(validate(edit({ domains: "sundsvall.se, -bad.se" }))).toEqual({
      allowed_domains: { key: "federation_admin_domain_invalid", values: { domain: "-bad.se" } }
    });
  });

  it("requires a replacement secret of at least eight characters", () => {
    expect(validate(edit({ secret: "" }))).toEqual({ client_secret: { key: "required_field" } });
    expect(validate(edit({ secret: "short" }))).toEqual({
      client_secret: { key: "federation_admin_secret_too_short", values: { min: 8 } }
    });
    expect(validate(edit({ secret: "long-enough" }))).toEqual({});
  });
});

describe("toPatch", () => {
  it("sends only what changed, with the revision it was made against", () => {
    expect(toPatch(view, edit({ clientId: " next-client " }))).toEqual({
      revision: "rev-1",
      client_id: "next-client"
    });
  });

  it("sends the secret only while it is being replaced", () => {
    expect(toPatch(view, edit({ secret: "  a-new-secret  " }))).toEqual({
      revision: "rev-1",
      client_secret: "a-new-secret"
    });
    expect(toPatch(view, edit({ provider: "Entra" }))).not.toHaveProperty("client_secret");
  });

  it("sends the domains as a list", () => {
    expect(toPatch(view, edit({ domains: "b.se\nSundsvall.se" }))).toEqual({
      revision: "rev-1",
      allowed_domains: ["b.se", "sundsvall.se"]
    });
  });
});

describe("what a save does to sign-in", () => {
  const listed = { ...view, allowed_domains: ["example.org", "example.com"] };
  const draft = (changes: Partial<FederationDraft>): FederationDraft => ({
    ...draftFromView(listed),
    ...changes
  });

  it("a new name changes nothing for the people who sign in", () => {
    expect(consequences(listed, draft({ provider: "Okta" }))).toEqual([]);
  });

  it("a new client ID and a new secret each have their own consequence", () => {
    expect(consequences(listed, draft({ clientId: "next", secret: "s3cret-value" }))).toEqual([
      { code: "client_id" },
      { code: "secret" }
    ]);
  });

  it("names the domains a save removes and adds, ignoring case", () => {
    const next = draft({ domains: "EXAMPLE.com\nfoo.se" });
    expect(domainChange(listed, next)).toEqual({ added: ["foo.se"], removed: ["example.org"] });
    expect(consequences(listed, next)).toEqual([
      { code: "domains_removed", domains: ["example.org"] },
      { code: "domains_added", domains: ["foo.se"] }
    ]);
  });

  it("an emptied list lets every member in and stops automatic accounts", () => {
    expect(consequences(listed, draft({ domains: "" }))).toEqual([{ code: "domains_emptied" }]);
  });

  it("a first list shuts out everyone else", () => {
    const open = { ...listed, allowed_domains: [] };
    expect(consequences(open, draft({ domains: "foo.se" }))).toEqual([
      { code: "domains_restricted", domains: ["foo.se"] }
    ]);
  });

  it("a new order of the same domains admits and refuses the same people", () => {
    const next = draft({ domains: "example.com\nexample.org" });
    expect(changedFields(listed, next)).toEqual(["allowed_domains"]);
    expect(domainChange(listed, next)).toEqual({ added: [], removed: [] });
    expect(consequences(listed, next)).toEqual([]);
  });
});

describe("the MFA rule", () => {
  const ruled: FederationView = {
    ...view,
    mfa: { claim: "acr", values: ["level-3", "level-2"], request: "acr_values" }
  };
  const draft = (changes: Partial<FederationDraft>): FederationDraft => ({
    ...draftFromView(ruled),
    ...changes
  });

  it("starts from the stored rule and sends nothing while it is untouched", () => {
    expect(draftFromView(ruled)).toMatchObject({
      mfaClaim: "acr",
      mfaValues: "level-3\nlevel-2",
      mfaRequest: "acr_values"
    });
    expect(changedFields(ruled, draftFromView(ruled))).toEqual([]);
    expect(toPatch(ruled, draftFromView(ruled))).toEqual({ revision: "rev-1" });
  });

  it("reads the values as typed, each once and in order", () => {
    expect(draftRule(draft({ mfaValues: " level-3, level-2\n\nlevel-3 " }))).toEqual({
      claim: "acr",
      values: ["level-3", "level-2"],
      request: "acr_values"
    });
  });

  it("sends the first rule, and null to remove one", () => {
    const first = edit({ mfaClaim: "amr", mfaValues: "mfa" });
    expect(changedFields(view, first)).toEqual(["mfa"]);
    expect(toPatch(view, first)).toEqual({
      revision: "rev-1",
      mfa: { claim: "amr", values: ["mfa"] }
    });
    expect(toPatch(ruled, draft({ mfaClaim: "" }))).toEqual({ revision: "rev-1", mfa: null });
  });

  it("asks only by an acr rule", () => {
    expect(draftRule(draft({ mfaClaim: "amr" }))).toEqual({
      claim: "amr",
      values: ["level-3", "level-2"]
    });
  });

  it("needs at least one value, and no more than the backend takes", () => {
    expect(validate(draft({ mfaValues: " \n" })).mfa).toEqual({
      key: "federation_admin_mfa_values_required"
    });
    const many = Array.from({ length: MFA_VALUES_MAX + 1 }, (_, index) => `v${index}`).join("\n");
    expect(validate(draft({ mfaValues: many })).mfa).toEqual({
      key: "federation_admin_mfa_values_too_many",
      values: { max: MFA_VALUES_MAX }
    });
    expect(validate(draft({ mfaClaim: "", mfaValues: "" })).mfa).toBeUndefined();
  });

  it("a first rule tells that open sessions have no MFA", () => {
    const first = edit({ mfaClaim: "acr", mfaValues: "level-2" });
    expect(changesMfaTrust(view, first)).toBe(false);
    expect(consequences(view, first)).toEqual([{ code: "mfa_first" }]);
  });

  it("a change of what the rule accepts, or of the client ID, takes MFA from every session", () => {
    for (const changes of [
      { mfaValues: "level-2" },
      { mfaClaim: "amr" as const },
      { mfaClaim: "" as const }
    ]) {
      expect(changesMfaTrust(ruled, draft(changes))).toBe(true);
      expect(consequences(ruled, draft(changes))).toEqual([{ code: "mfa_sessions" }]);
    }
    expect(consequences(ruled, draft({ clientId: "another-client" }))).toEqual([
      { code: "client_id" },
      { code: "mfa_sessions" }
    ]);
    // Without a rule no session has MFA to lose.
    expect(consequences(view, edit({ clientId: "another-client" }))).toEqual([
      { code: "client_id" }
    ]);
  });

  it("the order of the values and how Eneo asks leave the sessions as they are", () => {
    for (const changes of [
      { mfaValues: "level-2\nlevel-3" },
      { mfaRequest: "claims" as const },
      { mfaRequest: "" as const }
    ]) {
      expect(changedFields(ruled, draft(changes))).toEqual(["mfa"]);
      expect(changesMfaTrust(ruled, draft(changes))).toBe(false);
      expect(consequences(ruled, draft(changes))).toEqual([]);
    }
  });
});

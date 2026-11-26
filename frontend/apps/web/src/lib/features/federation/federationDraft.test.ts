import { describe, expect, test } from "vitest";
import {
  changedFields,
  changesMfaTrust,
  consequences,
  domainChange,
  draftFromView,
  draftRule,
  MFA_VALUES_MAX,
  parseDomains,
  patchFromForm,
  toFormData,
  validate,
  type FederationDraft,
  type FederationView
} from "./federationDraft";

const view: FederationView = {
  configured: true,
  provider: "Entra ID",
  client_id: "client-a",
  client_secret_set: true,
  allowed_domains: ["example.com", "Example.org"],
  revision: "rev-1"
} as FederationView;

describe("the sign-in settings draft", () => {
  test("starts from the stored values and keeps the secret", () => {
    expect(draftFromView(view)).toEqual({
      provider: "Entra ID",
      clientId: "client-a",
      domains: "example.com\nExample.org",
      secret: null,
      mfaClaim: "",
      mfaValues: "",
      mfaRequest: ""
    });
  });

  test("reads one domain per line, also split by commas and spaces, in lower case", () => {
    expect(parseDomains(" Example.com,foo.se\n\n bar.org  baz.se ")).toEqual([
      "example.com",
      "foo.se",
      "bar.org",
      "baz.se"
    ]);
  });

  test("an untouched draft changes nothing, even with stored upper case domains", () => {
    expect(changedFields(view, draftFromView(view))).toEqual([]);
  });

  test("lists what changed in form order; an emptied domain list is a change", () => {
    const draft = { ...draftFromView(view), domains: "", secret: "new-secret", clientId: "b" };
    expect(changedFields(view, draft)).toEqual(["client_id", "client_secret", "allowed_domains"]);
  });

  test("explains at the field what the backend would refuse", () => {
    expect(
      validate({
        ...draftFromView(view),
        provider: " ",
        clientId: "",
        domains: "example.com\nnot a domain",
        secret: "short"
      })
    ).toEqual({
      provider: { code: "required" },
      client_id: { code: "required" },
      client_secret: { code: "secret_too_short", min: 8 },
      allowed_domains: { code: "domain_invalid", domain: "not" }
    });
    expect(validate({ ...draftFromView(view), secret: "" })).toEqual({
      client_secret: { code: "secret_required" }
    });
    expect(validate(draftFromView(view))).toEqual({});
  });

  test("posts the revision and only what changed, never a kept secret", () => {
    const kept = toFormData(view, { ...draftFromView(view), provider: " Okta " });
    expect([...kept.entries()]).toEqual([
      ["revision", "rev-1"],
      ["provider", "Okta"]
    ]);

    const replaced = toFormData(view, {
      ...draftFromView(view),
      domains: "",
      secret: " s3cret-value "
    });
    expect([...replaced.entries()]).toEqual([
      ["revision", "rev-1"],
      ["client_secret", "s3cret-value"],
      ["allowed_domains", ""]
    ]);
  });
});

describe("what a save does to who can sign in", () => {
  const draft = (changes: Partial<ReturnType<typeof draftFromView>>) => ({
    ...draftFromView(view),
    ...changes
  });

  test("a new name changes nothing for anyone signing in", () => {
    expect(consequences(view, draft({ provider: "Okta" }))).toEqual([]);
  });

  test("a new client ID and a new secret each have their own consequence", () => {
    expect(consequences(view, draft({ clientId: "client-b", secret: "s3cret-value" }))).toEqual([
      { code: "client_id" },
      { code: "secret" }
    ]);
  });

  test("names the domains a save removes and adds, ignoring case", () => {
    const next = draft({ domains: "EXAMPLE.com\nfoo.se" });
    expect(domainChange(view, next)).toEqual({ added: ["foo.se"], removed: ["example.org"] });
    expect(consequences(view, next)).toEqual([
      { code: "domains_removed", domains: ["example.org"] },
      { code: "domains_added", domains: ["foo.se"] }
    ]);
  });

  test("an emptied list lets every member in and stops automatic accounts", () => {
    expect(consequences(view, draft({ domains: "" }))).toEqual([{ code: "domains_emptied" }]);
  });

  test("a first list shuts out everyone else", () => {
    const open = { ...view, allowed_domains: [] } as FederationView;
    expect(consequences(open, draft({ domains: "foo.se" }))).toEqual([
      { code: "domains_restricted", domains: ["foo.se"] }
    ]);
  });

  test("a new order of the same domains admits and refuses the same people", () => {
    const next = draft({ domains: "example.org\nexample.com" });
    expect(changedFields(view, next)).toEqual(["allowed_domains"]);
    expect(domainChange(view, next)).toEqual({ added: [], removed: [] });
    expect(consequences(view, next)).toEqual([]);
  });
});

describe("the posted form", () => {
  function form(entries: [string, string][]) {
    const data = new FormData();
    for (const [name, value] of entries) data.append(name, value);
    return data;
  }

  test("becomes a patch of the four editable settings and nothing else", () => {
    expect(
      patchFromForm(
        form([
          ["revision", "rev-1"],
          ["provider", "Okta"],
          ["client_id", "client-b"],
          ["client_secret", "s3cret-value"],
          ["allowed_domains", "Example.com\nfoo.se"],
          ["discovery_endpoint", "https://evil.example/.well-known/openid-configuration"],
          ["issuer", "https://evil.example"],
          ["revision_extra", "x"]
        ])
      )
    ).toEqual({
      revision: "rev-1",
      provider: "Okta",
      client_id: "client-b",
      client_secret: "s3cret-value",
      allowed_domains: ["example.com", "foo.se"]
    });
  });

  test("keeps an emptied domain list and leaves missing settings out", () => {
    expect(
      patchFromForm(
        form([
          ["revision", "rev-1"],
          ["allowed_domains", ""]
        ])
      )
    ).toEqual({ revision: "rev-1", allowed_domains: [] });
  });

  test("without a revision there is nothing to save", () => {
    expect(patchFromForm(form([["provider", "Okta"]]))).toBeNull();
  });
});

describe("the MFA rule", () => {
  const ruled = {
    ...view,
    mfa: { claim: "acr", values: ["level-3", "level-2"], request: "acr_values" }
  } as FederationView;
  const draft = (changes: Partial<FederationDraft>): FederationDraft => ({
    ...draftFromView(ruled),
    ...changes
  });
  const posted = (state: FederationView, next: FederationDraft) =>
    patchFromForm(toFormData(state, next));

  test("starts from the stored rule and posts nothing while it is untouched", () => {
    expect(draftFromView(ruled)).toMatchObject({
      mfaClaim: "acr",
      mfaValues: "level-3\nlevel-2",
      mfaRequest: "acr_values"
    });
    expect(changedFields(ruled, draftFromView(ruled))).toEqual([]);
    expect(posted(ruled, draftFromView(ruled))).toEqual({ revision: "rev-1" });
  });

  test("reads the values as typed, each once and in order", () => {
    expect(draftRule(draft({ mfaValues: " level-3, level-2\n\nlevel-3 " }))).toEqual({
      claim: "acr",
      values: ["level-3", "level-2"],
      request: "acr_values"
    });
  });

  test("the form carries the first rule to the patch, and null to remove one", () => {
    const first = { ...draftFromView(view), mfaClaim: "amr" as const, mfaValues: "mfa" };
    expect(changedFields(view, first)).toEqual(["mfa"]);
    expect(posted(view, first)).toEqual({
      revision: "rev-1",
      mfa: { claim: "amr", values: ["mfa"] }
    });
    expect(posted(ruled, draft({ mfaClaim: "" }))).toEqual({ revision: "rev-1", mfa: null });
  });

  test("a posted rule keeps its three fields and nothing else; what is not a rule is no patch", () => {
    const form = (mfa: string) => {
      const data = new FormData();
      data.set("revision", "rev-1");
      data.set("mfa", mfa);
      return data;
    };
    expect(
      patchFromForm(
        form(JSON.stringify({ claim: "acr", values: ["level-2"], request: "claims", extra: 1 }))
      )
    ).toEqual({ revision: "rev-1", mfa: { claim: "acr", values: ["level-2"], request: "claims" } });
    for (const bad of [
      "",
      "not json",
      "[]",
      '{"claim":"auth_time","values":["1"]}',
      '{"claim":"acr","values":[2]}'
    ]) {
      expect(patchFromForm(form(bad))).toBeNull();
    }
  });

  test("asks only by an acr rule", () => {
    expect(draftRule(draft({ mfaClaim: "amr" }))).toEqual({
      claim: "amr",
      values: ["level-3", "level-2"]
    });
  });

  test("needs at least one value, and no more than the backend takes", () => {
    expect(validate(draft({ mfaValues: " \n" })).mfa).toEqual({ code: "mfa_values_required" });
    const many = Array.from({ length: MFA_VALUES_MAX + 1 }, (_, index) => `v${index}`).join("\n");
    expect(validate(draft({ mfaValues: many })).mfa).toEqual({
      code: "mfa_values_too_many",
      max: MFA_VALUES_MAX
    });
    expect(validate(draft({ mfaClaim: "", mfaValues: "" })).mfa).toBeUndefined();
  });

  test("a first rule tells that open sessions have no MFA", () => {
    const first = { ...draftFromView(view), mfaClaim: "acr" as const, mfaValues: "level-2" };
    expect(changesMfaTrust(view, first)).toBe(false);
    expect(consequences(view, first)).toEqual([{ code: "mfa_first" }]);
  });

  test("a change of what the rule accepts, or of the client ID, takes MFA from every session", () => {
    for (const changes of [
      { mfaValues: "level-2" },
      { mfaClaim: "amr" as const },
      { mfaClaim: "" as const }
    ]) {
      expect(changesMfaTrust(ruled, draft(changes))).toBe(true);
      expect(consequences(ruled, draft(changes))).toEqual([{ code: "mfa_sessions" }]);
    }
    expect(consequences(ruled, draft({ clientId: "client-b" }))).toEqual([
      { code: "client_id" },
      { code: "mfa_sessions" }
    ]);
    // Without a rule no session has MFA to lose.
    expect(consequences(view, { ...draftFromView(view), clientId: "client-b" })).toEqual([
      { code: "client_id" }
    ]);
  });

  test("the order of the values and how Eneo asks leave the sessions as they are", () => {
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

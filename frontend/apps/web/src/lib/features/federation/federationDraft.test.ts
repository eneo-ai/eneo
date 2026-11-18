import { describe, expect, test } from "vitest";
import {
  changedFields,
  consequences,
  domainChange,
  draftFromView,
  parseDomains,
  patchFromForm,
  toFormData,
  validate,
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
      secret: null
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

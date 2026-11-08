import { describe, expect, it } from "vitest";
import type { FederationView } from "./federation";
import {
  changedFields,
  draftFromView,
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
      secret: null
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

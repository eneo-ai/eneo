import { describe, expect, it } from "vitest";
import type { ApiKey, ApiKeyCreationConstraints } from "./api-keys";
import {
  administrationLevel,
  canWrite,
  createRequest,
  draftFromApiKey,
  draftProblems,
  heldAdministration,
  ipProblem,
  isAdministrationLevelAllowed,
  newApiKeyDraft,
  offersAdministration,
  originProblem,
  resourceLevel,
  updateRequest,
  visibleResources,
  withKeyType,
  withScopeType
} from "./api-key-draft";

const t = (key: string, values?: Record<string, string | number>) =>
  values ? `${key} ${JSON.stringify(values)}` : key;

const constraints: ApiKeyCreationConstraints = {
  require_expiration: false,
  max_expiration_days: null,
  max_rate_limit: 1000,
  notification_policy: {
    enabled: true,
    default_days_before_expiry: [30, 14, 7, 3, 1],
    max_days_before_expiry: 365,
    allow_auto_follow_published_assistants: false,
    allow_auto_follow_published_apps: false
  }
};

const key = {
  id: "key-1",
  key_prefix: "pk_ab",
  key_suffix: "wxyz",
  name: "Webbwidget",
  description: null,
  key_type: "pk_",
  permission: "read",
  scope_type: "assistant",
  scope_id: "assistant-1",
  allowed_origins: ["https://sundsvall.se"],
  resource_permissions: {
    assistants: "read",
    apps: "none",
    spaces: "none",
    knowledge: "none",
    conversations: "read",
    files: "none",
    jobs: "none",
    prompts: "none"
  },
  rate_limit: 100,
  state: "active"
} as ApiKey;

describe("createRequest", () => {
  it("sends a public key's origins and its read-only access", () => {
    const draft = {
      ...withKeyType(newApiKeyDraft(), "pk_"),
      name: " Widget ",
      allowedOrigins: ["https://sundsvall.se"],
      allowedIps: ["10.0.0.0/8"]
    };
    expect(createRequest(draft)).toMatchObject({
      name: "Widget",
      description: null,
      key_type: "pk_",
      permission: "read",
      scope_type: "tenant",
      scope_id: null,
      allowed_origins: ["https://sundsvall.se"],
      allowed_ips: null,
      resource_permissions: { assistants: "read", apps: "read", jobs: "none", prompts: "none" }
    });
  });

  it("sends a secret key's IPs, scope, rate limit and its highest level as the permission", () => {
    const base = withScopeType(newApiKeyDraft(), "space");
    const draft = {
      ...base,
      name: "Integration",
      scopeId: "space-1",
      allowedIps: ["10.0.0.0/8"],
      rateLimit: "500",
      expiresAt: "2026-12-01T22:59:59.000Z",
      resourcePermissions: { ...base.resourcePermissions, knowledge: "write" as const }
    };
    expect(createRequest(draft)).toMatchObject({
      key_type: "sk_",
      permission: "write",
      scope_type: "space",
      scope_id: "space-1",
      allowed_origins: null,
      allowed_ips: ["10.0.0.0/8"],
      rate_limit: 500,
      expires_at: "2026-12-01T22:59:59.000Z"
    });
  });

  it("prefers a typed resource id and sends what the scope does not reach as none", () => {
    const draft = {
      ...withScopeType(newApiKeyDraft(), "app"),
      name: "App runner",
      scopeId: "app-picked",
      manualScopeId: " app-typed "
    };
    const request = createRequest(draft);
    expect(request.scope_id).toBe("app-typed");
    expect(request.resource_permissions).toEqual({
      assistants: "none",
      apps: "read",
      spaces: "none",
      knowledge: "none",
      conversations: "none",
      files: "read",
      jobs: "none",
      prompts: "none",
      administration: "none"
    });
  });
});

describe("resource access", () => {
  it("keeps a scoped key's own resource from going to no access", () => {
    const draft = withScopeType(newApiKeyDraft(), "assistant");
    const none = {
      ...draft,
      resourcePermissions: { ...draft.resourcePermissions, assistants: "none" as const }
    };
    expect(visibleResources(none)).toEqual(["assistants", "conversations", "files"]);
    expect(resourceLevel(none, "assistants")).toBe("read");
  });

  it("lets a public key read at most, and never jobs or prompts", () => {
    const draft = withKeyType(newApiKeyDraft(), "pk_");
    const admin = {
      ...draft,
      resourcePermissions: { ...draft.resourcePermissions, spaces: "admin" as const }
    };
    expect(visibleResources(admin)).not.toContain("jobs");
    expect(resourceLevel(admin, "spaces")).toBe("none");
  });
});

describe("draftProblems", () => {
  it("names the missing name, scope target, origins and required expiry", () => {
    const draft = { ...withScopeType(withKeyType(newApiKeyDraft(), "pk_"), "space"), name: " " };
    const required = { ...constraints, require_expiration: true };
    expect(draftProblems(draft, { constraints: required }, t)).toEqual({
      name: "api_keys_name_required",
      scope: 'api_keys_select_scope {"scopeType":"api_keys_scope_space"}',
      origins: "api_keys_origin_required",
      expiry: "api_keys_exp_required"
    });
  });

  it("names an invalid entry and a rate limit above the policy's", () => {
    const draft = {
      ...newApiKeyDraft(),
      name: "Integration",
      allowedIps: ["10.0.0.0/8", "300.1.1.1"],
      rateLimit: "5000"
    };
    expect(draftProblems(draft, { constraints }, t)).toEqual({
      ips: "300.1.1.1: api_keys_tag_invalid_octet",
      rateLimit: 'api_keys_rate_limit_max {"max":1000}'
    });
  });

  it("does not ask an edit for a scope target or an expiry", () => {
    const required = { ...constraints, require_expiration: true };
    expect(draftProblems(draftFromApiKey(key), { constraints: required, stored: key }, t)).toEqual(
      {}
    );
  });

  it("renames an unlimited key (-1) without touching its rate limit", () => {
    const unlimited = { ...key, rate_limit: -1 } as ApiKey;
    const draft = { ...draftFromApiKey(unlimited), name: "Webbwidget 2" };
    expect(draftProblems(draft, { constraints: undefined, stored: unlimited }, t)).toEqual({});
    expect(updateRequest(draft, unlimited)).toEqual({ name: "Webbwidget 2" });
  });

  it("renames a key whose rate limit and origins a later policy or check would refuse", () => {
    const old = { ...key, rate_limit: 800, allowed_origins: ["sundsvall.se"] } as ApiKey;
    const draft = { ...draftFromApiKey(old), description: "Ny beskrivning" };
    expect(
      draftProblems(draft, { constraints: { ...constraints, max_rate_limit: 500 }, stored: old }, t)
    ).toEqual({});
    // A changed rate limit is checked as on create.
    expect(
      draftProblems(
        { ...draft, rateLimit: "900" },
        { constraints: { ...constraints, max_rate_limit: 500 }, stored: old },
        t
      )
    ).toMatchObject({ rateLimit: 'api_keys_rate_limit_max {"max":500}' });
  });

  it("takes -1 (no limit) only where no tenant maximum is set, and never 0", () => {
    const draft = { ...newApiKeyDraft(), name: "Batch", rateLimit: "-1" };
    expect(draftProblems(draft, { constraints: undefined }, t)).toEqual({});
    expect(draftProblems(draft, { constraints }, t)).toEqual({
      rateLimit: 'api_keys_rate_limit_max {"max":1000}'
    });
    expect(draftProblems({ ...draft, rateLimit: "0" }, { constraints: undefined }, t)).toEqual({
      rateLimit: "api_keys_rate_limit_invalid"
    });
  });
});

describe("originProblem and ipProblem", () => {
  it.each([
    ["https://sundsvall.se", null],
    ["http://localhost:*", null],
    ["https://*.sundsvall.se", null],
    ["ftp://sundsvall.se", "api_keys_tag_invalid_origin"],
    ["sundsvall.se", "api_keys_tag_invalid_origin"],
    ["https://sund*svall.se/x", "api_keys_tag_invalid_wildcard"]
  ])("origin %s", (value, problem) => expect(originProblem(value)).toBe(problem));

  it.each([
    ["10.0.0.1", null],
    ["10.0.0.0/8", null],
    ["2001:db8::/32", null],
    ["::1", null],
    ["10.0.0.0/33", "api_keys_tag_invalid_cidr"],
    ["256.0.0.1", "api_keys_tag_invalid_octet"],
    ["example.com", "api_keys_tag_invalid_ip"]
  ])("ip %s", (value, problem) => expect(ipProblem(value)).toBe(problem));
});

describe("updateRequest", () => {
  it("sends nothing when nothing changed", () => {
    expect(updateRequest(draftFromApiKey(key), key)).toEqual({});
  });

  it("sends only what changed", () => {
    const draft = {
      ...draftFromApiKey(key),
      description: "För webbplatsen",
      rateLimit: "",
      allowedOrigins: ["https://sundsvall.se", "https://www.sundsvall.se"]
    };
    expect(updateRequest(draft, key)).toEqual({
      description: "För webbplatsen",
      rate_limit: null,
      allowed_origins: ["https://sundsvall.se", "https://www.sundsvall.se"]
    });
  });

  it("sends only the name and description of a revoked or expired key", () => {
    const revoked = { ...key, state: "revoked", resource_permissions: null } as ApiKey;
    const draft = { ...draftFromApiKey(revoked), name: "Gamla widgeten", rateLimit: "" };
    expect(updateRequest(draft, revoked, { metadataOnly: true })).toEqual({
      name: "Gamla widgeten"
    });
  });

  it("sends a legacy key's access (none stored) only when it was edited", () => {
    const legacy = {
      ...key,
      key_type: "sk_",
      scope_type: "tenant",
      permission: "write",
      allowed_origins: null,
      resource_permissions: null
    } as ApiKey;
    const opened = draftFromApiKey(legacy);
    expect(updateRequest(opened, legacy)).toEqual({});
    expect(updateRequest({ ...opened, description: "Ny" }, legacy)).toEqual({ description: "Ny" });
    const narrowed = {
      ...opened,
      resourcePermissions: { ...opened.resourcePermissions, spaces: "read" as const }
    };
    expect(updateRequest(narrowed, legacy).resource_permissions).toMatchObject({
      spaces: "read",
      assistants: "write"
    });
  });

  it("clears a secret key's IP allowlist with null", () => {
    const secret = {
      ...key,
      key_type: "sk_",
      allowed_origins: null,
      allowed_ips: ["10.0.0.0/8"]
    } as ApiKey;
    expect(updateRequest({ ...draftFromApiKey(secret), allowedIps: [] }, secret)).toEqual({
      allowed_ips: null
    });
  });
});

describe("administration", () => {
  const organization = { ...newApiKeyDraft(), administration: "write" as const };
  const organizationKey = {
    ...key,
    key_type: "sk_",
    scope_type: "tenant",
    scope_id: null,
    allowed_origins: null
  } as ApiKey;

  it("is sent as a permission of its own, apart from the key's ceiling", () => {
    const request = createRequest(organization);
    expect(request.resource_permissions).toMatchObject({ administration: "write" });
    expect(request.permission).toBe("read");
    expect(canWrite(organization)).toBe(true);
  });

  it("belongs to a secret key of the whole organization only", () => {
    expect(administrationLevel(withScopeType(organization, "space"))).toBe("none");
    expect(administrationLevel(withKeyType(organization, "pk_"))).toBe("none");
    expect(
      offersAdministration(withScopeType(organization, "space"), { isAdmin: true, held: "none" })
    ).toBe(false);
  });

  it("is given by an administrator; anyone else can only lower what the key holds", () => {
    expect(offersAdministration(organization, { isAdmin: false, held: "none" })).toBe(false);
    expect(offersAdministration(organization, { isAdmin: false, held: "write" })).toBe(true);
    expect(isAdministrationLevelAllowed("read", { isAdmin: false, held: "write" })).toBe(true);
    expect(isAdministrationLevelAllowed("admin", { isAdmin: false, held: "write" })).toBe(false);
    expect(isAdministrationLevelAllowed("admin", { isAdmin: true, held: "none" })).toBe(true);
  });

  it("reads what a stored key holds, and Admin on a resource is not it", () => {
    const resources = { ...key.resource_permissions, prompts: "admin" };
    expect(
      heldAdministration({ ...organizationKey, resource_permissions: resources } as ApiKey)
    ).toBe("none");
    expect(
      heldAdministration({
        ...organizationKey,
        resource_permissions: { ...resources, administration: "admin" }
      } as ApiKey)
    ).toBe("admin");
    // A key without per-resource access keeps the earlier rule.
    const legacy = { ...organizationKey, resource_permissions: null } as ApiKey;
    expect(heldAdministration({ ...legacy, permission: "admin" })).toBe("admin");
    expect(heldAdministration({ ...legacy, permission: "write" })).toBe("none");
  });

  it("is saved when it is the only thing that changed", () => {
    const stored = {
      ...organizationKey,
      resource_permissions: { ...key.resource_permissions, administration: "admin" }
    } as ApiKey;
    const draft = draftFromApiKey(stored);
    expect(updateRequest(draft, stored)).toEqual({});
    expect(updateRequest({ ...draft, administration: "read" }, stored)).toEqual({
      resource_permissions: expect.objectContaining({ administration: "read" })
    });
  });
});

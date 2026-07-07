import { describe, expect, it, vi } from "vitest";
import { buildScopedApiKeyCreateBody, buildTenantApiKeyCreateBody } from "./api-keys";

describe("buildTenantApiKeyCreateBody", () => {
  it("creates tenant-scoped user keys", () => {
    expect(
      buildTenantApiKeyCreateBody({
        name: " Production ",
        ownership: "user",
        permission: "read",
        expiryDays: "never"
      })
    ).toEqual({
      name: "Production",
      key_type: "sk_",
      permission: "read",
      scope_type: "tenant",
      ownership: "user",
      expires_at: null
    });
  });
});

describe("buildScopedApiKeyCreateBody", () => {
  it("locks assistant keys to the selected assistant scope", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

    expect(
      buildScopedApiKeyCreateBody({
        name: " Assistant runner ",
        scopeType: "assistant",
        scopeId: "assistant-id",
        permission: "write",
        expiryDays: "30"
      })
    ).toEqual({
      name: "Assistant runner",
      key_type: "sk_",
      permission: "write",
      scope_type: "assistant",
      scope_id: "assistant-id",
      ownership: "user",
      expires_at: "2026-01-31T00:00:00.000Z"
    });

    vi.useRealTimers();
  });

  it("locks space keys to the selected space scope", () => {
    expect(
      buildScopedApiKeyCreateBody({
        name: "Space key",
        scopeType: "space",
        scopeId: "space-id",
        permission: "admin",
        expiryDays: "never"
      })
    ).toMatchObject({
      name: "Space key",
      key_type: "sk_",
      permission: "admin",
      scope_type: "space",
      scope_id: "space-id",
      ownership: "user",
      expires_at: null
    });
  });
});

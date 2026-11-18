import { expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import { ssoEntry } from "./sso-entry";

const status = (
  changes: Partial<Schema<"FederationStatusResponse">> = {}
): Schema<"FederationStatusResponse"> => ({
  has_global_oidc_config: false,
  has_single_tenant_federation: false,
  has_multi_tenant_federation: false,
  tenant_count: 0,
  ...changes
});

it.each([{ has_global_oidc_config: true }, { has_single_tenant_federation: true }])(
  "offers the backend initiate route for %j",
  (flags) => {
    expect(ssoEntry(status(flags))).toBe("/api/v1/auth/browser/initiate");
  }
);

it("encodes a safe continuation and replaces an external one", () => {
  expect(ssoEntry(status({ has_global_oidc_config: true }), "/spaces/x?a=1")).toBe(
    "/api/v1/auth/browser/initiate?next=%2Fspaces%2Fx%3Fa%3D1"
  );
  expect(ssoEntry(status({ has_global_oidc_config: true }), "//evil.example")).toBe(
    "/api/v1/auth/browser/initiate?next=%2Fspaces%2Fpersonal%2Fchat"
  );
});

it.each([
  null,
  status(),
  status({ has_multi_tenant_federation: true, has_global_oidc_config: true })
])("leaves password or tenant selection to its owner for %j", (value) => {
  expect(ssoEntry(value)).toBeNull();
});

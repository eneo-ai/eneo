import { describe, expect, it } from "vitest";
import { integrationSetupAction } from "./setup-action";

describe("integrationSetupAction", () => {
  it("imports when there are configured integrations available", () => {
    expect(
      integrationSetupAction({
        importableCount: 1,
        personal: false,
        organization: false,
        isAdmin: false
      })
    ).toEqual({ kind: "import" });
  });

  it("links personal spaces to account integration settings", () => {
    expect(
      integrationSetupAction({
        importableCount: 0,
        personal: true,
        organization: false,
        isAdmin: false
      })
    ).toEqual({ kind: "link", href: "/account/integrations?tab=providers" });
  });

  it("links admins in shared spaces to admin integration settings", () => {
    expect(
      integrationSetupAction({
        importableCount: 0,
        personal: false,
        organization: false,
        isAdmin: true
      })
    ).toEqual({ kind: "link", href: "/admin/integrations?tab=providers" });
  });

  it("uses the organization-specific admin hint for organization spaces", () => {
    expect(
      integrationSetupAction({
        importableCount: 0,
        personal: false,
        organization: true,
        isAdmin: false
      })
    ).toEqual({ kind: "message", messageKey: "org_integrations_require_admin" });
  });
});

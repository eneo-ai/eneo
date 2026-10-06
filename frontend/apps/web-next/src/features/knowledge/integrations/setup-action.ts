export type IntegrationSetupAction =
  | { kind: "import" }
  | {
      kind: "link";
      href: "/account/integrations?tab=providers" | "/admin/integrations?tab=providers";
    }
  | {
      kind: "message";
      messageKey: "org_integrations_require_admin" | "shared_integrations_require_admin";
    };

export function integrationSetupAction({
  importableCount,
  personal,
  organization,
  isAdmin
}: {
  importableCount: number;
  personal: boolean;
  organization: boolean;
  isAdmin: boolean;
}): IntegrationSetupAction {
  if (importableCount > 0) return { kind: "import" };
  if (personal) return { kind: "link", href: "/account/integrations?tab=providers" };
  if (isAdmin) return { kind: "link", href: "/admin/integrations?tab=providers" };
  return {
    kind: "message",
    messageKey: organization
      ? "org_integrations_require_admin"
      : "shared_integrations_require_admin"
  };
}

import type { Eneo, UserIntegration, components } from "@eneo/eneo-js";

export type SharePointFixtureScenario = components["schemas"]["SharePointFixtureScenario"];
export type SharePointFixturePreviewResponse =
  components["schemas"]["SharePointFixturePreviewResponse"];
export type SharePointFixtureTreeResponse = components["schemas"]["SharePointFixtureTreeResponse"];

export const SHAREPOINT_FIXTURE_QUERY_PARAMETER = "sharepoint_fixture";

const SHAREPOINT_FIXTURE_INTEGRATION_ID = "00000000-0000-4000-8000-000000000001";
const SHAREPOINT_FIXTURE_TENANT_INTEGRATION_ID = "00000000-0000-4000-8000-000000000002";

export type SharePointFixtureAuthType = "user_oauth" | "tenant_app";

export type SharePointSetupFixtureScenario = "fresh" | "configured" | "connection_error";

export function isSharePointSetupFixtureScenario(
  value: string
): value is SharePointSetupFixtureScenario {
  return value === "fresh" || value === "configured" || value === "connection_error";
}

// Mirrors the error Microsoft Entra returns for a bad client secret, so the
// setup demo exercises the same long, untranslated message the real flow shows.
export const SHAREPOINT_SETUP_FIXTURE_TEST_ERROR =
  "AADSTS7000215: Invalid client secret provided. " +
  "Ensure the secret being sent in the request is the client secret value, " +
  "not the client secret ID.";

export function createSharePointSetupFixtureConfig(options: {
  authMethod: "tenant_app" | "service_account";
  clientId?: string;
  tenantDomain?: string;
  clientSecret?: string;
}): components["schemas"]["TenantSharePointAppPublic"] {
  const clientId = options.clientId?.trim() || "12345678-1234-1234-1234-123456789012";
  const tenantDomain = options.tenantDomain?.trim() || "kommunen.onmicrosoft.com";
  const secret = options.clientSecret || "fixture-secret-3kQ";
  return {
    id: "00000000-0000-4000-8000-000000000101",
    tenant_id: "00000000-0000-4000-8000-000000000102",
    client_id: clientId,
    client_secret_masked: `••••••••${secret.slice(-3)}`,
    tenant_domain: tenantDomain,
    is_active: true,
    auth_method: options.authMethod,
    service_account_email:
      options.authMethod === "service_account" ? `eneo-tjanstekonto@${tenantDomain}` : null,
    certificate_path: null,
    created_by: null,
    created_at: "2026-08-01T09:00:00.000Z",
    updated_at: "2026-08-20T14:30:00.000Z"
  };
}

// Keeps loading states visible in the simulated setup flow.
export function sharePointFixtureDelay(ms = 450): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function isSharePointFixtureModeRequested(
  searchParams: Pick<URLSearchParams, "has">
): boolean {
  return searchParams.has(SHAREPOINT_FIXTURE_QUERY_PARAMETER);
}

export function parseSharePointFixtureScenario(
  searchParams: Pick<URLSearchParams, "get">
): SharePointFixtureScenario | null {
  const value = searchParams.get(SHAREPOINT_FIXTURE_QUERY_PARAMETER);
  switch (value) {
    case "representative":
    case "large_tenant":
    case "empty":
      return value;
    default:
      return null;
  }
}

export function createSharePointFixtureIntegration(
  authType: SharePointFixtureAuthType
): UserIntegration {
  return {
    id: SHAREPOINT_FIXTURE_INTEGRATION_ID,
    name: "SharePoint test data",
    description: "Development-only SharePoint fixture data",
    integration_type: "sharepoint",
    tenant_integration_id: SHAREPOINT_FIXTURE_TENANT_INTEGRATION_ID,
    connected: true,
    auth_type: authType,
    tenant_app_id: null,
    tenant_app_configured: false
  };
}

/**
 * Make the fixture picker reachable even when the tenant has no Microsoft
 * provider configured. The returned integration only exists in page data and
 * fixture mode prevents it from reaching the real import/Graph paths.
 */
export function withSharePointFixtureIntegration(
  integrations: readonly UserIntegration[],
  searchParams: Pick<URLSearchParams, "has">,
  authType: SharePointFixtureAuthType
): UserIntegration[] {
  const availableIntegrations = [...integrations];
  if (!isSharePointFixtureModeRequested(searchParams)) return availableIntegrations;

  const hasConnectedSharePointIntegration = availableIntegrations.some(
    (integration) =>
      integration.integration_type === "sharepoint" &&
      integration.connected &&
      integration.auth_type === authType
  );
  if (hasConnectedSharePointIntegration) return availableIntegrations;

  return [...availableIntegrations, createSharePointFixtureIntegration(authType)];
}

export function assertSharePointFixtureEnvelope(
  response: { fixture?: true; scenario: SharePointFixtureScenario },
  requestedScenario: SharePointFixtureScenario
): void {
  if (response.fixture !== true || response.scenario !== requestedScenario) {
    throw new Error("SharePoint fixture endpoint returned an invalid fixture envelope");
  }
}

export async function fetchSharePointFixturePreview(
  client: Eneo["client"],
  scenario: SharePointFixtureScenario
): Promise<SharePointFixturePreviewResponse> {
  const response = await client.fetch(
    "/api/v1/integrations/sharepoint/fixtures/{scenario}/preview/",
    {
      method: "get",
      params: { path: { scenario } }
    }
  );
  assertSharePointFixtureEnvelope(response, scenario);
  return response;
}

type FixtureTreeRequest = {
  siteId?: string;
  driveId?: string;
  folderId?: string;
  folderPath?: string;
};

export async function fetchSharePointFixtureTree(
  client: Eneo["client"],
  scenario: SharePointFixtureScenario,
  request: FixtureTreeRequest
): Promise<SharePointFixtureTreeResponse> {
  const response = await client.fetch("/api/v1/integrations/sharepoint/fixtures/{scenario}/tree/", {
    method: "get",
    params: {
      path: { scenario },
      query: {
        site_id: request.siteId,
        drive_id: request.driveId,
        folder_id: request.folderId,
        folder_path: request.folderPath
      }
    }
  });
  assertSharePointFixtureEnvelope(response, scenario);
  return response;
}

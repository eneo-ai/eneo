import type { Eneo, UserIntegration, components } from "@eneo/eneo-js";

export type SharePointFixtureScenario = components["schemas"]["SharePointFixtureScenario"];
export type SharePointFixturePreviewResponse =
  components["schemas"]["SharePointFixturePreviewResponse"];
export type SharePointFixtureTreeResponse = components["schemas"]["SharePointFixtureTreeResponse"];

export const SHAREPOINT_FIXTURE_QUERY_PARAMETER = "sharepoint_fixture";

const SHAREPOINT_FIXTURE_INTEGRATION_ID = "00000000-0000-4000-8000-000000000001";
const SHAREPOINT_FIXTURE_TENANT_INTEGRATION_ID = "00000000-0000-4000-8000-000000000002";

export type SharePointFixtureAuthType = "user_oauth" | "tenant_app";

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

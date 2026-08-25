import type { Eneo, components } from "@eneo/eneo-js";

export type SharePointFixtureScenario = components["schemas"]["SharePointFixtureScenario"];
export type SharePointFixturePreviewResponse =
  components["schemas"]["SharePointFixturePreviewResponse"];
export type SharePointFixtureTreeResponse = components["schemas"]["SharePointFixtureTreeResponse"];

export const SHAREPOINT_FIXTURE_QUERY_PARAMETER = "sharepoint_fixture";

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

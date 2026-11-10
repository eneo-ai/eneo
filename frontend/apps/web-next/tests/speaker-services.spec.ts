import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, apiRequest, uniqueName } from "./helpers";

// The e2e stack's mock timing service (e2e/mock_model_server.py) answers its
// readiness check with word timings and no speakers.
const ENDPOINT = "http://e2e-mock-model:8200";
const KEY = "e2e-timing-fixture";

test.describe("speaker identification services", { tag: "@vite" }, () => {
  test("an administrator connects a service, a space is given it and its flow lists it", async ({
    page
  }) => {
    const name = uniqueName("E2E Vemsa");

    // Connect: the new service is tested at once and the dialog stays on it.
    await page.goto("/admin/models");
    await page.getByRole("tab", { name: "Ordtider och talaridentifiering" }).click();
    const panel = page.getByRole("tabpanel");
    // The connect action sits in the page header, beside the tabs.
    await page.getByRole("button", { name: "Anslut tjänst" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/^Namn/).fill(name);
    await dialog.getByLabel(/^Adress/).fill(ENDPOINT);
    await dialog.getByLabel(/^API-nyckel/).fill(KEY);
    await dialog.getByRole("button", { name: "Anslut", exact: true }).click();
    await expect(dialog.getByRole("heading", { name: `${name} är ansluten` })).toBeVisible();
    await expect(dialog.getByText("Tar emot jobb", { exact: true })).toBeVisible();
    // The key is write-only: the field is empty again and nothing shows it.
    await expect(dialog.getByLabel(/^API-nyckel/)).toHaveValue("");
    await expect(dialog.getByRole("button", { name: "Klar" })).toBeFocused();
    await dialog.getByRole("button", { name: "Klar" }).click();
    await expect(dialog).toBeHidden();
    const row = panel.getByRole("row", { name: new RegExp(name) });
    await expect(row).toContainText("Tar emot jobb");
    await expect(row).toContainText("e2e-mock-model:8200");
    await expect(page.getByText(KEY)).toHaveCount(0);

    // Grant it to a space in the space's settings.
    const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E speaker space") });
    await page.goto(`/spaces/${spaceId}/settings`);
    const grant = page.locator("#speaker-services").getByRole("switch", { name });
    await expect(grant).not.toBeChecked();
    const saved = page.waitForResponse(
      (response) =>
        response.request().method() === "PATCH" &&
        new URL(response.url()).pathname === `/api/v1/spaces/${spaceId}/`
    );
    await grant.click();
    expect((await saved).ok()).toBe(true);
    await expect(grant).toBeChecked();

    // A flow in the space that transcribes with the service lists it.
    const space = await apiRequest<Schema<"SpacePublic">>(page, `/spaces/${spaceId}/`);
    expect(space.transcription_services?.map((granted) => granted.name)).toEqual([name]);
    const serviceId = space.transcription_services![0]!.id;
    const modelId = space.transcription_models[0]?.id;
    if (!modelId) throw new Error("The E2E space has no seeded transcription model");
    const flow = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
      method: "POST",
      body: { space_id: spaceId, name: uniqueName("E2E speaker flow") }
    });
    await apiRequest(page, `/flows/${flow.id}/editor/`, {
      method: "PATCH",
      body: {
        expected_revision: flow.draft_revision,
        definition: {
          metadata_json: {
            wizard: {
              transcription_enabled: true,
              transcription_model: { id: modelId },
              transcription_language: "sv",
              transcription_diarization: false,
              transcription_speaker_service: { id: serviceId }
            }
          }
        },
        new_steps: [
          {
            name: "Transkribera",
            assistant: {},
            configuration: {
              input_source: "flow_input",
              input_type: "audio",
              output_mode: "transcribe_only",
              output_type: "text",
              input_config: {
                runtime_input: { enabled: true, required: true, input_format: "audio" }
              }
            }
          }
        ]
      } satisfies Schema<"FlowEditorUpdateRequest">
    });
    await page.goto(`/spaces/${spaceId}/flows/${flow.id}`);
    const settings = page.getByRole("region", { name: "Inställningar" });
    await expect(settings.getByText(name, { exact: true })).toBeVisible();
    // Granted and usable: no "no longer in the space" warning.
    await expect(settings.getByText("Den valda tjänsten finns inte längre i ytan.")).toHaveCount(0);
  });
});

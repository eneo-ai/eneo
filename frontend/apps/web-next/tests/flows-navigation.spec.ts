import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, apiRequest, collectAssetFailures, productionAsset, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served production Vite build.");

test(
  "keeps a flow draft on Stay and confirms a missing-chunk departure once",
  { tag: "@vite" },
  async ({ page }, info) => {
    await page.goto("/spaces/list");
    const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E flow navigation") });
    const flow = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
      method: "POST",
      body: { space_id: spaceId, name: uniqueName("E2E draft") }
    });
    const saved = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${flow.id}/editor/`, {
      method: "PATCH",
      body: {
        expected_revision: flow.draft_revision,
        definition: {},
        new_steps: [
          {
            name: "Manuellt steg",
            assistant: {},
            configuration: {
              input_source: "flow_input",
              input_type: "text",
              output_mode: "pass_through",
              output_type: "text"
            }
          }
        ]
      } satisfies Schema<"FlowEditorUpdateRequest">
    });
    await page.goto(`/spaces/${spaceId}/flows/${flow.id}?step=${saved.steps[0]!.id}`);
    const name = page.getByRole("textbox", { name: /^Stegnamn/ });
    await name.fill("Osparat steg");
    const originalUrl = page.url();

    const missing = productionAsset("src/routes/_app/admin/users.tsx?tsr-split=component");
    const unexpected = collectAssetFailures(page, new Set([missing]));
    let missingRequests = 0;
    let reloads = 0;
    const nativePrompts: string[] = [];
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) reloads++;
    });
    page.on("dialog", async (dialog) => {
      nativePrompts.push(dialog.type());
      await dialog.dismiss();
    });
    // The first import is gone, as after deployment; the recovered document can load its route.
    await page.route(
      (url) => url.pathname === missing,
      async (route) => {
        missingRequests++;
        if (missingRequests === 1) {
          await route.fulfill({
            status: 404,
            contentType: "text/plain",
            body: "Removed deployment asset"
          });
        } else await route.continue();
      }
    );
    async function openUsers() {
      await page.getByRole("button", { name: "Sök", exact: true }).click();
      const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
      await palette.getByRole("combobox").fill("Användare");
      await palette
        .getByRole("option", { name: "Administration › Användare", exact: true })
        .click();
    }
    await openUsers();
    const confirmation = page.getByRole("alertdialog", { name: "Lämna sidan?", exact: true });
    await confirmation.getByRole("button", { name: "Avbryt", exact: true }).click();
    // A retained frame is insufficient: Stay must leave the editor usable after pending work settles.
    await page.waitForTimeout(1_000);
    await expect(page).toHaveURL(originalUrl);
    await expect(name).toBeEditable();
    await expect(name).toHaveValue("Osparat steg");
    expect(missingRequests).toBe(0);
    expect(reloads).toBe(0);
    await name.fill("Osparat steg med fortsättning");
    await page.screenshot({ path: info.outputPath("flow-draft-after-stay.png"), fullPage: true });

    await openUsers();
    await confirmation.getByRole("button", { name: "Lämna utan att spara", exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
    await expect(page.getByRole("button", { name: /skapa användare|create user/i })).toBeEnabled();
    expect(nativePrompts).toEqual([]);
    expect(reloads).toBe(1);
    expect(missingRequests).toBe(2);
    expect(unexpected).toEqual([]);
    const unchanged = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${flow.id}/`);
    expect(unchanged.steps[0]!.user_description).toBe("Manuellt steg");
    await info.attach("flow-departure-observation", {
      contentType: "application/json",
      body: JSON.stringify({ missingRequests, reloads, nativePrompts })
    });
  }
);

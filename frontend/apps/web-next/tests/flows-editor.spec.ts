import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, apiRequest, uniqueName } from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served production Vite build.");

test.describe("the run form on a touch tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test(
    "reorders the run form's fields with 44 px buttons and the keyboard, and saves the order",
    { tag: "@vite" },
    async ({ page }) => {
      await page.goto("/spaces/list");
      const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E run form") });
      const flow = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
        method: "POST",
        body: { space_id: spaceId, name: uniqueName("E2E run form") }
      });
      await apiRequest(page, `/flows/${flow.id}/editor/`, {
        method: "PATCH",
        body: {
          expected_revision: flow.draft_revision,
          definition: {
            metadata_json: {
              form_schema: {
                fields: [
                  {
                    name: "diarienummer",
                    label: "Diarienummer",
                    type: "text",
                    required: true,
                    order: 1
                  },
                  { name: "datum", label: "Datum", type: "date", required: false, order: 2 }
                ]
              }
            }
          }
        } satisfies Schema<"FlowEditorUpdateRequest">
      });
      await page.goto(`/spaces/${spaceId}/flows/${flow.id}`);
      await page.getByRole("button", { name: "Ändra inställningar", exact: true }).click();

      const down = page.getByRole("button", { name: "Flytta ner Diarienummer", exact: true });
      const up = page.getByRole("button", { name: "Flytta upp Diarienummer", exact: true });
      for (const button of [down, up]) {
        const box = await button.boundingBox();
        expect(box?.width).toBeGreaterThanOrEqual(44);
        expect(box?.height).toBeGreaterThanOrEqual(44);
      }
      await expect(up).toBeDisabled();
      await down.tap();
      // Last now, its down button is off and its up button holds the focus.
      await expect(down).toBeDisabled();
      await expect(up).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(down).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(up).toBeFocused();

      await page.getByRole("button", { name: "Spara inställningar", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "Ändra inställningar", exact: true })
      ).toBeVisible();
      const saved = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${flow.id}/`);
      const form = (
        saved.metadata_json as { form_schema: { fields: { name: string; order: number }[] } }
      ).form_schema;
      expect(form.fields.map(({ name, order }) => [name, order])).toEqual([
        ["datum", 1],
        ["diarienummer", 2]
      ]);
    }
  );
});

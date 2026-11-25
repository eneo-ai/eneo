import type { Locator } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, apiRequest, sessionResponseHeaders, uniqueName } from "./helpers";

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

test.describe("a tool step's long text argument", () => {
  // Tall enough that half the window is more than the field's 15 lines.
  test.use({ viewport: { width: 1280, height: 900 } });

  const serverId = "6f1c2b9a-4d3e-4f50-8a71-1b2c3d4e5f60";
  const toolId = "0a9b8c7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
  const lines = (count: number) =>
    Array.from({ length: count }, (_, line) => `SELECT ${line + 1}`).join("\n");
  const heights = (field: Locator) =>
    field.evaluate((element) => ({
      scroll: element.scrollHeight,
      client: element.clientHeight
    }));

  test(
    "grows to 15 lines and scrolls, and its value scrolls from the keyboard in the preview",
    { tag: "@vite" },
    async ({ page }) => {
      // The space has no MCP server: the step's tool comes from this answer.
      await page.route("**/api/v1/flows/*/tool-options*", (route) =>
        route.fulfill({
          json: {
            security_classifications_enabled: false,
            items: [
              {
                mcp_server_id: serverId,
                mcp_server_name: "Driftdatabas",
                mcp_server_security_level: null,
                tool_id: toolId,
                tool_name: "kor_fraga",
                tool_description: null,
                refusal: null,
                input_schema: { properties: { sql: { type: "string" } }, required: ["sql"] }
              }
            ]
          } satisfies Schema<"FlowToolOptionsPublic">,
          headers: sessionResponseHeaders(route)
        })
      );
      await page.goto("/spaces/list");
      const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E tool argument") });
      const flow = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
        method: "POST",
        body: { space_id: spaceId, name: uniqueName("E2E tool argument") }
      });
      // A draft does not ask whether the server exists; publishing would.
      await apiRequest(page, `/flows/${flow.id}/editor/`, {
        method: "PATCH",
        body: {
          expected_revision: flow.draft_revision,
          definition: {},
          new_steps: [
            {
              name: "Fråga databasen",
              assistant: {},
              configuration: {
                input_source: "tool",
                input_type: "text",
                output_mode: "compose_text",
                output_type: "text",
                input_config: {
                  tool: {
                    mcp_server_id: serverId,
                    tool_id: toolId,
                    arguments: { sql: lines(60) }
                  }
                }
              }
            }
          ]
        } satisfies Schema<"FlowEditorUpdateRequest">
      });
      await page.goto(`/spaces/${spaceId}/flows/${flow.id}`);
      await page.getByRole("button", { name: /Redigera.*Fråga databasen/ }).click();

      // Sixty lines: the field stops at its cap and scrolls.
      const sql = page.getByRole("textbox", { name: /^sql/ });
      await expect(sql).toHaveValue(lines(60));
      const capped = await heights(sql);
      expect(capped.scroll).toBeGreaterThan(capped.client + 1);

      // The preview shows the value in a region that scrolls from the keyboard.
      const open = page.getByRole("button", { name: "Visa anropet", exact: true });
      await open.click();
      const dialog = page.getByRole("dialog", { name: "Det steget skickar" });
      const value = dialog.getByRole("region", { name: "Värdet för sql" });
      await expect(value).toBeVisible();
      for (let press = 0; press < 10; press++) {
        if (await value.evaluate((element) => element === document.activeElement)) break;
        await page.keyboard.press("Tab");
      }
      await expect(value).toBeFocused();
      await page.keyboard.press("PageDown");
      await expect.poll(() => value.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(open).toBeFocused();

      // Fifteen lines fit without scrolling at the same height; a sixteenth scrolls.
      await sql.fill(lines(15));
      const fifteen = await heights(sql);
      expect(Math.abs(fifteen.scroll - fifteen.client)).toBeLessThanOrEqual(1);
      expect(Math.abs(fifteen.client - capped.client)).toBeLessThanOrEqual(1);
      await sql.fill(lines(16));
      const sixteen = await heights(sql);
      expect(sixteen.scroll).toBeGreaterThan(sixteen.client + 1);
    }
  );
});

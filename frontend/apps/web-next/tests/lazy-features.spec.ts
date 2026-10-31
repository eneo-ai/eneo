import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import {
  apiPath,
  apiPost,
  apiPostJson,
  askChatQuestion,
  collectAssetFailures,
  conversationLog,
  MOCK_REPLY,
  uniqueName
} from "./helpers";

const fixtures = path.resolve("../../../e2e/fixtures");

test.describe("production lazy features", { tag: "@vite" }, () => {
  test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served production Vite build.");

  test("previews the original DOCX and workbook in the file panel", async ({ page }) => {
    const failures = collectAssetFailures(page);
    await page.goto("/spaces/personal/chat");
    await page.locator('input[type="file"]').setInputFiles([
      {
        name: "sample.docx",
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: await readFile(path.join(fixtures, "sample.docx"))
      },
      {
        name: "workflow.xlsx",
        mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buffer: await readFile(path.join(fixtures, "workflow.xlsx"))
      }
    ]);
    await askChatQuestion(page, uniqueName("Preview the attached originals"));
    const log = conversationLog(page);
    await expect(log.getByText(MOCK_REPLY)).toBeVisible({ timeout: 30_000 });
    await log.getByRole("button", { name: "Förhandsgranska sample.docx", exact: true }).click();
    await expect(
      page
        .frameLocator('iframe[title="sample.docx"]')
        .getByText("Vite document preview", { exact: true })
    ).toBeVisible();
    await log.getByRole("button", { name: "Förhandsgranska workflow.xlsx", exact: true }).click();
    const table = page.getByRole("table", { name: "Sales", exact: true });
    await expect(table).toBeVisible();
    await expect(table.getByRole("columnheader", { name: /region/ })).toBeVisible();
    await expect(table.getByText("north", { exact: true }).first()).toBeVisible();
    expect(failures, "production asset failures").toEqual([]);
  });

  test("renders a real bundled tool frame and the usage chart", async ({ page }) => {
    test.setTimeout(180_000);
    const failures = collectAssetFailures(page);
    await page.goto("/spaces/personal/chat");
    const catalogResponse = await page.request.get(apiPath("/mcp-servers/bundled/"));
    expect(catalogResponse.ok()).toBe(true);
    const catalog: Schema<"BundledToolList"> = await catalogResponse.json();
    for (const name of ["file-analysis", "file-creation", "charts"]) {
      const existing = catalog.items.find((item) => item.tool === name)?.mcp_server_id;
      if (existing) {
        await apiPostJson<Schema<"CapabilityActivationResponse">>(
          page,
          `/mcp-servers/${existing}/activate/`,
          {}
        );
      } else {
        await apiPostJson<Schema<"MCPServerCreateResponse">>(
          page,
          `/mcp-servers/bundled/${name}/`,
          { activate: true }
        );
      }
    }
    const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("Lazy feature tools") });
    const assistantId = await apiPost(page, `/spaces/${spaceId}/applications/assistants/`, {
      name: uniqueName("Lazy feature workflow")
    });
    const skill = await apiPostJson<Schema<"SkillPublic">>(page, `/spaces/${spaceId}/skills/`, {
      slug: `lazy-workflow-${Date.now()}`,
      display_name: "Workflow analysis",
      description: "Use for the E2E_WORKFLOW report and revision.",
      instructions:
        "Inspect the workbook, query saved values, disclose missing formula results, and write a report."
    });
    await apiPost(page, `/assistants/${assistantId}/`, {
      enabled_capabilities: ["file_analysis", "file_creation", "charts"],
      inline_file_text: false,
      skill_bindings: [
        {
          skill_id: skill.id,
          skill_revision_id: skill.current_revision.id,
          activation_mode: "on_demand"
        }
      ]
    });
    await page.goto(`/spaces/${spaceId}/chat?type=assistant&id=${assistantId}&tab=chat`);
    await page.locator('input[type="file"]').setInputFiles({
      name: "workflow.xlsx",
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: await readFile(path.join(fixtures, "workflow.xlsx"))
    });
    await askChatQuestion(page, "E2E_WORKFLOW_REPORT: analyse the workbook and create a report.");
    const log = conversationLog(page);
    await expect(log).toContainText(/E2E workflow /, { timeout: 90_000 });
    await log.getByRole("button", { name: /^Aktivitet:/ }).click();
    await expect(
      log.getByText("E2E workflow complete. Saved-value total: 180300; 1 formula result missing.", {
        exact: true
      })
    ).toBeVisible();
    await expect
      .poll(async () => {
        const frames = [];
        for (const frame of page.frames()) {
          if (await frame.getByRole("button", { name: /Show more rows|Visa fler rader/ }).count())
            frames.push(frame);
        }
        return frames.length;
      })
      .toBe(1);
    for (const frame of page.frames()) {
      const more = frame.getByRole("button", { name: /Show more rows|Visa fler rader/ });
      if (await more.count()) {
        await more.click();
        await expect(frame.getByText(/601 rows|601 rader/, { exact: true })).toBeVisible();
      }
    }
    await page.goto("/admin/insights");
    await expect(page.locator("svg.recharts-surface").first()).toBeVisible();
    expect(failures, "production asset failures").toEqual([]);
  });
});

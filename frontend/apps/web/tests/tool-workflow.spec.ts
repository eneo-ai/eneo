import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { askChatQuestion, backendFetch, expectOk, uniqueName } from "./helpers";

type WorkflowMessage = { generated_files?: { id: string; mimetype: string }[] };
type WorkflowConversation = {
  messages?: WorkflowMessage[];
  questions?: WorkflowMessage[];
};

test("workbook tools produce a report, preserve revisions, and recheck export support", async ({
  page,
  request
}) => {
  test.setTimeout(180_000);
  await page.goto("/");
  const api = async (path: string, data?: unknown, method = "POST") => {
    const res = await backendFetch(
      page,
      request,
      "/api/v1" + path,
      data === undefined ? { method: "GET" } : { method, data }
    );
    await expectOk(res, path);
    return res.json();
  };
  const providers = [];
  const catalog: { items: { tool: string; mcp_server_id?: string | null }[] } =
    await api("/mcp-servers/bundled/");
  for (const name of ["file-analysis", "file-creation", "charts"]) {
    const existing = catalog.items.find((item) => item.tool === name)?.mcp_server_id;
    if (existing) {
      await api(`/mcp-servers/${existing}/activate/`, {});
      providers.push({ id: existing });
    } else {
      providers.push((await api(`/mcp-servers/bundled/${name}/`, { activate: true })).server);
    }
  }
  const space = await api("/spaces/type/personal/");
  const assistant = await api(`/spaces/${space.id}/applications/assistants/`, {
    name: uniqueName("Workflow")
  });
  const skill = await api(`/spaces/${space.id}/skills/`, {
    slug: `workflow-${Date.now()}`,
    display_name: "Workflow analysis",
    description: "Use for the E2E_WORKFLOW report and revision.",
    instructions:
      "Inspect the workbook, query saved values, disclose missing formula results, and write a report."
  });
  await api(`/assistants/${assistant.id}/`, {
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
  await page.goto(`/spaces/personal/chat/?type=assistant&id=${assistant.id}&tab=chat`);
  await page.locator("input[type=file]").setInputFiles({
    name: "workflow.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: await readFile(new URL("../../../../e2e/fixtures/workflow.xlsx", import.meta.url))
  });
  await expect(page.getByText("workflow.xlsx", { exact: true }).first()).toBeVisible();
  await askChatQuestion(page, "E2E_WORKFLOW_REPORT: analyse the workbook and create a report.");
  const conversation = page.locator("#session-message-container");
  await expect(
    conversation.getByText(
      "E2E workflow complete. Saved-value total: 180300; 1 formula result missing.",
      { exact: true }
    )
  ).toBeVisible({ timeout: 90_000 });
  await conversation.getByRole("button", { name: /Skills.*6/ }).click();
  await expect(conversation.getByRole("button", { name: /Workflow analysis/ })).toBeVisible();

  // The formula notice is rendered by the table itself, independently of model prose.
  await expect
    .poll(async () => {
      for (const frame of page.frames()) {
        if (
          await frame
            .getByText(/formula cells have no saved result|formelceller saknar sparade resultat/)
            .count()
        )
          return true;
      }
      return false;
    })
    .toBe(true);

  const tableFrames = [];
  for (const frame of page.frames()) {
    if (await frame.getByRole("button", { name: /Show more rows|Visa fler rader/ }).count())
      tableFrames.push(frame);
  }
  expect(tableFrames).toHaveLength(1);
  await tableFrames[0].getByRole("button", { name: /Show more rows|Visa fler rader/ }).click();
  await expect(tableFrames[0].getByText(/601 rows|601 rader/, { exact: true })).toBeVisible();

  const sessions = await api(`/assistants/${assistant.id}/sessions/`);
  const sessionId = sessions.items[0].id;
  const session: WorkflowConversation = await api(`/conversations/${sessionId}/`);
  const messages = session.messages ?? session.questions ?? [];
  const document = messages
    .flatMap((q) => q.generated_files ?? [])
    .find((f) => f.mimetype === "text/markdown");
  if (!document) throw new Error("Expected the workflow to generate a Markdown document");
  const exportPath = `/conversations/${sessionId}/documents/${document.id}/export/`;
  expect((await api(exportPath)).docx.available).toBe(true);
  for (const format of ["docx", "pdf"]) {
    const output = await backendFetch(page, request, "/api/v1" + exportPath, {
      method: "POST",
      data: { format }
    });
    await expectOk(output, "exporting " + format);
    const bytes = await output.body();
    expect(bytes.subarray(0, format === "pdf" ? 4 : 2).toString()).toBe(
      format === "pdf" ? "%PDF" : "PK"
    );
  }

  await askChatQuestion(page, "E2E_WORKFLOW_EDIT: replace Draft wording with Revised wording.");
  await expect(
    conversation.getByText("E2E workflow revision complete.", { exact: true })
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Revised wording.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^(Previous version|Föregående version)$/ }).click();
  await expect(page.getByText("Draft wording.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^(Next version|Nästa version)$/ }).click();
  await expect(page.getByText("Revised wording.", { exact: true })).toBeVisible();
  const revised: WorkflowConversation = await api(`/conversations/${sessionId}/`);
  const revisedMessages = revised.messages ?? revised.questions ?? [];
  const documents = revisedMessages
    .flatMap((q) => q.generated_files ?? [])
    .filter((f) => f.mimetype === "text/markdown");
  expect(documents.length).toBe(2);
  await page.goto(
    `/spaces/personal/chat/?type=assistant&id=${assistant.id}&tab=chat&session_id=${sessionId}`
  );
  await page.reload();
  await expect(
    conversation.getByText("E2E workflow revision complete.", { exact: true })
  ).toBeVisible();

  // Losing a provider cannot make existing saved documents disappear.
  await api(`/mcp-servers/${providers[1].id}/deactivate/`, {});
  expect((await api(exportPath)).docx.available).toBe(false);
  const refused = await backendFetch(page, request, "/api/v1" + exportPath, {
    method: "POST",
    data: { format: "docx" }
  });
  expect(refused.status()).toBe(409);
  await api(`/mcp-servers/${providers[1].id}/activate/`, {});
  expect((await api(exportPath)).docx.available).toBe(true);

  // A Skill cannot restore a Function removed from this Assistant.
  await api(`/assistants/${assistant.id}/`, { enabled_capabilities: ["file_creation"] });
  await page.reload();
  await askChatQuestion(page, "E2E_WORKFLOW_REPORT: analyse the workbook again.");
  await expect(
    conversation.getByText("E2E workflow unavailable: inspect_table", { exact: true })
  ).toBeVisible({ timeout: 30_000 });
});

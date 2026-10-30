import { expect, test } from "./csp";
import { askChatQuestion, isChatStream, MOCK_REPLY, uniqueName } from "./helpers";

test.describe("unsaved edits on Vite", { tag: "@vite" }, () => {
  test.skip(!process.env.E2E_BASE_URL, "The in-app blocker is owned by the Vite router.");

  test("Skills keep edits on cancelled Back and link navigation, then leave on confirmation", async ({
    page
  }) => {
    await page.goto("/spaces/personal/skills");
    await page.getByRole("link", { name: /^(Skapa skill|Create skill)$/i }).click();
    const name = page.getByRole("textbox", { name: /^(Namn|Name)$/ });
    await name.fill(uniqueName("Unsaved Skill"));
    const draft = await name.inputValue();
    const unloading = page.waitForEvent("dialog");
    const reload = page.reload().catch(() => null);
    const warning = await unloading;
    expect(warning.type()).toBe("beforeunload");
    await warning.dismiss();
    await reload;
    await expect(name).toHaveValue(draft);
    await page.evaluate(() => window.history.back());
    const dialog = page.getByRole("alertdialog", { name: "Lämna sidan?" });
    const cancel = dialog.getByRole("button", { name: "Avbryt", exact: true });
    await expect(dialog).toBeVisible();
    await expect(cancel).toBeFocused();
    await cancel.click();
    await expect(dialog).not.toBeVisible();
    await expect(page).toHaveURL(/\/skills\/new$/);
    await expect(name).toHaveValue(draft);

    const catalogue = page.getByRole("main").getByRole("link", { name: "Skills", exact: true });
    await catalogue.focus();
    await catalogue.press("Enter");
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(catalogue).toBeFocused();
    await expect(name).toHaveValue(draft);
    await catalogue.click();
    await dialog.getByRole("button", { name: "Lämna utan att spara", exact: true }).click();
    await expect(page).toHaveURL(/\/spaces\/personal\/skills$/);
    await expect(dialog).not.toBeVisible();
  });

  test("chat document edits survive save failure and cancelled navigation, then save and leave", async ({
    page
  }) => {
    const file = {
      id: "11111111-1111-4111-8111-111111111111",
      name: "Navigation.md",
      mimetype: "text/markdown",
      size: 24
    };
    // The mock model has no document tool. Add only its generated-file metadata;
    // the conversation and session still come from the backend's real stream.
    await page.route(isChatStream, async (route) => {
      const response = await route.fetch();
      const events = (await response.text()).split(/\r?\n\r?\n/).filter((event) => event.trim());
      const finish = events.findIndex((event) => /"type":\s*"finish"/.test(event));
      expect(finish).toBeGreaterThanOrEqual(0);
      events.splice(
        finish,
        0,
        `data: ${JSON.stringify({ type: "message-metadata", messageMetadata: { generatedFiles: [file] } })}`
      );
      await route.fulfill({
        response,
        headers: { "content-type": "text/event-stream", "x-vercel-ai-ui-message-stream": "v1" },
        body: events.map((event) => `${event}\n\n`).join("")
      });
    });
    const original = `/api/v1/files/${file.id}/original/download/?token=fixture`;
    await page.route(`**/api/v1/files/${file.id}/original/signed-url/`, (route) =>
      route.fulfill({ json: { url: new URL(original, page.url()).href } })
    );
    await page.route(`**/api/v1/files/${file.id}/original/download/**`, (route) =>
      route.fulfill({ contentType: "text/markdown", body: "# Navigation\n\nOriginal.\n" })
    );
    let refuseSave = true;
    await page.route(`**/api/v1/conversations/*/documents/${file.id}/versions/`, (route) => {
      expect(route.request().postDataJSON()).toEqual({ content: "Changed document.\n" });
      return route.fulfill(
        refuseSave
          ? { status: 503, json: { message: "Unavailable" } }
          : {
              json: {
                ...file,
                id: "22222222-2222-4222-8222-222222222222",
                revises_file_id: file.id
              }
            }
      );
    });
    await page.goto("/spaces/personal/chat");
    await askChatQuestion(page, uniqueName("Document navigation"));
    await expect(page.getByRole("log").getByText(MOCK_REPLY)).toBeVisible();
    await page.getByRole("button", { name: "Förhandsgranska Navigation.md", exact: true }).click();
    const editor = page.locator('.tiptap[contenteditable="true"]');
    await expect(editor).toBeVisible();
    await editor.fill("Changed document.");
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await expect(
      page.getByText("Ändringarna kunde inte sparas. Försök igen.", { exact: true })
    ).toBeVisible();
    const dashboard = page.getByRole("link", { name: "Assistenter", exact: true });
    await dashboard.click();
    const dialog = page.getByRole("alertdialog", { name: "Lämna sidan?" });
    await dialog.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(editor).toHaveText("Changed document.");
    refuseSave = false;
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await expect(page.getByRole("button", { name: "Spara", exact: true })).not.toBeVisible();
    await dashboard.click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(dialog).not.toBeVisible();
  });
});

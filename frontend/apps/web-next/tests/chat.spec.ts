import { expect, test } from "./csp";
import { askChatQuestion, conversationLog, MOCK_REPLY, uniqueName } from "./helpers";

test(
  "personal chat streams, reloads and returns focus after deleting the saved session",
  { tag: "@vite" },
  async ({ page }) => {
    const question = uniqueName("e2e chat round-trip");

    await page.goto("/spaces/personal/chat");
    await askChatQuestion(page, question);

    // Scoped to the message list: the header shows the conversation title, which
    // can repeat the question or the mock answer once the title is generated.
    const log = conversationLog(page);
    await expect(log.getByText(question, { exact: true })).toBeVisible();
    await expect(log.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });

    const sessionId = new URL(page.url()).searchParams.get("session_id");
    expect(sessionId).toBeTruthy();

    await page.reload();
    await expect(log.getByText(question, { exact: true })).toBeVisible();
    await expect(log.getByText(MOCK_REPLY)).toBeVisible();

    const more = page
      .getByRole("button", { name: "Fler alternativ", exact: true })
      .filter({ visible: true });
    await more.click();
    await page.getByRole("menuitem", { name: "Ta bort konversationen", exact: true }).click();
    const dialog = page.getByRole("alertdialog", { name: "Ta bort konversationen", exact: true });
    await dialog.getByRole("button", { name: "Bekräfta borttagning", exact: true }).click();
    await expect(log).not.toBeVisible();
    await expect(more).toBeFocused();
  }
);

test(
  "dashboard chat streams and reloads its saved path session",
  { tag: "@vite" },
  async ({ page }) => {
    await page.goto("/dashboard");
    const personal = await page.request.get("/api/eneo/api/v1/spaces/type/personal/");
    expect(personal.ok()).toBe(true);
    const {
      default_assistant: { id }
    } = (await personal.json()) as { default_assistant: { id: string } };
    await page.goto(`/dashboard/${id}`);
    const question = uniqueName("e2e dashboard chat");
    await askChatQuestion(page, question);
    const log = conversationLog(page);
    await expect(log.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
    await expect.poll(() => new URL(page.url()).pathname.split("/").length).toBe(4);
    const savedPath = new URL(page.url()).pathname;
    expect(savedPath.startsWith(`/dashboard/${id}/`)).toBe(true);
    await page.reload();
    await expect(log.getByText(question, { exact: true })).toBeVisible();
    await expect(log.getByText(MOCK_REPLY)).toBeVisible();
    expect(new URL(page.url()).pathname).toBe(savedPath);
  }
);

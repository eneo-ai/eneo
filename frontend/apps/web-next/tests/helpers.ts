import { expect, type Page } from "@playwright/test";

export const MOCK_REPLY = process.env.MOCK_REPLY ?? "E2E mock completion: pong";

let counter = 0;

export function uniqueName(prefix: string) {
  counter += 1;
  return `${prefix} ${Date.now()} ${counter}`;
}

/** The chat composer's text field ("Meddelande till <assistent>"), in either layout. */
export function chatComposer(page: Page) {
  return page.getByRole("textbox", { name: /^(Meddelande till|Message to) / });
}

export async function askChatQuestion(page: Page, question: string) {
  await chatComposer(page).fill(question);
  await page.getByRole("button", { name: /skicka meddelande|send message/i }).click();
}

/** The chat's message list (a named log); appears once the first question is sent. */
export function conversationLog(page: Page) {
  return page.getByRole("log", { name: /konversation|conversation/i });
}

export async function expectOkUrl(page: Page, pattern: RegExp) {
  await expect(page).toHaveURL(pattern, { timeout: 15_000 });
}

/** Creates a shared space through the UI and returns its base path (`/spaces/<id>`). */
export async function createSpace(page: Page, name: string): Promise<string> {
  await page.goto("/spaces/list");
  // Scope to the page and the dialog: the SideNav has its own "Skapa yta".
  await page
    .getByRole("main")
    .getByRole("button", { name: /skapa yta|create space/i })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/namn|name/i).fill(name);
  await dialog.getByRole("button", { name: /skapa yta|create space/i }).click();
  await page.waitForURL(/\/spaces\/[^/]+\/overview$/, { timeout: 15_000 });
  return new URL(page.url()).pathname.replace(/\/overview$/, "");
}

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { ConversationSparse, Paginated, Space } from "@eneo/eneo-js";
import { askChatQuestion, backendFetch, expectOk, MOCK_REPLY, uniqueName } from "./helpers";

// Central flow #4: the core product loop. A logged-in user sends a message in the
// personal chat and gets the assistant's streamed answer. The seeded model points
// at the deterministic mock server, so the reply is always the same fixed string —
// this exercises the full chain (UI → conversations SSE → litellm → model) without
// touching a real provider.
test("a streamed answer is saved and can be reopened from history", async ({ page }) => {
  await page.goto("/spaces/personal/chat");

  const question = uniqueName("e2e persistence ping");
  await askChatQuestion(page, question);

  // Scope to the conversation: once the session exists the service reloads the
  // history list, whose (hidden) table also contains the question text.
  const conversation = page.locator("#session-message-container");
  await expect(conversation.getByText(question, { exact: true })).toBeVisible();
  await expect(conversation.getByText("E2E mock completion: pong")).toBeVisible({
    timeout: 20_000
  });

  await page.getByRole("tablist").getByRole("tab").nth(1).click();

  const savedConversation = page.getByRole("button", { name: question }).first();
  await expect(savedConversation).toBeVisible({ timeout: 15_000 });
  await savedConversation.click();

  await expect(conversation.getByText(question, { exact: true })).toBeVisible();
  await expect(conversation.getByText("E2E mock completion: pong")).toBeVisible();

  const sessionId = new URL(page.url()).searchParams.get("session_id");
  expect(sessionId).toBeTruthy();

  // The loader settles the conversation on the server before rendering.
  // Check the saved exchange in the document, then in the hydrated UI below.
  const restoredPage = await page.reload();
  if (!restoredPage) throw new Error("Reload did not return a document response");
  expect(restoredPage.status()).toBe(200);
  const html = await restoredPage.text();
  expect(html).toContain(question);
  expect(html).toContain(MOCK_REPLY);
  await expect(page).toHaveURL((url) => url.searchParams.get("session_id") === sessionId);

  await expect(conversation.getByText(question, { exact: true })).toBeVisible();
  await expect(conversation.getByText("E2E mock completion: pong")).toBeVisible();
});

async function savedConversation(
  page: Page,
  request: APIRequestContext,
  assistantId: string,
  name: string
): Promise<ConversationSparse> {
  const response = await backendFetch(
    page,
    request,
    `/api/v1/conversations/?assistant_id=${assistantId}&limit=50`
  );
  await expectOk(response, "List saved conversations");
  const history: Paginated<ConversationSparse> = await response.json();
  const saved = history.items.find((conversation) => conversation.name === name);
  if (!saved?.id) throw new Error(`Conversation was not persisted: ${name}`);
  return saved;
}

for (const route of ["space", "dashboard"] as const) {
  test(`a deleted ${route} conversation link recovers into a reloadable new chat`, async ({
    page,
    request,
    browser
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto("/spaces/personal/chat");
    const spaceResponse = await backendFetch(page, request, "/api/v1/spaces/type/personal/");
    await expectOk(spaceResponse, "Load personal space");
    const space: Space = await spaceResponse.json();
    if (!space.default_assistant) throw new Error("The test user has no personal assistant");
    const assistantId = space.default_assistant.id;
    const href = (id: string) =>
      route === "space"
        ? `/spaces/personal/chat?session_id=${id}`
        : `/dashboard/${assistantId}/${id}`;

    const originalQuestion = uniqueName("e2e deleted conversation");
    await askChatQuestion(page, originalQuestion);
    await expect(page.locator("#session-message-container").getByText(MOCK_REPLY)).toBeVisible({
      timeout: 20_000
    });
    const original = await savedConversation(page, request, assistantId, originalQuestion);
    const deletion = await backendFetch(page, request, `/api/v1/conversations/${original.id}/`, {
      method: "DELETE"
    });
    await expectOk(deletion, "Delete the test conversation");
    const missing = await backendFetch(page, request, `/api/v1/conversations/${original.id}/`);
    expect(missing.status()).toBe(404);

    const staleResponse = await page.goto(href(original.id));
    expect(staleResponse?.status()).toBe(200);
    const notice = page.getByRole("status").filter({
      hasText: /This conversation could not be found|Konversationen kunde inte hittas/
    });
    await expect(notice).toBeVisible();
    await expect(page.locator("#session-message-container")).toHaveCount(0);

    const replacementQuestion = uniqueName("e2e recovered conversation");
    await askChatQuestion(page, replacementQuestion);
    const conversation = page.locator("#session-message-container");
    await expect(conversation.getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
    await expect(notice).toHaveCount(0);
    const replacement = await savedConversation(page, request, assistantId, replacementQuestion);
    expect(replacement.id).not.toBe(original.id);
    await expect(page).toHaveURL((url) =>
      route === "space"
        ? url.searchParams.get("session_id") === replacement.id
        : url.pathname.endsWith(`/${replacement.id}`)
    );

    await page.reload();
    await expect(conversation.getByText(replacementQuestion, { exact: true })).toBeVisible();
    await expect(conversation.getByText(MOCK_REPLY)).toBeVisible();
    await expect(notice).toHaveCount(0);

    // A stale link must leave the shared frontend usable by another browser session.
    const otherContext = await browser.newContext({
      storageState: await page.context().storageState()
    });
    try {
      const otherPage = await otherContext.newPage();
      otherPage.on("pageerror", (error) => pageErrors.push(error.message));
      const response = await otherPage.goto(new URL(href(replacement.id), page.url()).href);
      expect(response?.status()).toBe(200);
      expect(await response!.text()).toContain(replacementQuestion);
      await expect(otherPage.getByText(replacementQuestion, { exact: true }).first()).toBeVisible();
    } finally {
      await otherContext.close();
    }

    await page
      .getByRole("button", { name: /^(Ny konversation|New conversation|Ny chatt|New chat)$/i })
      .click();
    await expect(page).toHaveURL((url) =>
      route === "space"
        ? !url.searchParams.has("session_id")
        : url.pathname.endsWith(`/dashboard/${assistantId}`)
    );
    await page.reload();
    await expect(page.locator("#session-message-container")).toHaveCount(0);
    await expect(notice).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });
}

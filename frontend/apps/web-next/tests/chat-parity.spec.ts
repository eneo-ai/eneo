import type { Page, Route } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPath, conversationLog, isChatStream, sessionResponseHeaders } from "./helpers";

// Real cookie authentication and FastAPI/CSP; the response fixtures below isolate
// route guards, token rejection and saved-message presentation from providers.
const SESSION = "11111111-1111-4111-8111-111111111111";
async function personal(page: Page) {
  const response = await page.request.get(apiPath("/spaces/type/personal/"));
  expect(response.ok()).toBe(true);
  const space: Schema<"SpacePublic"> = await response.json();
  if (!space.default_assistant) throw new Error("The native fixture needs a personal assistant");
  return { space, assistant: space.default_assistant };
}
const reply = (route: Route, json: unknown) =>
  route.fulfill({
    status: 200,
    headers: sessionResponseHeaders(route),
    json
  });

test(
  "loaded denial and helper identities stop private chat queries",
  { tag: "@vite" },
  async ({ page }) => {
    const { space, assistant } = await personal(page);
    const privateRequests: string[] = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (
        path === "/api/v1/conversations/" ||
        path.includes(`/conversations/${SESSION}/`) ||
        path.endsWith("/skills/configuration/")
      )
        privateRequests.push(path);
    });
    await page.route("**/api/v1/spaces/type/personal/", (route) =>
      reply(route, {
        ...space,
        default_assistant: { ...assistant, permissions: [] }
      })
    );
    await page.goto(`/spaces/personal/chat?session_id=${SESSION}`);
    await expect(
      page.getByRole("heading", { name: "Du har inte åtkomst till den personliga chatten" })
    ).toBeVisible();
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toHaveCount(0);
    expect(privateRequests).toEqual([]);
    await page.route(`**/api/v1/assistants/${assistant.id}/`, (route) =>
      reply(route, {
        ...assistant,
        is_help_assistant: true
      })
    );
    for (const href of [
      `/dashboard/${assistant.id}/${SESSION}`,
      `/spaces/personal/chat?type=assistant&id=${assistant.id}&session_id=${SESSION}`
    ]) {
      await page.goto(href);
      await expect(page.getByRole("heading", { name: "Sidan hittades inte" })).toBeVisible();
      expect(privateRequests).toEqual([]);
    }
  }
);

test(
  "insight permission and submitted Markdown follow the loaded assistant",
  { tag: "@vite" },
  async ({ page }) => {
    const { assistant } = await personal(page);
    let allowed = false;
    let insightReads = 0;
    await page.route(`**/api/v1/assistants/${assistant.id}/`, (route) =>
      reply(route, {
        ...assistant,
        insight_enabled: true,
        permissions: allowed ? ["read", "insight_view"] : ["read"]
      })
    );
    await page.route("**/api/v1/analysis/conversation-insights/**", (route) => {
      insightReads++;
      return reply(
        route,
        route.request().method() === "POST"
          ? { answer: "## Resultat\n\n**LOU** gäller. [Osäker](javascript:alert(1))" }
          : { total_conversations: 12, total_questions: 30, feedback: { positive: 7, negative: 2 } }
      );
    });
    await page.goto(`/dashboard/${assistant.id}?tab=insights`);
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toBeVisible();
    await expect(page.getByRole("radio", { name: "Insikter", exact: true })).toHaveCount(0);
    expect(insightReads).toBe(0);
    allowed = true;
    await page.reload();
    await expect(page.getByText("Totala konversationer", { exact: true })).toBeVisible();
    const input = page.getByRole("textbox", { name: /Fråga om insikter/ });
    await input.fill("Vilka regler gäller?");
    await page.getByRole("button", { name: "Generera insikter", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Resultat", exact: true })).toBeVisible();
    await input.fill("Nästa fråga");
    await expect(page.getByText("Vilka regler gäller?", { exact: true })).toBeVisible();
    await expect(page.locator('[data-streamdown="strong"]')).toHaveText("LOU");
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  }
);

test(
  "baseline and real context-error counts preserve the draft and use the conversation owner",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    await page.route("**/api/v1/conversations/preflight", (route) =>
      reply(route, {
        input_tokens: 0,
        file_tokens: 0,
        excluded_file_count: 0,
        model_name: "Fixture",
        context_window: 10000,
        context_reserve_tokens: 1000,
        prompt_tokens: 500,
        skill_context_tokens: 200,
        assistant_attachment_tokens: 300
      })
    );
    await page.route(isChatStream, (route) =>
      route.fulfill({
        status: 200,
        headers: {
          ...sessionResponseHeaders(route),
          "content-type": "text/event-stream",
          "x-vercel-ai-ui-message-stream": "v1"
        },
        body:
          [
            { type: "start", messageId: "context-answer" },
            {
              type: "data-session",
              data: {
                session_id: SESSION,
                completion_model: null,
                files: [],
                web_search_references: []
              }
            },
            { type: "data-error", data: { code: 9003 } },
            { type: "error", errorText: "12,000 tokens used, limit is 10,000 tokens" }
          ]
            .map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`)
            .join("") + "data: [DONE]\n\n"
      })
    );
    await page.goto("/spaces/personal/chat");
    const meter = page.getByRole("button", { name: /^Kontextanvändning:/ });
    await expect(meter).toContainText(/800 \/ 10.000/);
    await meter.click();
    const details = page.getByRole("dialog", { name: "Beräknad kontextanvändning" });
    await expect(details.getByText("Varav skillkontext", { exact: true })).toBeVisible();
    await expect(details.getByText("200", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("chat-baseline.png") });
    await page.keyboard.press("Escape");
    const composer = page.getByRole("textbox", { name: /^Fråga / });
    await composer.fill("Behåll min fråga");
    await composer.press("Control+Enter");
    const error = conversationLog(page).getByText(
      "Din input är för stor för denna modell. Prova ett kortare meddelande, färre bilagor, eller en modell med större kontextfönster.",
      { exact: true }
    );
    await expect(error).toBeVisible();
    await expect(composer).toHaveValue("Behåll min fråga");
    await expect(page.getByText(/12.000 \/ 10.000 tokens \(2.000 över gränsen\)/)).toBeVisible();
    await page
      .getByRole("log", { name: "Konversation", exact: true })
      .getByRole("button", { name: "Ny konversation", exact: true })
      .click();
    const confirmation = page.getByRole("alertdialog", { name: "Lämna chatten?", exact: true });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole("button", { name: "Lämna chatten", exact: true }).click();
    await expect(page.getByRole("textbox", { name: /^Fråga / })).toHaveValue("");
    await expect(page).not.toHaveURL(/session_id=/);
  }
);

test(
  "cursor counts, added-row focus and question upload groups share saved-message identity",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const file = (id: string, name: string) => ({
      id,
      name,
      mimetype: "application/pdf",
      size: 1024
    });
    const first = file("22222222-2222-4222-8222-222222222222", "Policy.pdf");
    const second = file("33333333-3333-4333-8333-333333333333", "Avtal.pdf");
    await page.route(`**/api/v1/conversations/${SESSION}/`, (route) =>
      reply(route, {
        id: SESSION,
        name: "Sparat samtal",
        feedback: null,
        messages: [
          { id: "turn1", question: "Första frågan", answer: "Första svaret", files: [first] },
          { id: "turn2", question: "Utan filer", answer: "Andra svaret", files: [] },
          {
            id: "turn3",
            question: "Tredje frågan",
            answer: "Tredje svaret",
            files: [first, second]
          }
        ]
      })
    );
    await page.route(
      (url) => url.pathname === "/api/v1/conversations/",
      (route) => {
        const older = new URL(route.request().url()).searchParams.has("cursor");
        return reply(route, {
          items: older
            ? [{ id: "older", name: "Äldre samtal" }]
            : [
                { id: SESSION, name: "Sparat samtal" },
                { id: "next", name: "Annat samtal" }
              ],
          total_count: 3,
          next_cursor: older ? null : "older"
        });
      }
    );
    await page.goto(`/spaces/personal/chat?session_id=${SESSION}`);
    await expect(page.getByRole("log").getByText("Tredje svaret", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /^Konversationer med / }).click();
    await expect(page.getByText("Laddade 2/3 konversationer", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Visa fler konversationer", exact: true }).click();
    await expect(page.getByText("Laddade 3/3 konversationer", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Äldre samtal", exact: true })).toBeFocused();
    await page
      .getByRole("button", { name: "Visa sidopanelen med filer och vyer", exact: true })
      .click();
    const firstGroup = page.getByRole("region", { name: "Fråga 1", exact: true });
    const thirdGroup = page.getByRole("region", { name: "Fråga 3", exact: true });
    await expect(
      firstGroup.getByRole("button", { name: "Förhandsgranska Policy.pdf", exact: true })
    ).toBeVisible();
    await expect(
      thirdGroup.getByRole("button", { name: "Förhandsgranska Avtal.pdf", exact: true })
    ).toBeVisible();
    await expect(
      thirdGroup.getByRole("button", { name: "Förhandsgranska Policy.pdf", exact: true })
    ).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("chat-upload-groups.png") });
  }
);

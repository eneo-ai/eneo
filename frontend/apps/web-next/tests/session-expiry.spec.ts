import { expect, test } from "./csp";
import { openRoute } from "./responsive-fixtures";
import {
  askChatQuestion,
  chatComposer,
  conversationLog,
  E2E_CREDENTIALS,
  MOCK_REPLY,
  shortenSession
} from "./helpers";

test.skip(!process.env.E2E_BASE_URL, "Requires the FastAPI-served Vite build");

// ACCESSIBILITY.md rule 15: two minutes before the session ends a dialog
// offers to stay signed in; at the end the page stays and sign-in returns to it.
// The page clock reaches those moments; the session is ten minutes long. A test
// that renews or replaces its session signs in one of its own (ownSession), so
// the suite's shared session is never touched.
const SESSION = { left: 600, lifetime: 600 };
const TO_WARNING = "08:01";
const TO_END = "10:01";
const WARNING = /^(Din session går snart ut|Your session is about to end)$/;
const STAY = /^(Fortsätt vara inloggad|Stay signed in)$/;
const EXTEND = "/api/v1/auth/session/extend/";

test(
  "stays signed in from the warning without leaving the page or its draft",
  { tag: "@vite" },
  async ({ page, ownSession }) => {
    await page.clock.install();
    await shortenSession(page, SESSION);
    await page.goto("/spaces/personal/chat");
    await chatComposer(page).fill("Ett utkast som ska vara kvar");

    const dialog = page.getByRole("dialog", { name: WARNING });
    await expect(dialog).toBeHidden();
    await page.clock.fastForward(TO_WARNING);
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByRole("button", { name: STAY })).toBeFocused();

    const [before] = await ownSession.cookies();
    const renewal = page.waitForResponse((response) => response.url().endsWith(EXTEND));
    // Esc keeps the session, as the button does.
    await page.keyboard.press("Escape");
    const response = await renewal;
    expect(response.status()).toBe(200);
    const { generation } = (await response.json()) as { generation: string };
    expect(JSON.stringify(await response.json())).not.toMatch(/eyJ/);
    // The same session, with a new token in the cookie.
    expect(generation).toBe(response.request().headers()["eneo-session-generation"]);
    expect((await ownSession.cookies())[0]!.value).not.toBe(before!.value);

    await expect(dialog).toBeHidden();
    await expect(chatComposer(page)).toBeFocused();
    await expect(chatComposer(page)).toHaveValue("Ett utkast som ska vara kvar");

    // The page speaks for the renewed session under the generation it had.
    const next = page.waitForRequest(
      (request) => request.url().includes("/api/") && request.method() === "POST"
    );
    await askChatQuestion(page, "Efter förlängningen");
    expect((await next).headers()["eneo-session-generation"]).toBe(generation);
    await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
    expect(new URL(page.url()).pathname).toBe("/spaces/personal/chat");
  }
);

test(
  "a renewal whose answer the page never read leaves it working",
  { tag: "@vite" },
  async ({ page, context, ownSession }) => {
    const probe = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/auth/session/") && response.request().method() === "GET"
    );
    await page.goto("/spaces/personal/chat");
    const generation = (await probe).headers()["eneo-session-generation"]!;
    const [before] = await ownSession.cookies();

    // The server renews the session and swaps the cookie; the answer never reaches the page.
    const renewed = await context.request.post(EXTEND, {
      headers: { "Sec-Fetch-Site": "same-origin", "Eneo-Session-Generation": generation }
    });
    expect(renewed.status()).toBe(200);
    expect((await ownSession.cookies())[0]!.value).not.toBe(before!.value);

    // The page's next request names its session, which the new cookie still is.
    const next = page.waitForRequest(
      (request) => request.url().includes("/api/") && request.method() === "POST"
    );
    await askChatQuestion(page, "Efter ett svar som aldrig kom");
    expect((await next).headers()["eneo-session-generation"]).toBe(generation);
    await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
    expect(new URL(page.url()).pathname).toBe("/spaces/personal/chat");
  }
);

test(
  "another open tab follows the renewal instead of signing in again",
  { tag: "@vite" },
  async ({ page, context, ownSession }) => {
    await context.clock.install();
    await shortenSession(context, SESSION);
    const other = await context.newPage();
    // A page from context.newPage() is not the fixture's: its goto returns before the app
    // has checked the session. Moving the clock first would let that check, answered after
    // the jump, start the tab's session ten minutes later than the other's. Each tab opens
    // the way every route in the suite does: the second tab boots the whole app cold, which
    // on a loaded runner takes longer than a single expect waits.
    for (const tab of [page, other]) {
      await openRoute(tab, "/spaces/personal/chat", true);
      await expect(chatComposer(tab)).toBeVisible();
    }
    const renewals: string[] = [];
    other.on("request", (request) => {
      if (request.url().endsWith(EXTEND)) renewals.push(request.url());
    });
    // Before the clock moves: coming back to a tab checks the session again.
    await page.bringToFront();
    const [before] = await ownSession.cookies();

    await context.clock.fastForward(TO_WARNING);
    await expect(other.getByRole("dialog", { name: WARNING })).toBeVisible({ timeout: 15_000 });
    await page.getByRole("dialog", { name: WARNING }).getByRole("button", { name: STAY }).click();

    await expect(page.getByRole("dialog", { name: WARNING })).toBeHidden();
    await expect(other.getByRole("dialog", { name: WARNING })).toBeHidden();
    expect(renewals).toEqual([]);
    // Its next request names the same session, now with the renewed cookie.
    expect((await ownSession.cookies())[0]!.value).not.toBe(before!.value);
    await askChatQuestion(other, "Från den andra fliken");
    await expect(conversationLog(other).getByText(MOCK_REPLY)).toBeVisible({ timeout: 20_000 });
    expect(new URL(other.url()).pathname).toBe("/spaces/personal/chat");
  }
);

test(
  "at the end the page stays, and signing in again returns to it with the draft",
  { tag: "@vite" },
  async ({ page }) => {
    await page.clock.install();
    await shortenSession(page, SESSION);
    await page.goto("/spaces/personal/chat");
    await chatComposer(page).fill("Utkast före utloggning");
    // Writing the draft waits for typing to pause.
    await page.waitForTimeout(600);
    await page.clock.fastForward(TO_END);

    const expired = page.getByRole("dialog", {
      name: /^(Din session har gått ut|Your session has expired)$/
    });
    await expect(expired).toBeVisible({ timeout: 15_000 });
    await expired.getByRole("button", { name: /^(Logga in igen|Login again)$/ }).click();

    // The cookie still works here, so sign-in sends the browser straight back.
    await page.waitForURL((url) => url.pathname === "/spaces/personal/chat");
    await expect(chatComposer(page)).toHaveValue("Utkast före utloggning");
  }
);

test(
  "a session the server has ended keeps the draft through a real sign-in",
  { tag: "@vite" },
  async ({ page, context, ownSession }) => {
    const resume = "/spaces/personal/chat";
    await page.goto(resume);
    await chatComposer(page).fill("Utkast när sessionen tar slut");
    // Writing the draft waits for typing to pause.
    await page.waitForTimeout(600);

    // The server no longer knows this browser: the cookie is gone.
    await context.clearCookies({ name: /^(eneo_web|__Host-eneo_web)$/ });
    // Coming back to the tab checks the session, which the server refuses.
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await page.waitForURL((url) => url.pathname === "/login");
    expect(new URL(page.url()).searchParams.get("next")).toBe(resume);

    await page.locator('input[name="email"]').fill(E2E_CREDENTIALS.username);
    await page.locator('input[name="password"]').fill(E2E_CREDENTIALS.password);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL((url) => url.pathname === resume);
    await expect(chatComposer(page)).toHaveValue("Utkast när sessionen tar slut");
    expect(await ownSession.cookies()).toHaveLength(1);
  }
);

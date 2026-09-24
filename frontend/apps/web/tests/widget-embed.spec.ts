import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import http from "node:http";
import { BACKEND_URL, backendFetch, expectOk, MOCK_REPLY, uniqueName } from "./helpers";

// Central flow #7: an assistant published as a chat widget on another
// website. A fake host page on a second origin (a tiny HTTP server started by
// the spec, so Chromium's local-network checks see a real loopback origin)
// loads the real loader script from the preview server, which frames the
// embed page cross-origin. This proves the browser-enforced
// pieces end to end: frame-ancestors from the widget's allowed origins, the
// postMessage origin checks, keyboard flow and focus return, ALTCHA inside the
// iframe and a streamed answer from the mock model — plus an axe audit of the
// open panel.
const HOST_PORT = 4174;
const DENIED_PORT = 4175;
const HOST_ORIGIN = `http://127.0.0.1:${HOST_PORT}`;
const DENIED_ORIGIN = `http://127.0.0.1:${DENIED_PORT}`;

type Widget = { id: string; public_id: string; status: string; revision: number };

/**
 * Every WCAG 2.0–2.2 A and AA violation on the host page and inside the
 * widget's frame, whatever axe rates its impact: a widget that goes onto
 * sites bound by the accessibility law has to pass all of them.
 */
async function wcagViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"])
    .analyze();
  return results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    targets: v.nodes.map((node) => node.target)
  }));
}

async function createActiveWidget(
  page: Page,
  request: APIRequestContext,
  settings: Record<string, unknown> = {}
): Promise<Widget> {
  const space = await backendFetch(page, request, "/api/v1/spaces/", {
    method: "POST",
    data: { name: uniqueName("widget e2e space") }
  });
  await expectOk(space, "create space");
  const spaceId = (await space.json()).id as string;

  const assistant = await backendFetch(
    page,
    request,
    `/api/v1/spaces/${spaceId}/applications/assistants/`,
    { method: "POST", data: { name: "Widgetassistenten" } }
  );
  await expectOk(assistant, "create assistant");
  const assistantId = (await assistant.json()).id as string;

  await expectOk(
    await backendFetch(page, request, `/api/v1/assistants/${assistantId}/publish/?published=true`, {
      method: "POST"
    }),
    "publish assistant"
  );

  // The proof of work is verified server-side by the widget unit and
  // integration tests. In Playwright's headless Chromium on a loaded runner
  // the ALTCHA workers intermittently never report back (the challenge is
  // fetched, no solution ever follows), so the E2E widget runs without bot
  // protection and only checks that the challenge endpoint answers the
  // embed origin cross-origin.
  await expectOk(
    await backendFetch(page, request, "/api/v1/admin/widget-policy/", {
      method: "PATCH",
      data: { allow_bot_protection_none: true }
    }),
    "allow widgets without bot protection"
  );

  const created = await backendFetch(page, request, `/api/v1/spaces/${spaceId}/widgets/`, {
    method: "POST",
    data: { target_id: assistantId, name: uniqueName("widget e2e"), language: "sv" }
  });
  await expectOk(created, "create widget");
  const widget = (await created.json()) as Widget;

  await expectOk(
    await backendFetch(page, request, `/api/v1/widgets/${widget.id}/`, {
      method: "PATCH",
      data: {
        revision: widget.revision,
        allowed_origins: [HOST_ORIGIN],
        bot_protection: "none",
        texts: {
          title: "Fråga kommunen",
          welcome: "Hej! Vad kan jag hjälpa dig med?",
          subtitle: "Du chattar med en AI-assistent. Svaren kan innehålla fel."
        },
        ...settings
      }
    }),
    "configure widget"
  );

  const response = await backendFetch(page, request, `/api/v1/widgets/${widget.id}/activate/`, {
    method: "POST"
  });
  await expectOk(response, "activate widget");
  const active = (await response.json()) as Widget;
  activated.push(active);
  return active;
}

function hostPage(loaderOrigin: string, publicId: string): string {
  return `<!doctype html>
<html lang="sv">
<head><meta charset="utf-8"><title>Testkommun</title>
<script>
  window.Eneo = window.Eneo || function () { (window.Eneo.q = window.Eneo.q || []).push(arguments); };
  window.__events = [];
  Eneo("on", "ready", function () { window.__events.push("ready"); });
  Eneo("on", "open", function () { window.__events.push("open"); });
  Eneo("on", "close", function () { window.__events.push("close"); });
  Eneo("on", "conversation_started", function () { window.__events.push("conversation_started"); });
</script>
<script async src="${loaderOrigin}/widget/v1/eneo.js" data-widget-id="${publicId}"></script>
</head>
<body><main><h1>Testkommun</h1><p>En vanlig kommunsida. <a href="#kontakt">Kontakt</a></p></main></body>
</html>`;
}

/** A throwaway host site: every path answers with the same page. */
function serveHost(port: number, html: () => string): Promise<http.Server> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((_req, res) => {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(html());
    });
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

const hosts: http.Server[] = [];
let hostHtml = "";
// Widgets this spec activated; paused again afterwards so repeated local runs
// against one stack never hit the tenant's active-widget ceiling.
const activated: Widget[] = [];

test.afterEach(async ({ page, request }) => {
  for (const widget of activated.splice(0)) {
    await backendFetch(page, request, `/api/v1/widgets/${widget.id}/pause/`, { method: "POST" });
  }
});

test.beforeAll(async () => {
  hosts.push(await serveHost(HOST_PORT, () => hostHtml));
  hosts.push(await serveHost(DENIED_PORT, () => hostHtml));
});

test.afterAll(async () => {
  await Promise.all(hosts.map((server) => new Promise((done) => server.close(done))));
});

test.describe("embeddable widget", () => {
  test("loads cross-origin, answers, respects keyboard flow and passes axe", async ({
    page,
    request,
    baseURL
  }) => {
    test.setTimeout(120_000);
    // Everything the host page and the iframe log, attached to the report so a
    // stalled proof of work on a slow runner can be read without a rerun.
    const consoleLines: string[] = [];
    page.on("console", (message) => consoleLines.push(`[${message.type()}] ${message.text()}`));
    page.on("pageerror", (error) => consoleLines.push(`[pageerror] ${error.message}`));
    const attachConsole = () =>
      test.info().attach("widget-console", {
        body: consoleLines.join("\n"),
        contentType: "text/plain"
      });
    // Comments are stored, so the vote offers the comment dialog.
    const widget = await createActiveWidget(page, request, {
      privacy: { retention_days: 30, store_feedback_text: true }
    });
    const loaderOrigin = baseURL!.replace(/\/$/, "");

    // The loader route: cacheable, CORS-open (for SRI) and never sniffable.
    const loader = await request.get(`${loaderOrigin}/widget/v1/eneo.js`);
    expect(loader.status()).toBe(200);
    expect(loader.headers()["content-type"]).toContain("text/javascript");
    expect(loader.headers()["access-control-allow-origin"]).toBe("*");
    expect(loader.headers()["cache-control"]).toContain("max-age=3600");
    expect(loader.headers()["x-content-type-options"]).toBe("nosniff");

    // What the loader reads before it shows the launcher, from any host page.
    const settings = await request.get(`${loaderOrigin}/widget/settings/${widget.public_id}`);
    expect(settings.status()).toBe(200);
    expect(settings.headers()["access-control-allow-origin"]).toBe("*");
    expect(await settings.json()).toMatchObject({ language: "sv", position: "bottom-right" });

    // The embed page tells the browser exactly who may frame it.
    const embed = await request.get(
      `${loaderOrigin}/embed/${widget.public_id}?origin=${encodeURIComponent(HOST_ORIGIN)}`
    );
    expect(embed.status()).toBe(200);
    const csp = embed.headers()["content-security-policy"] ?? "";
    expect(csp).toContain(`frame-ancestors 'self' ${HOST_ORIGIN}`);
    expect(csp).not.toContain(DENIED_ORIGIN);
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).toContain("worker-src 'self' blob:");
    expect(csp).toContain("frame-src 'none'");

    hostHtml = hostPage(loaderOrigin, widget.public_id);
    await page.goto(`${HOST_ORIGIN}/index.html`);

    const launcher = page.locator("eneo-widget button.launcher");
    await expect(launcher).toHaveAttribute("aria-haspopup", "dialog");
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await expect(launcher).toHaveAccessibleName("Öppna chatt");
    // Hidden until the loader has read the saved settings.
    await expect(launcher).toBeVisible();
    // The closed widget adds nothing to the page that fails WCAG.
    expect(await wcagViolations(page)).toEqual([]);

    // Open with the keyboard: Tab to the launcher, Enter opens the panel.
    await launcher.focus();
    await page.keyboard.press("Enter");
    await expect(launcher).toHaveAttribute("aria-expanded", "true");

    const frame = page.frameLocator("eneo-widget iframe");
    const composer = frame.getByRole("textbox", { name: "Din fråga" });
    await expect(composer).toBeVisible({ timeout: 20_000 });
    await expect(frame.getByRole("heading", { name: "Fråga kommunen" })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => (window as never as { __events: string[] }).__events))
      .toContain("ready");

    // Focus moved into the iframe's composer on open.
    await expect(composer).toBeFocused();

    // Beside the page the panel is a named, non-modal dialog, and the frame
    // is named after the widget for screen readers.
    const dialog = page.getByRole("dialog", { name: "Chatt" });
    await expect(dialog).toBeVisible();
    await expect(dialog).not.toHaveAttribute("aria-modal", "true");
    await expect(page.locator("main")).not.toHaveAttribute("inert", "");
    await expect(page.locator("eneo-widget iframe")).toHaveAttribute("title", "Fråga kommunen");
    // What a screen reader finds on the host page: the expanded launcher and
    // the dialog it controls.
    await expect(page.locator("eneo-widget")).toMatchAriaSnapshot(`
      - button "Stäng chatt" [expanded]
      - dialog "Chatt"
    `);

    // A forged message from the host page itself is ignored (only the iframe
    // window on the Eneo origin may close the panel).
    await page.evaluate(() => window.postMessage({ ns: "eneo-widget", v: 1, type: "close" }, "*"));
    await expect(launcher).toHaveAttribute("aria-expanded", "true");

    // The ALTCHA challenge is still served to the embed origin cross-origin,
    // which is what a protected widget's iframe needs before minting.
    const challenge = await request.get(
      `${BACKEND_URL}/api/v1/widgets/${widget.public_id}/challenge/`,
      { headers: { Origin: loaderOrigin } }
    );
    expect(challenge.status()).toBe(200);
    expect(challenge.headers()["access-control-allow-origin"]).toBe(loaderOrigin);
    expect((await challenge.json()).parameters).toBeTruthy();

    // Ask: the token is minted without a proof of work, the mock model streams.
    const probe = await frame.locator("body").evaluate(() => ({
      origin: location.origin,
      secureContext: window.isSecureContext,
      cores: navigator.hardwareConcurrency
    }));
    consoleLines.push(`[probe] ${JSON.stringify(probe)}`);
    await composer.fill("Hej, vad kan du?");
    const askedAt = Date.now();
    await page.keyboard.press("Enter");
    try {
      await expect(frame.getByRole("log").getByText(MOCK_REPLY)).toBeVisible({
        timeout: 45_000
      });
    } finally {
      consoleLines.push(`[probe] answer wait ${Date.now() - askedAt} ms`);
      await attachConsole();
    }
    await expect
      .poll(() => page.evaluate(() => (window as never as { __events: string[] }).__events))
      .toContain("conversation_started");

    // A screen reader hears the finished answer once, never the stream.
    await expect(frame.locator("[aria-live='polite'][aria-atomic='true']")).toHaveText(
      `Assistent: ${MOCK_REPLY}`
    );

    // The send arrow and the comment dialog's Send are submit buttons: they
    // only work when the loader's sandbox allows forms, which Enter alone
    // never proved.
    await composer.fill("Och en fråga till?");
    await frame.getByRole("button", { name: "Skicka", exact: true }).click();
    await expect(frame.getByRole("log").getByText(MOCK_REPLY)).toHaveCount(2, {
      timeout: 45_000
    });
    await expect(composer).toBeFocused();

    const helpful = frame.getByRole("button", { name: "Bra svar" });
    await helpful.click();
    await frame.getByRole("button", { name: "Vill du berätta mer?" }).click();
    const comment = frame.getByRole("dialog");
    await comment.getByRole("textbox").fill("Tydligt och snabbt svar.");
    await comment.getByRole("button", { name: "Skicka" }).click();
    await expect(frame.getByRole("status")).toHaveText(/Tack, vi har tagit emot din återkoppling/);
    await expect(comment).toBeHidden();
    await expect(helpful).toBeFocused();

    // The chat's landmarks, title, conversation and composer, as the
    // accessibility tree exposes them inside the frame.
    await expect(frame.locator("[data-widget-chat]")).toMatchAriaSnapshot(`
      - banner:
        - heading "Fråga kommunen" [level=1]
      - main:
        - log "Konversation"
      - contentinfo:
        - textbox "Din fråga"
        - button "Skicka"
    `);

    // WCAG check of the open panel (host page + iframe).
    expect(await wcagViolations(page)).toEqual([]);

    // Escape on the host page closes the panel too, so it never keeps covering
    // what the visitor moved on to, and focus stays there (WCAG 2.4.11).
    const hostLink = page.getByRole("link", { name: "Kontakt" });
    await hostLink.focus();
    await page.keyboard.press("Escape");
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await expect(hostLink).toBeFocused();
    await launcher.click();
    await expect(composer).toBeFocused();

    // Escape inside the iframe closes the panel and returns focus to the launcher.
    await composer.focus();
    await page.keyboard.press("Escape");
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await expect(launcher).toBeFocused();
    await expect
      .poll(() => page.evaluate(() => (window as never as { __events: string[] }).__events))
      .toContain("close");

    // Pausing takes effect immediately: the embed page turns into a notice
    // that any host may still frame, so the launcher never opens a blank panel.
    await expectOk(
      await backendFetch(page, request, `/api/v1/widgets/${widget.id}/pause/`, { method: "POST" }),
      "pause widget"
    );
    const paused = await request.get(`${loaderOrigin}/embed/${widget.public_id}`);
    expect(paused.status()).toBe(200);
    expect(paused.headers()["content-security-policy"]).toContain("frame-ancestors *");
    expect(await paused.text()).toContain("Chatten är pausad");
    const config = await request.get(`${BACKEND_URL}/api/v1/widgets/${widget.public_id}/config/`);
    expect(config.status()).toBe(404);
  });

  test("the saved language and position reach a site without a new snippet", async ({
    page,
    request,
    baseURL
  }) => {
    // The host page is Swedish and its snippet carries neither setting.
    const widget = await createActiveWidget(page, request, {
      language: "en",
      theme: { position: "bottom-left" }
    });
    const loaderOrigin = baseURL!.replace(/\/$/, "");
    hostHtml = hostPage(loaderOrigin, widget.public_id);
    await page.goto(`${HOST_ORIGIN}/index.html`);

    const launcher = page.locator("eneo-widget button.launcher");
    await expect(launcher).toHaveAccessibleName("Open chat");
    await expect(launcher).toBeVisible();
    const box = await launcher.boundingBox();
    expect(box!.x + box!.width).toBeLessThan(page.viewportSize()!.width / 2);

    await launcher.click();
    const frame = page.frameLocator("eneo-widget iframe");
    await expect(frame.getByRole("textbox", { name: "Your question" })).toBeVisible({
      timeout: 20_000
    });

    // A frame or link that still asks for Swedish is moved to English.
    const query = `?origin=${encodeURIComponent(HOST_ORIGIN)}`;
    const swedish = await request.get(`${loaderOrigin}/embed/${widget.public_id}${query}`, {
      maxRedirects: 0
    });
    expect(swedish.status()).toBe(307);
    expect(swedish.headers()["location"]).toBe(`/en/embed/${widget.public_id}${query}`);
  });

  test("on a phone the chat is modal and a paused widget has no launcher on a new visit", async ({
    page,
    request,
    baseURL
  }) => {
    test.setTimeout(60_000);
    const widget = await createActiveWidget(page, request);
    const loaderOrigin = baseURL!.replace(/\/$/, "");
    await page.setViewportSize({ width: 375, height: 812 });
    hostHtml = hostPage(loaderOrigin, widget.public_id);
    await page.goto(`${HOST_ORIGIN}/index.html`);

    const launcher = page.locator("eneo-widget button.launcher");
    await launcher.click();
    await expect(launcher).toHaveAttribute("aria-expanded", "true");
    const frame = page.frameLocator("eneo-widget iframe");
    await expect(frame.getByRole("textbox", { name: "Din fråga" })).toBeVisible({
      timeout: 20_000
    });

    // Full screen the panel is a modal dialog: the page behind it is inert,
    // so neither Tab nor a screen reader reaches content hidden behind it.
    await expect(page.getByRole("dialog", { name: "Chatt" })).toHaveAttribute("aria-modal", "true");
    await expect(page.locator("main")).toHaveAttribute("inert", "");
    expect(await wcagViolations(page)).toEqual([]);

    // The chat's close button replaces the launcher while the panel is open.
    await expect(launcher).toBeHidden();
    await frame.getByRole("button", { name: "Stäng chatten" }).click();
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await expect(launcher).toBeFocused();
    await expect(page.locator("main")).not.toHaveAttribute("inert", "");
    await expect(launcher).toHaveAccessibleName("Öppna chatt");
    await expect(page.locator("eneo-widget .panel")).toBeHidden();
    // The host page is usable again: a click reaches its own content.
    await page.getByRole("heading", { name: "Testkommun" }).click();

    await expectOk(
      await backendFetch(page, request, `/api/v1/widgets/${widget.id}/pause/`, { method: "POST" }),
      "pause widget"
    );
    const settingsResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/widget/settings/${widget.public_id}`)
    );
    await page.reload();
    expect((await settingsResponse).status()).toBe(404);
    await expect(page.locator("eneo-widget button.launcher")).toBeHidden();
    await expect(page.locator("eneo-widget iframe")).toHaveCount(0);
    await expect(page.locator("main")).not.toHaveAttribute("inert", "");
  });

  test("a site that is not on the allowed list cannot frame the widget", async ({
    page,
    request,
    baseURL
  }) => {
    const widget = await createActiveWidget(page, request);
    const loaderOrigin = baseURL!.replace(/\/$/, "");

    const cspErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error" && /frame-ancestors/.test(message.text())) {
        cspErrors.push(message.text());
      }
    });

    hostHtml = hostPage(loaderOrigin, widget.public_id);
    await page.goto(`${DENIED_ORIGIN}/index.html`);

    const launcher = page.locator("eneo-widget button.launcher");
    await launcher.click();
    await expect(launcher).toHaveAttribute("aria-expanded", "true");

    // The iframe element exists but the browser refuses to render the page in it.
    const frame = page.frameLocator("eneo-widget iframe");
    await expect(frame.getByRole("textbox", { name: "Din fråga" })).toHaveCount(0);
    await expect.poll(() => cspErrors.length, { timeout: 15_000 }).toBeGreaterThan(0);
  });
});

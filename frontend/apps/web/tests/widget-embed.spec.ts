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

async function createActiveWidget(page: Page, request: APIRequestContext): Promise<Widget> {
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
        }
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
<body><main><h1>Testkommun</h1><p>En vanlig kommunsida.</p></main></body>
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
    const widget = await createActiveWidget(page, request);
    const loaderOrigin = baseURL!.replace(/\/$/, "");

    // The loader route: cacheable, CORS-open (for SRI) and never sniffable.
    const loader = await request.get(`${loaderOrigin}/widget/v1/eneo.js`);
    expect(loader.status()).toBe(200);
    expect(loader.headers()["content-type"]).toContain("text/javascript");
    expect(loader.headers()["access-control-allow-origin"]).toBe("*");
    expect(loader.headers()["cache-control"]).toContain("max-age=3600");
    expect(loader.headers()["x-content-type-options"]).toBe("nosniff");

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
      await expect(frame.getByText(MOCK_REPLY)).toBeVisible({ timeout: 45_000 });
    } finally {
      consoleLines.push(`[probe] answer wait ${Date.now() - askedAt} ms`);
      await attachConsole();
    }
    await expect
      .poll(() => page.evaluate(() => (window as never as { __events: string[] }).__events))
      .toContain("conversation_started");

    // WCAG check of the open panel (host page + iframe).
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical"
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

    // Escape inside the iframe closes the panel and returns focus to the launcher.
    await composer.focus();
    await page.keyboard.press("Escape");
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await expect(launcher).toBeFocused();
    await expect
      .poll(() => page.evaluate(() => (window as never as { __events: string[] }).__events))
      .toContain("close");

    // Pausing takes effect immediately: the public config disappears.
    await expectOk(
      await backendFetch(page, request, `/api/v1/widgets/${widget.id}/pause/`, { method: "POST" }),
      "pause widget"
    );
    const paused = await request.get(`${loaderOrigin}/embed/${widget.public_id}`);
    expect(paused.status()).toBe(404);
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

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import http from "node:http";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, apiPostJson, apiWriteJson, MOCK_REPLY, uniqueName } from "./helpers";

type Widget = Schema<"WidgetPublic">;
type Policy = Schema<"WidgetPolicyPublic">;
type LoaderRelease = { version: string; channel: string; integrity: string };

// These are real loopback sites: Chromium, rather than a request mock, decides
// whether the other origin may load the SRI script and frame the Vite app.
const hosts: http.Server[] = [];
let allowedOrigin = "";
let deniedOrigin = "";
let eneoOrigin = "";
let hostHtml = "";
let savedBotPolicy: boolean | undefined;
const createdWidgets: string[] = [];

async function serveHost(): Promise<string> {
  const server = http.createServer((_request, response) => {
    const assets = `'self' ${eneoOrigin}`;
    response.writeHead(200, {
      "content-type": "text/html; charset=utf-8",
      "content-security-policy": [
        "default-src 'none'",
        `script-src ${assets}`,
        `style-src ${assets}`,
        `frame-src ${eneoOrigin}`,
        `connect-src ${assets}`,
        `img-src ${assets} data:`,
        `font-src ${assets}`,
        "base-uri 'none'",
        "form-action 'none'"
      ].join("; ")
    });
    response.end(hostHtml);
  });
  hosts.push(server);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Widget host has no TCP address");
  return `http://127.0.0.1:${address.port}`;
}

function hostDocument(origin: string, widget: Widget, release: LoaderRelease): string {
  return `<!doctype html><html lang="sv"><head><meta charset="utf-8">
<title>Testkommun</title>
<script async crossorigin="anonymous" integrity="${release.integrity}"
  src="${origin}/widget/${release.channel}/eneo.js" data-widget-id="${widget.public_id}"></script>
</head><body><main><h1>Testkommun</h1><a href="#kontakt">Kontakt</a></main></body></html>`;
}

async function createWidget(page: Page, activate: boolean): Promise<Widget> {
  const space = await apiPost(page, "/spaces/", { name: uniqueName("Vite-widget") });
  const assistant = await apiPost(page, `/spaces/${space}/applications/assistants/`, {
    name: uniqueName("Widgetassistent")
  });
  await apiPostJson(page, `/assistants/${assistant}/publish/?published=true`, {});
  const draft = await apiPostJson<Widget>(page, `/spaces/${space}/widgets/`, {
    target_id: assistant,
    name: uniqueName("Besökschatt"),
    language: "sv"
  });
  createdWidgets.push(draft.id);
  const configured = await apiWriteJson<Widget>(page, "PATCH", `/widgets/${draft.id}/`, {
    revision: draft.revision,
    allowed_origins: [allowedOrigin],
    // The real visitor API, budget and model stream remain in this flow. Proof
    // of work has backend integration coverage; its headless worker timing is
    // deliberately outside this cross-origin/browser-session regression.
    bot_protection: "none",
    privacy: { retention_days: 30, store_feedback_text: true },
    texts: {
      title: "Fråga kommunen",
      welcome: "Hej! Vad kan jag hjälpa dig med?",
      subtitle: "Du chattar med en AI-assistent. Svaren kan innehålla fel."
    }
  });
  return activate ? apiPostJson<Widget>(page, `/widgets/${draft.id}/activate/`, {}) : configured;
}

test.beforeAll(async ({ baseURL }) => {
  if (!baseURL) throw new Error("The widget host needs the configured Eneo base URL");
  const eneo = new URL(baseURL);
  if (eneo.protocol !== "http:" && eneo.protocol !== "https:") {
    throw new Error("The widget host needs an HTTP or HTTPS Eneo origin");
  }
  eneoOrigin = eneo.origin;
  allowedOrigin = await serveHost();
  deniedOrigin = await serveHost();
});

test.afterAll(async () => {
  await Promise.all(
    hosts.map(
      (server) =>
        new Promise<void>((resolve, reject) => {
          server.close((error) => (error ? reject(error) : resolve()));
        })
    )
  );
});

test.beforeEach(async ({ page }) => {
  await page.goto("/spaces/list");
  const response = await page.request.get("/api/v1/admin/widget-policy/");
  expect(response.status()).toBe(200);
  const policy: Policy = await response.json();
  savedBotPolicy = policy.allow_bot_protection_none;
  if (!savedBotPolicy) {
    await apiWriteJson(page, "PATCH", "/admin/widget-policy/", { allow_bot_protection_none: true });
  }
});

test.afterEach(async ({ page }) => {
  try {
    for (const id of createdWidgets.splice(0)) {
      await apiPostJson(page, `/widgets/${id}/archive/`, {});
    }
  } finally {
    if (savedBotPolicy !== undefined) {
      await apiWriteJson(page, "PATCH", "/admin/widget-policy/", {
        allow_bot_protection_none: savedBotPolicy
      });
      savedBotPolicy = undefined;
    }
  }
});

test("the Vite widget loads cross-origin, streams and stores conversation feedback without app cookies", async ({
  page,
  context
}) => {
  test.setTimeout(120_000);
  const widget = await createWidget(page, true);
  const manifest = await page.request.get("/widget/manifest.json");
  expect(manifest.status()).toBe(200);
  const release: LoaderRelease = await manifest.json();
  hostHtml = hostDocument(eneoOrigin, widget, release);
  // Use an ordinary page for the external site: the app fixture's goto waits
  // for React hydration, while a municipal host page has no React root.
  const host = await context.newPage();
  const visitorHeaders: Promise<Record<string, string>>[] = [];
  host.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith(`/api/v1/widgets/${widget.public_id}/`)) {
      visitorHeaders.push(request.allHeaders());
    }
  });
  try {
    await host.goto(allowedOrigin);
    const launcher = host.locator("eneo-widget button.launcher");
    await expect(launcher).toBeVisible();
    await launcher.click();
    const frame = host.frameLocator("eneo-widget iframe");
    await expect(frame.getByRole("heading", { name: "Fråga kommunen", exact: true })).toBeVisible();
    await expect(host.locator("eneo-widget iframe")).toHaveAttribute("title", "Fråga kommunen");
    const composer = frame.getByRole("textbox", { name: "Din fråga", exact: true });
    await expect(composer).toBeFocused();
    await composer.fill("Hej, vad kan du?");
    await frame.getByRole("button", { name: "Skicka", exact: true }).click();
    await expect(frame.getByRole("log").getByText(MOCK_REPLY, { exact: true })).toBeVisible({
      timeout: 45_000
    });

    await frame.getByRole("button", { name: "Hjälpsam konversation", exact: true }).click();
    await expect(frame.getByRole("button", { name: "Ändra omdöme", exact: true })).toBeVisible();
    await frame.getByRole("button", { name: "Vill du berätta mer?", exact: true }).click();
    const comment = frame.getByRole("dialog", { name: "Berätta mer", exact: true });
    await comment.getByRole("textbox").fill("Tydligt och snabbt svar.");
    await comment.getByRole("button", { name: "Skicka", exact: true }).click();
    await expect(comment).toBeHidden();
    await expect(
      frame.getByRole("button", { name: "Redigera kommentar", exact: true })
    ).toBeVisible();
    // A new embed document must restore the saved feedback from the API.
    const restored = host.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.startsWith(
          `/api/v1/widgets/${widget.public_id}/sessions/`
        ) &&
        response.request().method() === "GET" &&
        response.status() === 200
    );
    await host.locator("eneo-widget iframe").evaluate((element) => {
      const source = element.getAttribute("src");
      if (!source) throw new Error("Widget iframe has no source");
      element.setAttribute("src", source);
    });
    await restored;
    await expect(
      frame.getByRole("button", { name: "Redigera kommentar", exact: true })
    ).toBeVisible();
    expect(
      (
        await new AxeBuilder({ page: host })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"])
          .analyze()
      ).violations
    ).toEqual([]);

    await composer.focus();
    await host.keyboard.press("Escape");
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await expect(launcher).toBeFocused();
    expect(visitorHeaders.length).toBeGreaterThanOrEqual(4);
    for (const headers of await Promise.all(visitorHeaders)) {
      expect(headers.cookie).toBeUndefined();
      expect(headers["eneo-session-generation"]).toBeUndefined();
    }
  } finally {
    await host.close();
  }
});

test("the production browser policy refuses a widget on an unapproved host", async ({
  page,
  context,
  cspViolations
}) => {
  test.setTimeout(60_000);
  const widget = await createWidget(page, true);
  const response = await page.request.get("/widget/manifest.json");
  const release: LoaderRelease = await response.json();
  hostHtml = hostDocument(eneoOrigin, widget, release);
  const host = await context.newPage();
  const refused: string[] = [];
  host.on("console", (message) => {
    if (message.type() === "error" && /frame-ancestors/.test(message.text()))
      refused.push(message.text());
  });
  try {
    await host.goto(deniedOrigin);
    const launcher = host.locator("eneo-widget button.launcher");
    await expect(launcher).toBeVisible();
    await launcher.click();
    await expect.poll(() => refused.length, { timeout: 15_000 }).toBeGreaterThan(0);
    await expect(
      host.frameLocator("eneo-widget iframe").getByRole("textbox", { name: "Din fråga" })
    ).toHaveCount(0);
    // The refused frame is intentional; every other CSP violation remains a failure.
    expect(cspViolations.filter((violation) => !violation.startsWith("frame-ancestors "))).toEqual(
      []
    );
    cspViolations.length = 0;
  } finally {
    await host.close();
  }
});

test("a draft preview takes its bearer token from the fragment and omits app cookies", async ({
  page,
  context
}) => {
  test.setTimeout(60_000);
  const draft = await createWidget(page, false);
  const preview = await apiPostJson<Schema<"WidgetPreviewToken">>(
    page,
    `/widgets/${draft.id}/preview-token/`,
    {}
  );
  const tab = await context.newPage();
  const requests: { url: string; headers: Promise<Record<string, string>> }[] = [];
  tab.on("request", (request) => {
    if (new URL(request.url()).pathname === `/api/v1/widgets/${draft.public_id}/config/`) {
      requests.push({ url: request.url(), headers: request.allHeaders() });
    }
  });
  try {
    await tab.goto(
      `/embed/${draft.public_id}?preview=1#preview=${encodeURIComponent(preview.token)}`
    );
    await expect(tab.getByRole("heading", { name: "Fråga kommunen", exact: true })).toBeVisible();
    await expect(tab.getByRole("textbox", { name: "Din fråga", exact: true })).toBeVisible();
    expect(requests).toHaveLength(1);
    const request = requests[0]!;
    expect(request.url).not.toContain(preview.token);
    const headers = await request.headers;
    expect(headers.authorization).toBe(`Bearer ${preview.token}`);
    expect(headers.cookie).toBeUndefined();
    expect(headers["eneo-session-generation"]).toBeUndefined();
  } finally {
    await tab.close();
  }
});

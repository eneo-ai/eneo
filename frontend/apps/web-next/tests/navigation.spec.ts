import type { Page } from "@playwright/test";
import { expect, test } from "./csp";
import {
  askChatQuestion,
  CHAT_COMPOSER_NAME,
  chatComposer,
  conversationLog,
  createSpace,
  fetchChatStream,
  isChatStream,
  MOCK_REPLY,
  productionAsset,
  sessionResponseHeaders,
  uniqueName
} from "./helpers";

type StreamWindow = Window & {
  navigationStream: { ready: boolean; releaseSession(): void; releaseAnswer(): void };
};

async function gateChatStream(page: Page) {
  // Playwright route.fulfill buffers a whole response. Gate consumption of the
  // real backend's bytes instead, on either side of its data-session event.
  await page.addInitScript(() => {
    const controlled = window as unknown as StreamWindow;
    let releaseSession!: () => void;
    let releaseAnswer!: () => void;
    const session = new Promise<void>((resolve) => (releaseSession = resolve));
    const answer = new Promise<void>((resolve) => (releaseAnswer = resolve));
    controlled.navigationStream = { ready: false, releaseSession, releaseAnswer };
    const fetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname !== "/api/v1/conversations/" || url.searchParams.get("version") !== "3")
        return fetch(input, init);
      window.fetch = fetch;
      const response = await fetch(input, init);
      const body = await response.text();
      const metadata = /data: [^\n]*"type"\s*:\s*"data-session"[^\n]*\r?\n\r?\n/.exec(body);
      if (!response.ok || !metadata) throw new Error("Expected a real conversation session stream");
      const boundary = metadata.index + metadata[0].length;
      const encoder = new TextEncoder();
      controlled.navigationStream.ready = true;
      return new Response(
        new ReadableStream({
          async start(controller) {
            await session;
            controller.enqueue(encoder.encode(body.slice(0, boundary)));
            await answer;
            controller.enqueue(encoder.encode(body.slice(boundary)));
            controller.close();
          }
        }),
        response
      );
    };
  });
}

test("one page link stays current across a saved chat and administration", async ({ page }) => {
  await page.goto("/spaces/personal/chat");
  await askChatQuestion(page, uniqueName("Current conversation"));
  await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
  await expect(page).toHaveURL(/\/spaces\/personal\/chat\?session_id=/);
  const sessionId = new URL(page.url()).searchParams.get("session_id");
  // A saved conversation belongs to the personal space's Chatt, as in the Svelte app's space menu.
  const chat = "/spaces/personal/chat?tab=chat";
  const current = page.locator('a[aria-current="page"]');
  await page.reload();
  await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
  await expect(current).toHaveCount(1);
  await expect(current).toHaveAttribute("href", chat);

  await page
    .getByRole("navigation", { name: "Huvudområden", exact: true })
    .getByRole("link", { name: "Administratör", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Administration", exact: true })
    .getByRole("link", { name: "Användare", exact: true })
    .click();
  await expect(page).toHaveURL(/\/admin\/users$/);
  await expect(current).toHaveCount(1);
  await expect(current).toHaveAttribute("href", "/admin/users");

  await page.getByRole("link", { name: "Tillbaka till Eneo", exact: true }).click();
  await page.getByRole("tab", { name: "Historik", exact: true }).click();
  await page.locator(`button[data-session-row="${sessionId}"]`).click();
  await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
  await expect(current).toHaveCount(1);
  await expect(current).toHaveAttribute("href", chat);
});

test("a page in a menu is a link: a modified click opens it in a new tab", async ({
  page,
  context
}) => {
  await page.goto("/spaces/list");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const start = page.url();
  await page.getByRole("button", { name: /: konto och inställningar$/ }).click();
  const account = page.getByRole("menu").getByRole("menuitem", { name: "Mitt konto", exact: true });
  await expect(account).toHaveAttribute("href", "/account");

  const opened = context.waitForEvent("page");
  await account.click({ modifiers: ["ControlOrMeta"] });
  const tab = await opened;
  await expect(tab).toHaveURL(/\/account$/);
  await tab.close();
  await expect(page).toHaveURL(start);
});

test("the session URL arrives during streaming without remounting or scrolling the conversation", async ({
  page
}) => {
  await gateChatStream(page);
  await page.goto("/spaces/personal/chat");
  const question = uniqueName("Stream continuity") + "\n" + "A line to keep in view.\n".repeat(60);
  await askChatQuestion(page, question);
  await expect
    .poll(() => page.evaluate(() => (window as unknown as StreamWindow).navigationStream.ready))
    .toBe(true);
  await chatComposer(page).fill("En följdfråga medan svaret förbereds");
  const log = conversationLog(page);
  await expect(log).toBeVisible();
  await log.evaluate((element) => {
    element.setAttribute("data-navigation-conversation", "original");
    // Chat owns a scroll container inside main; main itself does not scroll.
    let scroller = element.parentElement;
    while (scroller && getComputedStyle(scroller).overflowY !== "auto")
      scroller = scroller.parentElement;
    if (!scroller) throw new Error("Expected the conversation scroll container");
    scroller.setAttribute("data-navigation-scroll", "original");
    scroller.scrollTop = 120;
  });
  const scroller = page.locator('[data-navigation-scroll="original"]');
  await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBe(120);
  await expect(page).not.toHaveURL(/session_id=/);
  try {
    await page.evaluate(() =>
      (window as unknown as StreamWindow).navigationStream.releaseSession()
    );
    await expect(page).toHaveURL(/session_id=/);
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(chatComposer(page)).toHaveValue("En följdfråga medan svaret förbereds");
    await expect(
      page.getByRole("button", { name: "Stoppa generering", exact: true })
    ).toBeVisible();
    await expect(log).toHaveAttribute("data-navigation-conversation", "original");
    await expect(log.getByText(MOCK_REPLY)).toHaveCount(0);
    await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBe(120);

    await page.evaluate(() => (window as unknown as StreamWindow).navigationStream.releaseAnswer());
    await expect(log.getByText(MOCK_REPLY)).toBeVisible();
    await expect(log).toHaveAttribute("data-navigation-conversation", "original");
    await expect(page.getByRole("button", { name: "Stoppa generering", exact: true })).toHaveCount(
      0
    );
  } finally {
    await page.evaluate(() => {
      const stream = (window as unknown as StreamWindow).navigationStream;
      stream.releaseSession();
      stream.releaseAnswer();
    });
  }
});

for (const control of ["new", "history", "same-URL new"] as const) {
  test(`conversation controls keep unsent work until consent: ${control}`, async ({ page }) => {
    let destinationId: string | null = null;
    if (control === "same-URL new") await gateChatStream(page);
    await page.goto("/spaces/personal/chat");
    if (control !== "same-URL new") {
      await askChatQuestion(page, uniqueName("History destination"));
      await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
      destinationId = new URL(page.url()).searchParams.get("session_id");
      expect(destinationId).toBeTruthy();
      await page.getByRole("button", { name: "Ny konversation", exact: true }).click();
    }
    await askChatQuestion(page, uniqueName("Current conversation"));
    if (control === "same-URL new") {
      await expect
        .poll(() => page.evaluate(() => (window as unknown as StreamWindow).navigationStream.ready))
        .toBe(true);
    } else {
      await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
    }
    const originalUrl = page.url();
    const draft = "En oskickad fråga som ska vara kvar";
    await chatComposer(page).fill(draft);
    await page.locator('input[type="file"]').setInputFiles({
      name: "draft.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Unsent attachment")
    });
    const attachment = page.getByRole("button", { name: "Ta bort draft.txt", exact: true });
    await expect(attachment).toBeVisible();
    // Historik is a tab beside the chat, as in the Svelte app.
    const tab = (name: string) => page.getByRole("tab", { name, exact: true });
    const switchConversation = async () => {
      if (control !== "history") {
        await page.getByRole("button", { name: "Ny konversation", exact: true }).click();
        return;
      }
      await tab("Historik").click();
      await page.locator(`button[data-session-row="${destinationId}"]`).click();
    };
    const confirmation = page.getByRole("alertdialog", { name: "Lämna sidan?", exact: true });
    try {
      await switchConversation();
      await expect(confirmation).toBeVisible();
      // Historik writes ?tab=history; the conversation stays mounted behind it.
      const shown = new URL(originalUrl);
      if (control === "history") shown.searchParams.set("tab", "history");
      await expect(page).toHaveURL(shown.href);
      // Behind Historik the conversation is hidden, not gone: its draft and file are there.
      await expect(
        page.getByRole("textbox", { name: CHAT_COMPOSER_NAME, includeHidden: true })
      ).toHaveValue(draft);
      await expect(
        page.getByRole("button", { name: "Ta bort draft.txt", exact: true, includeHidden: true })
      ).toHaveCount(1);
      await confirmation.getByRole("button", { name: "Avbryt", exact: true }).click();
      if (control === "history") await tab("Chatt").click();
      await expect(chatComposer(page)).toBeEditable();
      await expect(chatComposer(page)).toHaveValue(draft);
      await expect(page).toHaveURL(originalUrl);
      await expect(attachment).toBeVisible();
      await switchConversation();
      await confirmation.getByRole("button", { name: "Lämna utan att spara", exact: true }).click();
      await expect(attachment).toHaveCount(0);
      if (control === "history") {
        await expect
          .poll(() => new URL(page.url()).searchParams.get("session_id"))
          .toBe(destinationId);
        await expect(conversationLog(page).getByText(MOCK_REPLY)).toBeVisible();
      } else {
        await expect(page).not.toHaveURL(/session_id=/);
        await expect(conversationLog(page)).toHaveCount(0);
      }
    } finally {
      if (control === "same-URL new")
        await page.evaluate(() => {
          const stream = (window as unknown as StreamWindow).navigationStream;
          stream.releaseSession();
          stream.releaseAnswer();
        });
    }
  });
}

for (const cached of [false, true]) {
  test(`a pending ${cached ? "cached" : "new"} space keeps the current frame until its data arrives`, async ({
    page
  }) => {
    await page.goto("/spaces/personal/chat");
    const secondName = uniqueName("Next space");
    const second = await createSpace(page, secondName);
    const firstName = uniqueName("Current space");
    const first = await createSpace(page, firstName);
    // Prime the destination only for the cached-return case.
    await page.goto(`${cached ? second : first}/overview`);
    // The space's sidebar: its switcher names the space, its sections link it.
    const nav = page.getByRole("navigation", { name: "Ytans meny", exact: true });
    const sectionsOf = (space: string) => nav.locator(`a[href="${space}/members"]`);
    const main = page.getByRole("main");
    await expect(
      main.getByRole("heading", { name: cached ? secondName : firstName, exact: true })
    ).toBeVisible();
    async function openSpace(name: string) {
      await page.keyboard.press("ControlOrMeta+k");
      const palette = page.getByRole("dialog", { name: /^(Sök i Eneo|Search Eneo)$/ });
      await palette.getByRole("combobox").fill(name);
      await palette.getByRole("option", { name: new RegExp(name) }).click();
    }
    if (cached) await openSpace(firstName);
    await expect(sectionsOf(first)).toBeVisible();
    await expect(main.getByRole("heading", { name: firstName, exact: true })).toBeVisible();
    // Expire Query's 30 s freshness window without delaying the suite or its timers.
    if (cached) await page.clock.setFixedTime(Date.now() + 31_000);

    let held = 0;
    let release!: () => void;
    const released = new Promise<void>((resolve) => (release = resolve));
    await page.route(
      (url) => url.pathname === `/api/v1${second}/`,
      async (route) => {
        held++;
        await released;
        await route.continue();
      }
    );
    try {
      await openSpace(secondName);
      await expect.poll(() => held).toBeGreaterThan(0);
      // Exercise the slow path past the router's 200 ms pending threshold and
      // 400 ms minimum display time, not just the first frame after a click.
      await page.waitForTimeout(1_000);
      await expect(sectionsOf(first)).toBeVisible();
      await expect(sectionsOf(second)).toHaveCount(0);
      await expect(main.getByRole("heading", { name: firstName, exact: true })).toBeVisible();
      await expect(main.getByRole("heading", { name: secondName, exact: true })).toHaveCount(0);

      release();
      await expect(page).toHaveURL(new RegExp(`${second}/overview$`));
      await expect(main.getByRole("heading", { name: secondName, exact: true })).toBeVisible();
      await expect(sectionsOf(second)).toBeVisible();
      await expect(nav.locator(`a[href="${second}/overview"][aria-current="page"]`)).toBeVisible();
    } finally {
      release();
      await page.unrouteAll({ behavior: "ignoreErrors" });
    }
  });
}

test("a direct space load shows progress while waiting for its data", async ({ page }) => {
  const name = uniqueName("Direct space");
  const space = await createSpace(page, name);
  let held = 0;
  let release!: () => void;
  const released = new Promise<void>((resolve) => (release = resolve));
  await page.route(
    (url) => url.pathname === `/api/v1${space}/`,
    async (route) => {
      held++;
      await released;
      await route.continue();
    }
  );
  const loading = page.goto(`${space}/overview`);
  try {
    await expect.poll(() => held).toBeGreaterThan(0);
    await expect(page.getByRole("status").filter({ hasText: "Laddar..." })).toBeVisible();
    release();
    await loading;
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  } finally {
    release();
    await loading;
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test.describe("unsaved edits on Vite", { tag: "@vite" }, () => {
  test("Skills keep edits on cancelled Back and link navigation, then leave on confirmation", async ({
    page
  }) => {
    await page.goto("/spaces/personal/skills");
    // An empty space offers only its empty state's "Skapa din första skill".
    await page
      .getByRole("link", { name: /^(Skapa (din första )?skill|Create (the first )?skill)$/i })
      .click();
    const name = page.getByRole("textbox", { name: /^(Namn|Name)$/ });
    await name.fill(uniqueName("Unsaved Skill"));
    const draft = await name.inputValue();
    const unloading = page.waitForEvent("dialog");
    // A cancelled navigation has no load event for Playwright's reload to await.
    const reload = page.evaluate(() => window.location.reload());
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

    const catalogue = page
      .getByRole("navigation", { name: /^(Ytans meny|Space menu)$/ })
      .getByRole("link", { name: "Skills", exact: true });
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

  test("chat document edits survive chunk and save failures and cancelled navigation, then save and leave", async ({
    page,
    context
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const file = {
      id: "11111111-1111-4111-8111-111111111111",
      name: "Navigation.md",
      mimetype: "text/markdown",
      size: 24
    };
    // The mock model has no document tool. Add its generated-file stream part;
    // the conversation and session still come from the backend's real stream.
    await page.route(isChatStream, async (route) => {
      const response = await fetchChatStream(route);
      const events = (await response.text()).split(/\r?\n\r?\n/).filter((event) => event.trim());
      const finish = events.findIndex((event) => /"type":\s*"finish"/.test(event));
      expect(finish).toBeGreaterThanOrEqual(0);
      events.splice(
        finish,
        0,
        `data: ${JSON.stringify({
          type: "file",
          url: new URL(`/api/v1/files/${file.id}/download/?token=fixture`, page.url()).href,
          mediaType: file.mimetype,
          filename: file.name,
          providerMetadata: { eneo: { ...file, tool_call_id: null } }
        })}`
      );
      await route.fulfill({
        response,
        headers: {
          ...sessionResponseHeaders(route),
          "content-type": "text/event-stream",
          "x-vercel-ai-ui-message-stream": "v1"
        },
        body: events.map((event) => `${event}\n\n`).join("")
      });
    });
    const original = `/api/v1/files/${file.id}/original/download/?token=fixture`;
    await page.route(`**/api/v1/files/${file.id}/original/signed-url/`, (route) =>
      route.fulfill({
        headers: sessionResponseHeaders(route),
        json: { url: new URL(original, page.url()).href }
      })
    );
    await page.route(`**/api/v1/files/${file.id}/original/download/**`, (route) =>
      route.fulfill({ contentType: "text/markdown", body: "Original.\n" })
    );
    let refuseSave = true;
    await page.route(`**/api/v1/conversations/*/documents/${file.id}/versions/`, (route) => {
      expect(route.request().postDataJSON()).toEqual({ content: "Changed document.\n" });
      return route.fulfill(
        refuseSave
          ? { status: 503, json: { message: "Unavailable" } }
          : {
              headers: sessionResponseHeaders(route),
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
    const clipboardAsset = productionAsset("src/components/ai-elements/answer-clipboard.ts");
    await page.route(
      (url) => url.pathname === clipboardAsset,
      (route) =>
        route.fulfill({ status: 404, contentType: "text/plain", body: "Removed deployment asset" })
    );
    await page
      .getByRole("log")
      .getByRole("button", { name: /fler åtgärder|more actions/i })
      .click();
    const unloading = page.waitForEvent("dialog");
    const copy = page
      .getByRole("menuitem", { name: /kopiera som formaterad text|copy as formatted text/i })
      .click();
    const warning = await unloading;
    expect(warning.type()).toBe("beforeunload");
    await warning.dismiss();
    await copy;
    await expect(
      page.getByText(
        "Det gick inte att kopiera. Försök igen eller markera texten och kopiera den.",
        { exact: true }
      )
    ).toBeVisible();
    await expect(editor).toHaveText("Changed document.");
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await expect(
      page.getByText("Ändringarna kunde inte sparas. Försök igen.", { exact: true })
    ).toBeVisible();
    const personal = page
      .getByRole("navigation", { name: "Huvudområden", exact: true })
      .getByRole("link", { name: "Personligt", exact: true });
    await personal.click();
    const dialog = page.getByRole("alertdialog", { name: "Lämna sidan?" });
    await dialog.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(editor).toHaveText("Changed document.");
    refuseSave = false;
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await expect(page.getByRole("button", { name: "Spara", exact: true })).not.toBeVisible();
    await personal.click();
    await expect(page).toHaveURL(/\/spaces\/personal\/chat$/);
    await expect(dialog).not.toBeVisible();
  });
});

test("a page in a menu opens from the keyboard, and Escape returns to the menu's button", async ({
  page
}) => {
  await page.goto("/spaces/list");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const trigger = page.getByRole("button", { name: /: konto och inställningar$/ });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  // Escape closes it, and focus is back on the button.
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();

  await page.keyboard.press("Enter");
  const account = menu.getByRole("menuitem", { name: "Mitt konto", exact: true });
  for (
    let step = 0;
    step < 12 && !(await account.evaluate((el) => el === document.activeElement));
    step += 1
  )
    await page.keyboard.press("ArrowDown");
  await expect(account).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/account$/);
});

test(
  "Tab runs from the space switcher to the sidebar's toggle, which keeps focus",
  { tag: ["@vite"] },
  async ({ page }) => {
    await page.goto("/spaces/personal/chat");
    const space = await createSpace(page, uniqueName("Toggle order"));
    await page.goto(`${space}/overview`);
    const nav = page.getByRole("navigation", { name: "Ytans meny", exact: true });
    const toggle = nav.getByRole("button", { name: /sidomenyn$/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await nav.locator("button").first().focus();
    await page.keyboard.press("Tab");
    await expect(toggle).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toBeFocused();
  }
);

import { readFile } from "node:fs/promises";
import { expect, test } from "./csp";
import {
  createSpace,
  openCreateCollectionDialog,
  sessionResponseHeaders,
  uniqueName
} from "./helpers";

test.describe("knowledge downloads on touch", () => {
  test.use({ hasTouch: true, isMobile: true });
  test(
    "downloads extracted text and hands an original URL to the browser on a phone",
    { tag: "@vite" },
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width: 390, height: 844 });
      const space = await createSpace(page, uniqueName("E2E Nedladdning"));
      await page.goto(`${space}/knowledge`);
      const create = await openCreateCollectionDialog(page);
      await create.getByLabel(/^(namn|name)$/i).fill("Riktlinjer");
      await create.getByRole("button", { name: /skapa samling|create collection/i }).click();
      await page.waitForURL(/\/knowledge\/collections\/[^/]+$/);
      await page.getByRole("button", { name: /lägg till text|add text/i }).click();
      const editor = page.getByRole("dialog", { name: /lägg till text|add text/i });
      await editor.getByLabel(/^(titel|title)$/i).fill("Riktlinjer.txt");
      const text = "Riktlinjer för öppen data.\n\n<script>alert('text')</script>";
      await editor.getByLabel(/^(innehåll|content)$/i).fill(text);
      await editor.getByRole("button", { name: /^(skicka|submit)$/i }).click();
      await expect(editor).toBeHidden();

      // The text is real backend data. The original capability is a fixture:
      // verify the browser handoff, without claiming original-byte delivery.
      await page.route(/\/api\/v1\/info-blobs\/[^/]+\/$/, async (route) => {
        const response = await route.fetch();
        await route.fulfill({
          response,
          json: { ...(await response.json()), original_available: true }
        });
      });
      await page.route(/\/api\/v1\/info-blobs\/[^/]+\/original\/signed-url\/$/, async (route) => {
        const path = new URL(route.request().url()).pathname.replace(/signed-url\/$/, "download/");
        await route.fulfill({
          headers: sessionResponseHeaders(route),
          json: { url: `${page.url().split("/spaces/")[0]}${path}?token=browser-proof` }
        });
      });
      await page.getByRole("button", { name: "Riktlinjer.txt", exact: true }).click();
      const preview = page.getByRole("dialog", { name: "Riktlinjer.txt" });
      const textButton = preview.getByRole("button", { name: /ladda ner.*text|download.*text/i });
      await expect(textButton).toBeEnabled();
      const extractedDownload = page.waitForEvent("download");
      await textButton.click();
      const extracted = await extractedDownload;
      expect(extracted.suggestedFilename()).toBe("Riktlinjer.txt");
      expect(await readFile((await extracted.path())!, "utf8")).toBe(text);
      const originalDownload = page.waitForEvent("download");
      await preview.getByRole("button", { name: /ladda ner original|download original/i }).click();
      const original = await originalDownload;
      const target = new URL(original.url());
      expect(target.origin).toBe(new URL(page.url()).origin);
      expect(target.pathname).toMatch(/^\/api\/v1\/info-blobs\/[^/]+\/original\/download\/$/);
      expect(target.searchParams.get("token")).toBe("browser-proof");
      await original.cancel();
      await expect(preview).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
      ).toBeLessThanOrEqual(0);
      await page.screenshot({
        path: testInfo.outputPath("knowledge-preview-phone.png"),
        fullPage: true
      });
    }
  );
});

test(
  "restores server search and a URL folder after reloading indexed content",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const space = await createSpace(page, uniqueName("E2E Webbplatsinnehåll"));
    await page.goto(`${space}/knowledge?tab=websites`);
    await page
      .getByRole("main")
      .getByRole("button", { name: /anslut webbplats|connect website/i })
      .click();
    const create = page.getByRole("dialog");
    await create.getByLabel(/^(webbadress|web address)/i).fill("https://example.org/");
    await create.getByRole("button", { name: /skapa webbplats|create website/i }).click();
    await expect(create).toBeHidden();
    const website = page.getByRole("main").getByRole("link", { name: "example.org/", exact: true });
    const href = await website.getAttribute("href");
    expect(href).toBeTruthy();

    // Deterministic indexed-page fixtures exercise actual routes, browser search,
    // CSP and layouts without requiring a live crawler or external website.
    await page.route(/\/api\/v1\/websites\/[^/]+\/content-folders\/\?/, async (route) => {
      const prefix = new URL(route.request().url()).searchParams.get("prefix");
      const items = !prefix
        ? [{ path: "https://example.org/", count: 2, has_children: true }]
        : prefix === "https://example.org/"
          ? [{ path: "https://example.org/docs/", count: 2, has_children: false }]
          : [];
      await route.fulfill({
        headers: sessionResponseHeaders(route),
        json: { items, next_cursor: null }
      });
    });
    await page.route(/\/api\/v1\/websites\/[^/]+\/info-blobs\/page\/\?/, async (route) => {
      const query = new URL(route.request().url()).searchParams.get("q") ?? "";
      const title = query ? "Sökresultat bortom första sidan" : "Första sidan";
      await route.fulfill({
        headers: sessionResponseHeaders(route),
        json: {
          items: [
            {
              id: "indexed-page",
              created_at: "2026-10-30T08:00:00Z",
              metadata: {
                title,
                url: "https://example.org/docs/riktlinjer.html",
                size: 20,
                embedding_model_id: "fixture-model"
              },
              original_available: false
            }
          ],
          total_count: query ? 1 : 2,
          next_cursor: null
        }
      });
    });
    await page.goto(
      `${href}?tab=blobs&prefix=${encodeURIComponent("https://example.org/docs/")}&q=riktlinjer`
    );
    const search = page.getByRole("searchbox");
    await expect(search).toHaveValue("riktlinjer");
    await expect(
      page.getByRole("button", { name: "Sökresultat bortom första sidan", exact: true })
    ).toBeVisible();
    const nav = page.getByRole("navigation", { name: "URL-struktur" });
    await expect(nav.getByRole("link", { name: /docs/ })).toHaveAttribute("aria-current", "page");
    await search.fill("rutiner");
    await expect(page).toHaveURL(/[?&]q=rutiner/);
    await page.reload();
    await expect(search).toHaveValue("rutiner");
    await expect(nav.getByRole("link", { name: /docs/ })).toHaveAttribute("aria-current", "page");
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await expect(search).toBeVisible();
      const nameColumn = page.getByRole("columnheader", { name: "Sortera efter Namn" });
      expect((await nameColumn.boundingBox())!.width).toBeGreaterThanOrEqual(176);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
      ).toBeLessThanOrEqual(0);
      for (const colorScheme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme });
        await page.screenshot({
          path: testInfo.outputPath(`knowledge-content-${width}-${colorScheme}.png`),
          fullPage: true
        });
      }
    }
  }
);

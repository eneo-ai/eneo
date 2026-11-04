import type { Space } from "../src/features/spaces/space";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, createSpace, sessionResponseHeaders, uniqueName } from "./helpers";

// The create button and its menu button are one control: both halves share one box.
test("draws the split create button as one control", { tag: "@vite" }, async ({ page }) => {
  const space = await createSpace(page, uniqueName("Split create"));
  await page.goto(`${space}/assistants`);
  const more = page.getByRole("main").getByRole("button", { name: "Fler sätt att skapa" }).first();
  await expect(more).toBeVisible();
  const halves = await more.evaluate((menu) => {
    const create = menu.parentElement!.firstElementChild!;
    return [create, menu].map((element) => {
      const { top, height } = element.getBoundingClientRect();
      return { top, height };
    });
  });
  expect(halves[1]).toEqual(halves[0]);
});

test(
  "creates a named group chat and honors both editor choices",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const space = await createSpace(page, uniqueName("Assistant creation"));
    for (const openEditor of [false, true]) {
      await page.goto(`${space}/assistants`);
      await page.getByRole("button", { name: "Fler sätt att skapa", exact: true }).click();
      await page.getByRole("menuitem", { name: "Skapa ny gruppchatt", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Skapa en ny gruppchatt", exact: true });
      const choice = dialog.getByRole("switch", {
        name: "Öppna gruppchatt-redigerare efter skapande",
        exact: true
      });
      await expect(choice).toBeChecked();
      const name = uniqueName(openEditor ? "Öppna grupp" : "Behåll grupp");
      await dialog.getByRole("textbox", { name: "Gruppchattens namn", exact: true }).fill(name);
      if (!openEditor) {
        await choice.uncheck();
        await page.setViewportSize({ width: 390, height: 844 });
        await expect(dialog).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
          390
        );
        await page.screenshot({
          path: testInfo.outputPath("group-create-phone.png"),
          animations: "disabled"
        });
        await page.setViewportSize({ width: 1280, height: 900 });
      }
      const creation = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/v1${space}/applications/group-chats/`
      );
      if (openEditor)
        await dialog
          .getByRole("textbox", { name: "Gruppchattens namn", exact: true })
          .press("Enter");
      else await dialog.getByRole("button", { name: "Skapa gruppchatt", exact: true }).click();
      const response = await creation;
      expect(response.status()).toBe(201);
      const group: Schema<"GroupChatPublic"> = await response.json();
      await expect(dialog).toBeHidden();
      if (openEditor) {
        await expect(page).toHaveURL(`${space}/group-chats/${group.id}/edit`);
        await expect(page.getByRole("textbox", { name: /^Namn/ })).toHaveValue(name);
      } else {
        await expect(page).toHaveURL(`${space}/assistants`);
        await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
      }
    }
  }
);

test(
  "rejects organization assistants by alias and id while keeping shared assistants",
  { tag: "@vite" },
  async ({ page }) => {
    const space = await createSpace(page, uniqueName("Assistant routes"));
    await page.goto(`${space}/assistants`);
    await expect(
      page.getByRole("heading", { name: "Assistenter", level: 1, exact: true })
    ).toBeVisible();
    const response = await page.request.get("/api/v1/spaces/type/organization/");
    expect(response.status()).toBe(200);
    const organization: Space = await response.json();
    expect(organization.organization).toBe(true);
    for (const routeId of ["organization", organization.id]) {
      await page.goto(`/spaces/${routeId}/assistants`);
      await expect(
        page.getByRole("heading", { name: "Sidan hittades inte", exact: true })
      ).toBeVisible();
    }
  }
);

test(
  "keeps valid move destinations and excludes current and organization spaces",
  { tag: "@vite" },
  async ({ page }) => {
    const currentName = uniqueName("Move current");
    const space = await createSpace(page, currentName);
    const targetName = uniqueName("Move target");
    await createSpace(page, targetName);
    const name = uniqueName("Movable assistant");
    await apiPost(page, `${space}/applications/assistants/`, { name });
    const response = await page.request.get("/api/v1/spaces/type/organization/");
    expect(response.status()).toBe(200);
    const organization: Space = await response.json();
    await page.goto(`${space}/assistants`);
    await page.getByRole("button", { name: `Fler åtgärder för ${name}`, exact: true }).click();
    await page.getByRole("menuitem", { name: /^Flytta/ }).click();
    const dialog = page.getByRole("dialog", { name: "Flytta assistent", exact: true });
    await dialog.getByRole("combobox", { name: "Destination", exact: true }).click();
    await expect(page.getByRole("option", { name: targetName, exact: true })).toBeVisible();
    await expect(page.getByRole("option", { name: currentName, exact: true })).toHaveCount(0);
    await expect(page.getByRole("option", { name: organization.name, exact: true })).toHaveCount(0);
    await page.getByRole("option", { name: targetName, exact: true }).click();
    await dialog.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(`${space}/assistants`);
  }
);

test(
  "expands selected wrappers and retries website cursor pages without losing loaded rows",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const space = await createSpace(page, uniqueName("Selected knowledge"));
    const assistantId = await apiPost(page, `${space}/applications/assistants/`, {
      name: "Kunskapsval"
    });
    const spaceResponse = await page.request.get(`/api/v1${space}/`);
    expect(spaceResponse.status()).toBe(200);
    const actualSpace: Space = await spaceResponse.json();
    const model = actualSpace.embedding_models[0];
    expect(model).toBeTruthy();
    const websiteId = "80000000-0000-4000-8000-000000000001";
    const website = {
      id: websiteId,
      name: "Handbok",
      url: "https://example.invalid/handbok/",
      space_id: actualSpace.id,
      embedding_model: model,
      latest_crawl: { pages_crawled: 2, files_downloaded: 0, pages_failed: 0, files_failed: 0 }
    };
    const integrations = [
      {
        id: "80000000-0000-4000-8000-000000000002",
        name: "Avtal",
        selected_item_type: "folder",
        folder_path: "/Dokument/Avtal"
      },
      {
        id: "80000000-0000-4000-8000-000000000003",
        name: "Policy.pdf",
        selected_item_type: "file",
        folder_path: "/Dokument/Policy.pdf"
      }
    ].map((item) => ({
      ...item,
      space_id: actualSpace.id,
      embedding_model: model,
      wrapper_id: "80000000-0000-4000-8000-000000000004",
      wrapper_name: "Importerad källa",
      integration_type: "sharepoint",
      metadata: { size: 0 }
    }));
    // Selected knowledge and indexed-page/error replies are presentation fixtures.
    // The space, assistant, browser cookie session and editor route are real.
    await page.route(`**/api/v1${space}/`, async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      const current: Space = await response.json();
      await route.fulfill({
        headers: sessionResponseHeaders(route),
        json: {
          ...current,
          knowledge: {
            ...current.knowledge,
            websites: { ...current.knowledge.websites, items: [website] },
            integration_knowledge_list: {
              ...current.knowledge.integration_knowledge_list,
              items: integrations
            }
          }
        }
      });
    });
    await page.route(`**/api/v1/assistants/${assistantId}/`, async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      await route.fulfill({
        headers: sessionResponseHeaders(route),
        json: {
          ...(await response.json()),
          websites: [website],
          integration_knowledge_list: integrations
        }
      });
    });
    const cursors: (string | null)[] = [];
    let failMore = true;
    await page.route(
      new RegExp(`/api/v1/websites/${websiteId}/info-blobs/page/`),
      async (route) => {
        const params = new URL(route.request().url()).searchParams;
        const cursor = params.get("cursor");
        cursors.push(cursor);
        expect(Number(params.get("limit"))).toBeGreaterThan(0);
        expect(Number(params.get("limit"))).toBeLessThanOrEqual(100);
        if (cursor && failMore) {
          await route.fulfill({
            status: 400,
            headers: sessionResponseHeaders(route),
            json: { message: "Fixture next page failed" }
          });
          return;
        }
        const title = cursor ? "Andra sidan" : "Första sidan";
        await route.fulfill({
          headers: sessionResponseHeaders(route),
          json: {
            items: [
              {
                id: cursor ? "indexed-second" : "indexed-first",
                created_at: "2026-10-31T08:00:00Z",
                metadata: { title, size: 12 }
              }
            ],
            total_count: 2,
            limit: 100,
            next_cursor: cursor ? null : "next"
          }
        });
      }
    );
    await page.goto(`${space}/assistants/${assistantId}/edit`);
    const wrapper = page.getByRole("button", { name: /Importerad källa/ });
    await expect(wrapper).toHaveAttribute("aria-expanded", "false");
    await wrapper.click();
    await expect(wrapper).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText("/Dokument/Avtal", { exact: true })).toBeVisible();
    await expect(page.getByText("Policy.pdf", { exact: true })).toBeVisible();
    expect(cursors).toEqual([]);
    await page.getByRole("button", { name: "Handbok", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Första sidan 12 B", exact: true })
    ).toBeVisible();
    expect(cursors).toEqual([null]);
    await page.getByRole("button", { name: /Läs in fler|Visa fler|Ladda fler/ }).click();
    const retry = page.getByRole("button", { name: /Försök igen/ });
    await expect(retry).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Första sidan 12 B", exact: true })
    ).toBeVisible();
    failMore = false;
    await retry.click();
    await expect(page.getByRole("button", { name: "Andra sidan 12 B", exact: true })).toBeVisible();
    expect(cursors).toEqual([null, "next", "next"]);
    await page.screenshot({
      path: testInfo.outputPath("selected-knowledge-pages.png"),
      animations: "disabled"
    });
  }
);

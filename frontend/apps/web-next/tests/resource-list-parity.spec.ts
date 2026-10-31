import type { Space } from "../src/features/spaces/space";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, createSpace, sessionResponseHeaders, uniqueName } from "./helpers";

for (const kind of ["apps", "assistants"] as const) {
  test(
    `${kind} preserves sortable views, collapse, permissions and menu navigation`,
    { tag: "@vite" },
    async ({ page }, testInfo) => {
      const space = await createSpace(page, uniqueName("Resource views"));
      const resources = [];
      for (const name of ["Alfa", "Åka", "Zeta"]) {
        resources.push({
          name: `${name} ${kind}`,
          id: await apiPost(page, `${space}/applications/${kind}/`, { name: `${name} ${kind}` })
        });
      }
      const readOnly = resources[2]!;
      // Only publication/row-permission presentation is a fixture. The space,
      // resources, cookie auth and edit destination remain backend-backed.
      await page.route(`**/api/v1${space}/`, async (route) => {
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        const current: Space = await response.json();
        expect(current.applications?.[kind].permissions).toContain("publish");
        if (!current.applications) throw new Error("Missing real space resources");
        const list = current.applications[kind];
        await route.fulfill({
          json: {
            ...current,
            applications: {
              ...current.applications,
              [kind]: {
                ...list,
                items: list.items.map((item) => ({
                  ...item,
                  published: item.id !== readOnly.id,
                  permissions: item.id === readOnly.id ? ["read"] : item.permissions
                }))
              }
            }
          },
          headers: sessionResponseHeaders(route)
        });
      });
      await page.goto(`${space}/${kind}`);
      const listButton = page.getByRole("button", { name: "Lista", exact: true });
      await listButton.focus();
      await listButton.press("Enter");
      await expect(listButton).toBeFocused();
      await expect(listButton).toHaveAttribute("aria-pressed", "true");
      const published = page.getByRole("region", { name: "Publicerad", exact: true });
      const publishedTable = published.getByRole("table");
      const names = () =>
        publishedTable.getByRole("row").locator("td:first-child a").allTextContents();
      expect(await names()).toEqual(resources.slice(0, 2).map((item) => item.name));
      const nameHeader = publishedTable.getByRole("columnheader", { name: /Namn/ });
      await nameHeader.getByRole("button").click();
      expect(await names()).toEqual([resources[1]!.name, resources[0]!.name]);
      const status = publishedTable.getByRole("columnheader", { name: /Status/ });
      await status.getByRole("button").click();
      await status.getByRole("button").click();
      expect(
        await page.getByRole("button", { name: /^(Publicerad|Utkast)$/ }).allTextContents()
      ).toEqual(["Utkast", "Publicerad"]);
      const draft = page.getByRole("region", { name: "Utkast", exact: true });
      await expect(
        draft
          .getByRole("table")
          .getByRole("row")
          .filter({ has: page.getByRole("link", { name: readOnly.name, exact: true }) })
          .getByRole("button")
      ).toHaveCount(0);
      await nameHeader.getByRole("button").click();
      const collapse = published.getByRole("button", { name: "Publicerad", exact: true });
      await collapse.focus();
      await collapse.press("Enter");
      await expect(collapse).toHaveAttribute("aria-expanded", "false");
      await expect(publishedTable).toBeHidden();
      await collapse.press("Enter");
      await expect(publishedTable).toBeVisible();
      const filter = page.getByRole("textbox", {
        name: kind === "apps" ? "Filtrera appar" : "Filtrera assistenter",
        exact: true
      });
      await filter.fill("Alfa");
      await expect(publishedTable.getByRole("link")).toHaveCount(1);
      await filter.fill("saknas-unikt");
      await expect(
        page.getByRole("heading", { name: "Inga resultat hittades", exact: true })
      ).toBeVisible();
      await expect(listButton).toHaveAttribute("aria-pressed", "true");
      await filter.fill("");
      await page.reload();
      await expect(listButton).toHaveAttribute("aria-pressed", "true");
      await expect(publishedTable).toBeVisible();
      await published.screenshot({ path: testInfo.outputPath(`${kind}-list.png`) });
      await page.getByRole("button", { name: "Kort", exact: true }).click();
      await page.reload();
      await expect(page.getByRole("button", { name: "Kort", exact: true })).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      await expect(published.getByRole("table")).toHaveCount(0);
      await page.getByRole("button", { name: /^Sortera: Namn/ }).click();
      await expect(
        page.getByRole("menuitemradio", { name: "Namn · Stigande", exact: true })
      ).toBeChecked();
      await page.getByRole("menuitemradio", { name: "Namn · Fallande", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "Sortera: Namn · Fallande", exact: true })
      ).toBeVisible();
      expect(
        await published
          .getByRole("link")
          .evaluateAll((links) => links.map((link) => link.getAttribute("aria-label")))
      ).toEqual([resources[1]!.name, resources[0]!.name]);
      await page.setViewportSize({ width: 320, height: 900 });
      await page.emulateMedia({ colorScheme: "dark" });
      await expect(listButton).toHaveCount(0);
      await published.screenshot({ path: testInfo.outputPath(`${kind}-phone-dark.png`) });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        320
      );
      await page.setViewportSize({ width: 1280, height: 900 });
      await listButton.click();
      const editable = resources[0]!;
      const row = publishedTable
        .getByRole("row")
        .filter({ has: page.getByRole("link", { name: editable.name, exact: true }) });
      await row
        .getByRole("button", { name: `Fler åtgärder för ${editable.name}`, exact: true })
        .click();
      await page.getByRole("menuitem", { name: "Redigera", exact: true }).click();
      await expect(page).toHaveURL(`${space}/${kind}/${editable.id}/edit`);
    }
  );
}

test(
  "spaces default to a sortable list and keep view, navigation and removal focus",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    await page.goto("/spaces/list");
    const prefix = uniqueName("List");
    const first = {
      name: `${prefix} Alfa`,
      id: await apiPost(page, "/spaces/", { name: `${prefix} Alfa` })
    };
    const second = {
      name: `${prefix} Zeta`,
      id: await apiPost(page, "/spaces/", { name: `${prefix} Zeta` })
    };
    await page.reload();
    const filter = page.getByRole("textbox", { name: "Filtrera ytor", exact: true });
    await filter.fill(prefix);
    const table = page.getByRole("table", { name: "Ytor", exact: true });
    await expect(page.getByRole("button", { name: "Lista", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await expect(table.getByRole("columnheader", { name: /Status/ })).toHaveCount(0);
    expect(await table.getByRole("link").allTextContents()).toEqual([first.name, second.name]);
    await table.getByRole("columnheader", { name: /Namn/ }).getByRole("button").click();
    expect(await table.getByRole("link").allTextContents()).toEqual([second.name, first.name]);
    await page.getByRole("button", { name: "Kort", exact: true }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Kort", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await filter.fill(prefix);
    await page.getByRole("button", { name: "Lista", exact: true }).click();
    await table.screenshot({ path: testInfo.outputPath("spaces-list.png") });
    await table
      .getByRole("button", { name: `Fler åtgärder för ${first.name}`, exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Radera yta", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Radera yta", exact: true });
    await dialog
      .getByRole("textbox", { name: "Ange ytnamnet för att bekräfta", exact: true })
      .fill(first.name);
    const deletion = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        new URL(response.url()).pathname === `/api/v1/spaces/${first.id}/`
    );
    await dialog.getByRole("button", { name: "Bekräfta borttagning", exact: true }).click();
    expect((await deletion).ok()).toBe(true);
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("heading", { level: 1, name: "Ytor", exact: true })).toBeFocused();
    await table.getByRole("link", { name: second.name, exact: true }).click();
    await expect(page).toHaveURL(`/spaces/${second.id}/overview`);
  }
);

test(
  "results filter and sort the returned collection and keep real result navigation",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const space = await createSpace(page, uniqueName("Sorted results"));
    const appId = await apiPost(page, `${space}/applications/apps/`, { name: "Result sorting" });
    const ids: string[] = [];
    for (const text of ["Zeta run", "Alfa run", "Beta run"])
      ids.push(await apiPost(page, `/apps/${appId}/runs/`, { text, files: [] }));
    await page.route(`**/api/v1/apps/${appId}/runs/`, async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      const payload: Schema<"PaginatedResponse_AppRunSparse_"> = await response.json();
      const statuses = ["queued", "failed", "complete"] as const;
      const dates = ["2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z"];
      await route.fulfill({
        json: {
          ...payload,
          items: payload.items.map((run) => {
            const index = ids.indexOf(run.id);
            return index < 0 ? run : { ...run, status: statuses[index], created_at: dates[index] };
          })
        },
        headers: sessionResponseHeaders(route)
      });
    });
    await page.goto(`${space}/apps/${appId}?tab=results`);
    const table = page.getByRole("table", { name: "Resultat", exact: true });
    await expect(table).toBeVisible();
    const names = table.getByRole("row").locator("td:first-child a");
    await expect(names).toHaveText(["Indata: Alfa run", "Indata: Beta run", "Indata: Zeta run"]);
    const name = table.getByRole("columnheader", { name: /Namn/ });
    await name.getByRole("button").click();
    await name.getByRole("button").click();
    await expect(names).toHaveText(["Indata: Zeta run", "Indata: Beta run", "Indata: Alfa run"]);
    await table
      .getByRole("columnheader", { name: /Status/ })
      .getByRole("button")
      .click();
    await expect(names).toHaveText(["Indata: Zeta run", "Indata: Alfa run", "Indata: Beta run"]);
    await table
      .getByRole("columnheader", { name: /Skapad/ })
      .getByRole("button")
      .click();
    await expect(names).toHaveText(["Indata: Zeta run", "Indata: Beta run", "Indata: Alfa run"]);
    const filter = page.getByRole("textbox", { name: "Filtrera resultat", exact: true });
    await filter.fill("alfa");
    await expect(table.getByRole("link")).toHaveCount(1);
    await filter.fill("saknas-unikt");
    await expect(
      page.getByRole("heading", { name: "Inga resultat hittades", exact: true })
    ).toBeVisible();
    await filter.fill("");
    await table.screenshot({ path: testInfo.outputPath("results-sorted.png") });
    await table.getByRole("link", { name: /Indata: Alfa run/ }).click();
    await expect(page).toHaveURL(`${space}/apps/${appId}/results/${ids[1]}`);
    await expect(page.getByText("Ditt resultat genereras.", { exact: true })).toBeVisible();
  }
);

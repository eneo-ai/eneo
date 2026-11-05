import AxeBuilder from "@axe-core/playwright";
import type { Page, Route } from "@playwright/test";
import { WCAG_22_AA_TAGS } from "../src/test/wcag";
import { expect, test } from "./csp";
import { createSpace, sessionResponseHeaders, uniqueName } from "./helpers";

const reply = (route: Route, json: unknown) =>
  route.fulfill({ headers: sessionResponseHeaders(route), json });
async function scan(page: Page) {
  type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];
  const result = await new AxeBuilder({ page: page as unknown as AxePage })
    .withTags(WCAG_22_AA_TAGS)
    .analyze();
  expect(
    result.violations.map((item) => ({ id: item.id, nodes: item.nodes.map((node) => node.target) }))
  ).toEqual([]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  ).toBeLessThanOrEqual(0);
}

// Session, space and shell are real backend data. SharePoint and crawl fixtures
// exercise the browser contracts without credentials or an external library.
test.describe("SharePoint import on touch", () => {
  test.use({ hasTouch: true, isMobile: true });
  test("searches, filters, replaces descendants and links the queued source", async ({
    page
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const space = await createSpace(page, uniqueName("E2E SharePoint"));
    const spaceId = space.split("/").at(-1)!;
    let imported = false;
    let batch: { items: { name: string; folder_id: string }[]; wrapper_name?: string } | null =
      null;
    const queries: URLSearchParams[] = [];
    const report = {
      id: "report",
      type: "file",
      name: "Riktlinjer för informationshantering.pdf",
      path: "/Dokument/Riktlinjer.pdf",
      size: 2048,
      has_children: false,
      source_metadata: [{ name: "Department", label: "Avdelning", value: "HR", kind: "text" }]
    };
    const handbook = {
      ...report,
      id: "handbook",
      name: "Personalhandbok.pdf",
      path: "/Dokument/Personalhandbok.pdf"
    };
    const folder = {
      id: "docs",
      type: "folder",
      name: "Dokument",
      path: "/Dokument",
      has_children: true
    };
    await page.route(
      (url) => url.pathname === `/api/v1/spaces/${spaceId}/`,
      async (route) => {
        const response = await route.fetch();
        const data = await response.json();
        if (imported)
          data.knowledge.integration_knowledge_list.items = [
            {
              id: "created-source",
              name: "Riktlinjer",
              original_name: null,
              url: "https://sharepoint.example.test/docs",
              space_id: spaceId,
              permissions: ["read", "edit", "delete"],
              integration_type: "sharepoint",
              embedding_model: data.embedding_models[0],
              wrapper_id: "created-wrapper",
              wrapper_name: "Personal",
              selected_item_type: "file",
              metadata: { size: 2048, document_count: 0 }
            }
          ];
        await route.fulfill({ response, json: data });
      }
    );
    await page.route(/\/api\/v1\/integrations\/spaces\/[^/]+\/available\/$/, (route) =>
      reply(route, {
        items: [
          {
            id: "connection",
            tenant_integration_id: "tenant-connection",
            name: "SharePoint",
            description: "",
            integration_type: "sharepoint",
            auth_type: "tenant_app",
            connected: true
          }
        ]
      })
    );
    await page.route(/\/api\/v1\/integrations\/connection\/preview\/$/, (route) =>
      reply(route, {
        items: [
          {
            key: "site",
            type: "site",
            name: "Intranätet",
            url: "https://sharepoint.example.test/"
          }
        ]
      })
    );
    await page.route(/\/api\/v1\/integrations\/connection\/sharepoint\/tree\//, (route) => {
      const nested = new URL(route.request().url()).searchParams.get("folder_id");
      return reply(route, {
        items: nested ? [report] : [folder],
        current_path: nested ? "/Dokument" : "/",
        drive_id: "drive",
        truncated: !nested,
        columns: nested
          ? []
          : [
              { name: "Department", label: "Avdelning", kind: "choice", choices: ["HR", "IT"] },
              { name: "Approved", label: "Godkänd", kind: "boolean" }
            ]
      });
    });
    await page.route(/\/api\/v1\/integrations\/connection\/sharepoint\/search\//, (route) => {
      queries.push(new URL(route.request().url()).searchParams);
      return reply(route, { items: [report, handbook], drive_id: "drive", truncated: true });
    });
    await page.route(
      /\/api\/v1\/spaces\/[^/]+\/knowledge\/integrations\/add\/connection\/batch\/$/,
      (route) => {
        batch = route.request().postDataJSON();
        imported = true;
        return reply(route, {
          created_count: 1,
          failed_count: 1,
          items: [
            {
              index: 0,
              name: report.name,
              status: "created",
              integration_knowledge_id: "created-source"
            },
            { index: 1, name: handbook.name, status: "failed", error: "Mappen finns inte" }
          ]
        });
      }
    );
    await page.goto(`${space}/knowledge?tab=integrations`);
    await page
      .getByRole("main")
      .getByRole("button", { name: "Importera kunskap", exact: true })
      .click();
    await page.getByRole("dialog").getByRole("button", { name: "Fortsätt" }).click();
    const dialog = page.getByRole("dialog", {
      name: "Importera kunskap från SharePoint / OneDrive"
    });
    await dialog.getByRole("button", { name: "Intranätet", exact: true }).click();
    await expect(
      dialog
        .getByRole("group", { name: "Innehåll", exact: true })
        .getByText("Alla objekt i mappen visas inte. Sök för att hitta resten.", {
          exact: true
        })
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Öppna mapp" }).click();
    await dialog.getByRole("checkbox", { name: report.name }).check();
    await expect(
      dialog.getByRole("textbox", { name: `Importnamn för ${report.name}` })
    ).toBeVisible();
    await dialog
      .getByRole("navigation", { name: "Intranätet" })
      .getByRole("button", { name: "Intranätet" })
      .click();
    await dialog.getByRole("checkbox", { name: "Dokument", exact: true }).check();
    await expect(
      dialog.getByRole("textbox", { name: `Importnamn för ${report.name}` })
    ).toHaveCount(0);
    await dialog.getByRole("checkbox", { name: "Dokument", exact: true }).uncheck();
    await dialog
      .getByRole("searchbox", { name: "Sök filer och egenskaper i Intranätet" })
      .fill("personal");
    await expect(dialog.getByRole("checkbox", { name: handbook.name })).toBeVisible();
    await page.setViewportSize({ width: 320, height: 844 });
    await dialog.getByRole("button", { name: "Filtrera på dokumentegenskaper, 0 aktiva" }).click();
    await expect(page.getByRole("combobox", { name: "Avdelning" })).toBeVisible();
    await scan(page);
    await page.screenshot({
      path: testInfo.outputPath("sharepoint-filters-320.png"),
      fullPage: true
    });
    await page.getByRole("combobox", { name: "Avdelning" }).focus();
    await page.keyboard.press("Space");
    await page.getByRole("option", { name: "HR", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Ta bort filtret Avdelning" })).toBeVisible();
    await dialog.getByRole("button", { name: "Filtrera på dokumentegenskaper, 1 aktiva" }).click();
    await page.getByRole("combobox", { name: "Godkänd" }).click();
    await page.getByRole("option", { name: "Ja", exact: true }).click();
    await expect
      .poll(() => queries.at(-1)?.getAll("filter").sort())
      .toEqual(["Approved:true", "Department:HR"]);
    expect(queries.at(-1)?.get("site_id")).toBe("site");
    expect(queries.at(-1)?.get("folder_id")).toBeNull();
    expect(queries.at(-1)?.get("q")).toBe("personal");
    await dialog.getByRole("button", { name: "Välj alla träffar (2)" }).click();
    await expect(dialog.getByRole("checkbox", { name: report.name })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: handbook.name })).toBeChecked();
    await dialog.getByRole("textbox", { name: /^Gruppnamn/ }).fill("Personal");
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await scan(page);
      await page.screenshot({
        path: testInfo.outputPath(`sharepoint-import-phone-${colorScheme}.png`),
        fullPage: true
      });
    }
    await dialog.getByRole("button", { name: "Importera", exact: true }).click();
    await expect(dialog.getByRole("heading", { name: "Import köad" })).toBeFocused();
    await expect(dialog.getByText("1 objekt kunde inte köas.", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Visa importen" })).toHaveAttribute(
      "href",
      `${space}/knowledge/integrations/created-source`
    );
    expect(batch).toMatchObject({
      wrapper_name: "Personal",
      items: [{ folder_id: "report" }, { folder_id: "handbook" }]
    });
    await scan(page);
    await page.screenshot({
      path: testInfo.outputPath("sharepoint-import-complete-phone.png"),
      fullPage: true
    });
    await dialog.getByRole("link", { name: "Visa importen" }).click();
    await expect(page).toHaveURL(
      `${space}/knowledge/integrations/wrapper/created-wrapper?folder=created-source`
    );
    await expect(dialog).toBeHidden();
  });
});

test("keeps one pending import while closing and reopening through the source selector", async ({
  page
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const space = await createSpace(page, uniqueName("E2E Pending SharePoint"));
  await page.route(/\/api\/v1\/integrations\/spaces\/[^/]+\/available\/$/, (route) =>
    reply(route, {
      items: [
        {
          id: "connection",
          tenant_integration_id: "tenant-connection",
          name: "SharePoint",
          description: "",
          integration_type: "sharepoint",
          auth_type: "tenant_app",
          connected: true
        }
      ]
    })
  );
  await page.route(/\/api\/v1\/integrations\/connection\/preview\/$/, (route) =>
    reply(route, {
      items: [
        { key: "site", type: "site", name: "Intranätet", url: "https://sharepoint.example.test/" }
      ]
    })
  );
  await page.route(/\/api\/v1\/integrations\/connection\/sharepoint\/tree\//, (route) =>
    reply(route, { items: [], current_path: "/", drive_id: "drive" })
  );
  let posts = 0;
  let release!: () => void;
  const finished = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    /\/api\/v1\/spaces\/[^/]+\/knowledge\/integrations\/add\/connection\/batch\/$/,
    async (route) => {
      posts += 1;
      await finished;
      await reply(route, {
        created_count: 1,
        failed_count: 0,
        items: [
          {
            index: 0,
            name: "Intranätet",
            status: "created",
            integration_knowledge_id: "created-source"
          }
        ]
      });
    }
  );
  await page.goto(`${space}/knowledge?tab=integrations`);
  const start = async () => {
    await page
      .getByRole("main")
      .getByRole("button", { name: "Importera kunskap", exact: true })
      .click();
    await page.getByRole("button", { name: "Fortsätt" }).click();
  };
  const choose = async () => {
    await page.getByRole("button", { name: "Intranätet", exact: true }).click();
    await page.getByRole("checkbox", { name: "Importera hela webbplatsen" }).check();
  };
  try {
    await start();
    await choose();
    await page.getByRole("button", { name: "Importera", exact: true }).click();
    await expect.poll(() => posts).toBe(1);
    await page.getByRole("dialog").getByRole("button", { name: "Stäng", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
    await start();
    await page.getByRole("button", { name: "Tillbaka", exact: true }).click();
    await page.getByRole("button", { name: "Fortsätt" }).click();
    await choose();
    const draft = page.getByRole("textbox", { name: "Importnamn för Intranätet" });
    await draft.fill("Ny draft");
    const submit = page.getByRole("button", { name: "Importerar...", exact: true });
    await expect(submit).toHaveAttribute("aria-busy", "true");
    await submit.click();
    expect(posts).toBe(1);
    release();
    await expect(page.getByRole("button", { name: "Importera", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Import köad" })).toHaveCount(0);
    await expect(draft).toHaveValue("Ny draft");
    expect(posts).toBe(1);
    await scan(page);
    await page.screenshot({
      path: testInfo.outputPath("sharepoint-reopened-draft.png"),
      fullPage: true
    });
  } finally {
    release();
  }
});

const crawl = (id: string, created_at: string) => ({
  id,
  created_at,
  finished_at: created_at,
  status: "complete",
  phase: "terminal",
  outcome: "partial",
  origin: "manual",
  pages_crawled: 3,
  pages_unchanged: 0,
  pages_failed: 2,
  files_downloaded: 0,
  files_unchanged: 0,
  files_failed: 1,
  failure_summary: { http_404: 2, file_too_large: 1 },
  failure_code: null,
  failure_detail: null,
  result_location: null,
  cancel_requested_at: null,
  attempt_count: 1
});
test("groups website Problems and switches completed crawls after a reload", async ({
  page
}, testInfo) => {
  const space = await createSpace(page, uniqueName("E2E Webbplatsproblem"));
  const runs = [crawl("latest", "2026-10-30T08:00:00Z"), crawl("older", "2026-10-28T08:00:00Z")];
  const readRuns: string[] = [];
  await page.route(/\/api\/v1\/websites\/website-fixture\/$/, (route) =>
    reply(route, {
      id: "website-fixture",
      name: "Riktlinjer",
      url: "https://example.org/",
      space_id: space.split("/").at(-1),
      permissions: ["read", "edit", "delete"],
      embedding_model: { id: "model", name: "Sökmodell" },
      metadata: { size: 0 },
      update_interval: "never",
      crawl_type: "crawl",
      download_files: true,
      requires_http_auth: false,
      is_auto_disabled: false
    })
  );
  await page.route(/\/api\/v1\/websites\/website-fixture\/runs\/latest\/$/, (route) =>
    reply(route, runs[0])
  );
  await page.route(/\/api\/v1\/websites\/website-fixture\/runs\//, (route) =>
    route.request().url().includes("/latest/")
      ? reply(route, runs[0])
      : reply(route, { items: runs, total_count: 2, next_cursor: null })
  );
  await page.route(/\/api\/v1\/websites\/website-fixture\/info-blobs\/page\//, (route) =>
    reply(route, { items: [], total_count: 0, next_cursor: null })
  );
  await page.route(/\/api\/v1\/crawl-runs\/(latest|older)\/failures\//, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-3)!;
    readRuns.push(id);
    return reply(route, {
      run: runs.find((run) => run.id === id),
      total_count: 3,
      next_cursor: null,
      details_available: true,
      items: [
        {
          id: `${id}-1`,
          kind: "page",
          reason: "http_404",
          url: `https://example.org/${id}/missing`
        },
        { id: `${id}-2`, kind: "page", reason: "http_404", url: "javascript:alert('unsafe')" },
        {
          id: `${id}-3`,
          kind: "file",
          reason: "file_too_large",
          url: `https://example.org/${id}/large.pdf`
        }
      ]
    });
  });
  await page.goto(`${space}/knowledge/websites/website-fixture?tab=problems`);
  await expect(page.getByRole("tab", { name: "Problem", exact: true })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await expect(page.getByRole("region", { name: "Adressen hittades inte (404)" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Problem", exact: true })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await page.getByRole("combobox", { name: "Inläsning" }).click();
  await page.getByRole("option").nth(1).click();
  await expect(page.getByRole("heading", { name: "Tidigare inläsning" })).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: "https://example.org/older/missing (öppnas i ny flik)",
      exact: true
    })
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /javascript/ })).toHaveCount(0);
  expect(readRuns).toContain("older");
  for (const width of [1280, 320]) {
    await page.setViewportSize({ width, height: 844 });
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await scan(page);
      await page.screenshot({
        path: testInfo.outputPath(`website-problems-${width}-${colorScheme}.png`),
        fullPage: true
      });
    }
  }
});

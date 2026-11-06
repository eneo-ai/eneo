import type { Page } from "@playwright/test";
import { expect, test } from "./csp";

/** The seed has no forecast model: the tool service's checkpoint is not in the stack. */
async function withForecastModel(page: Page) {
  await page.route(/\/api\/v1\/admin\/model-providers\/$/, async (route) => {
    const response = await route.fetch();
    const providers = await response.json();
    await route.fulfill({
      response,
      json: [
        ...providers,
        {
          ...providers[0],
          id: "22222222-2222-4222-8222-222222222222",
          name: "Eneo tool service",
          provider_type: "eneo_tool_service",
          is_managed: true,
          connection_check_supported: false
        }
      ]
    });
  });
  await page.route(/\/api\/v1\/ai-models\/$/, async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        forecast_models: [
          {
            id: "11111111-1111-4111-8111-111111111111",
            name: "default",
            nickname: "Timestral",
            org: "Mistral AI",
            open_source: true,
            is_deprecated: false,
            is_org_enabled: true,
            provider_id: "22222222-2222-4222-8222-222222222222",
            provider_name: "Eneo tool service",
            provider_type: "eneo_tool_service",
            security_classification: null,
            used_by_mcp_servers: [
              { id: "33333333-3333-4333-8333-333333333333", name: "Forecast", purpose: "forecast" }
            ]
          }
        ]
      }
    });
  });
}

test.describe("the models on a phone (decision 31)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("are rows with their hosting, a switch and a menu; the type opens as a sheet", async ({
    page
  }) => {
    await page.goto("/admin/models");
    // The seeded provider's models (e2e/seed.py).
    const list = page.getByRole("main").getByRole("list", { name: "E2E Mock Provider" });
    await expect(list).toBeVisible();
    await expect(page.getByRole("main").getByRole("table")).toHaveCount(0);
    const row = list.getByRole("listitem").first();
    const toggle = row.getByRole("switch");
    const menu = row.getByRole("button", { name: /^Fler åtgärder för / });
    for (const target of [toggle, menu]) {
      expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    // The switch's track sits level with the menu.
    const middle = async (target: typeof toggle) => {
      const box = (await target.boundingBox())!;
      return box.y + box.height / 2;
    };
    expect(Math.abs((await middle(toggle)) - (await middle(menu)))).toBeLessThanOrEqual(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );

    // The type filter is a selector; on touch it opens as a sheet.
    await page.getByRole("combobox", { name: /^Modelltyp/ }).click();
    const options = page.getByRole("listbox");
    await expect(options).toBeVisible();
    await expect(options.getByRole("option").first()).toBeVisible();
    await page.keyboard.press("Escape");
  });
});

test.describe("the forecast model on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("is a row under the provider that comes with the installation", async ({ page }) => {
    await withForecastModel(page);
    await page.goto("/admin/models?type=forecast");
    const list = page.getByRole("main").getByRole("list", { name: "Eneos verktygstjänst" });
    await expect(list.getByRole("button", { name: "Timestral", exact: true })).toBeVisible();
    await expect(page.getByRole("main").getByText("E2E Mock Provider")).toHaveCount(0);
    await expect(list.getByRole("switch", { name: "Aktivera Timestral" })).toBeVisible();
    // The provider has nothing to manage, and the key is no reader's concern.
    await expect(page.getByRole("main").getByText("default", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
  });
});

test.describe("the models on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("keep the type filter in the address", async ({ page }) => {
    await withForecastModel(page);
    await page.goto("/admin/models?type=forecast");
    const types = page.getByRole("radiogroup", { name: "Modelltyp" });
    await expect(types.getByRole("radio", { name: /^Prognos/, checked: true })).toBeVisible();
    await expect(page.getByRole("main").getByRole("table")).toHaveCount(1);

    await types.getByRole("radio", { name: /^Alla/ }).click();
    await expect(page).toHaveURL(/\/admin\/models$/);
    await page.reload();
    await expect(types.getByRole("radio", { name: /^Alla/, checked: true })).toBeVisible();
    await expect(page.getByRole("main").getByText("E2E Mock Provider")).not.toHaveCount(0);

    await page.goto("/admin/models?type=forecast");
    await expect(types.getByRole("radio", { name: /^Prognos/, checked: true })).toBeVisible();
    await page.getByRole("link", { name: "Modeller", exact: true }).first().click();
    await expect(types.getByRole("radio", { name: /^Alla/, checked: true })).toBeVisible();
  });

  test("keep their table and the type segments", async ({ page }) => {
    await page.goto("/admin/models");
    await expect(page.getByRole("main").getByRole("table").first()).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Modelltyp" })).toBeVisible();
  });

  test.describe("in dark mode", () => {
    test.use({ colorScheme: "dark" });

    test("raise the selected type above its track, with an edge", async ({ page }) => {
      await page.goto("/admin/models");
      const selected = page
        .getByRole("radiogroup", { name: "Modelltyp" })
        .getByRole("radio", { checked: true });
      await expect(selected).toBeVisible();
      // The painted luminance of the plate and of its track: each translucent
      // background composed over the first opaque one behind it.
      const { plate, track, edge } = await selected.evaluate((radio) => {
        const item = radio.closest<HTMLElement>(".astryx-segmented-control-item") ?? radio;
        const rgba = (element: Element) => {
          const [r = 0, g = 0, b = 0, a = 1] = (
            getComputedStyle(element).backgroundColor.match(/[\d.]+/g) ?? []
          ).map(Number);
          return { r, g, b, a };
        };
        const painted = (element: Element) => {
          const layers = [];
          for (let node: Element | null = element; node; node = node.parentElement) {
            const layer = rgba(node);
            if (layer.a > 0) layers.push(layer);
            if (layer.a === 1) break;
          }
          return layers.reduceRight(
            (below, top) => ({
              r: top.r * top.a + below.r * (1 - top.a),
              g: top.g * top.a + below.g * (1 - top.a),
              b: top.b * top.a + below.b * (1 - top.a),
              a: 1
            }),
            { r: 0, g: 0, b: 0, a: 1 }
          );
        };
        const luminance = ({ r, g, b }: { r: number; g: number; b: number }) =>
          [r, g, b]
            .map((channel) => channel / 255)
            .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
            .reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i]!, 0);
        return {
          plate: luminance(painted(item)),
          track: luminance(
            painted(item.closest(".astryx-segmented-control") ?? item.parentElement!)
          ),
          edge: getComputedStyle(item).boxShadow
        };
      });
      expect(plate).toBeGreaterThan(track);
      expect(edge).toContain("inset");
    });
  });

  test("keep an open model draft when the screen changes between tablet and phone", async ({
    page
  }) => {
    await page.goto("/admin/models");
    await page
      .getByRole("main")
      .getByRole("button", { name: /^Fler åtgärder för / })
      .first()
      .click();
    await page.getByRole("menuitem", { name: "Redigera", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const description = dialog.getByLabel("Beskrivning", { exact: true });
    await description.fill("Osparad beskrivning efter skärmbyte");
    for (const width of [390, 820]) {
      await page.setViewportSize({ width, height: 844 });
      await expect(dialog).toBeVisible();
      await expect(description).toHaveValue("Osparad beskrivning efter skärmbyte");
      await expect(description).toBeFocused();
    }
    await dialog.getByRole("button", { name: "Avbryt", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(
      page
        .getByRole("main")
        .getByRole("button", { name: /^Fler åtgärder för / })
        .first()
    ).toBeFocused();
  });
});

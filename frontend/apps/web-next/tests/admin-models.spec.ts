import { expect, test } from "./csp";

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

test.describe("the models on a tablet", () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

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

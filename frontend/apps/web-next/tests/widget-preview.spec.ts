import { expect, test } from "./csp";
import { apiPost, uniqueName } from "./helpers";
import { selectedProbe } from "./selected-probe";
import { controlName } from "./responsive-measure";

test("the widget preview marks its scheme and stays inside narrow editors", async ({ page }) => {
  await page.goto("/spaces/list");
  const space = await apiPost(page, "/spaces/", { name: uniqueName("Widget preview") });
  const assistant = await apiPost(page, `/spaces/${space}/applications/assistants/`, {
    name: uniqueName("Besökschatt")
  });
  await apiPost(page, `/spaces/${space}/widgets/`, {
    name: uniqueName("Widget"),
    target_id: assistant
  });
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto(`/spaces/${space}/assistants/${assistant}/widget`);
  const frame = page.getByTitle("Förhandsgranskning av chattwidgeten");
  await expect(frame).toBeVisible();
  await page.getByRole("button", { name: "Mobilbredd", exact: true }).click();
  const schemes = page.getByRole("group", { name: "Färgschema i förhandsgranskningen" });
  const schemeKey = await schemes.evaluate(controlName);
  const theme = await page.evaluate(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light"
  );
  for (const name of ["Ljust", "Mörkt", "Automatiskt"]) {
    const choice = schemes.getByRole("button", { name, exact: true });
    await choice.click();
    await expect(choice).toHaveAttribute("aria-pressed", "true");
    await expect
      .poll(async () => {
        const findings = await selectedProbe(page, {
          viewport: { width: 320, height: 568 },
          theme,
          touch: true
        });
        return findings.filter(
          ({ key }) => key === `selected ${schemeKey}` || key === `pressed ${schemeKey}`
        );
      })
      .toEqual([]);
  }
  for (const width of [320, 390, 820]) {
    await page.setViewportSize({ width, height: 844 });
    await expect
      .poll(() =>
        frame.evaluate((element) => {
          const panel = element.parentElement!.getBoundingClientRect();
          const preview = element.getBoundingClientRect();
          return (
            preview.left >= panel.left &&
            preview.right <= panel.right &&
            preview.left >= 0 &&
            preview.right <= window.innerWidth &&
            document.documentElement.scrollWidth <= window.innerWidth
          );
        })
      )
      .toBe(true);
  }
});

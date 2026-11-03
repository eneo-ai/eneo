import { expect, test } from "./csp";
import { apiPost, uniqueName } from "./helpers";

test("the mobile widget preview stays inside its editor on narrow phones", async ({ page }) => {
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

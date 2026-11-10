import { expect, test } from "./csp";
import { apiPath, apiPostJson } from "./helpers";

let username: string | undefined;

// The shared stack keeps no throwaway users, also when the test failed.
test.afterEach(async ({ page }) => {
  if (!username) return;
  await page.evaluate(
    async (url) => {
      const session = await fetch("/api/v1/auth/session/");
      await fetch(url, {
        method: "DELETE",
        headers: { "Eneo-Session-Generation": session.headers.get("Eneo-Session-Generation") ?? "" }
      });
    },
    apiPath(`/admin/users/${username}`)
  );
  username = undefined;
});

/**
 * A role change saved through the user editor, against the real backend: the
 * save once failed as "That email is already taken" for the user's own,
 * unchanged email, so no existing user could be edited.
 */
test("saves a role change to an existing user and keeps it after a reload", async ({ page }) => {
  const name = `e2e-editor-${Date.now()}`;
  await page.goto("/admin/users");
  const user = await apiPostJson<{ email: string }>(page, "/admin/users/", {
    email: `${name}@example.com`,
    username: name
  });
  username = name;

  const openEditor = async () => {
    await page.getByRole("button", { name: `Fler åtgärder för ${user.email}` }).click();
    await page.getByRole("menuitem", { name: "Redigera användare" }).click();
    return page.getByRole("dialog", { name: "Redigera användare" });
  };
  const roles = (dialog: ReturnType<typeof page.getByRole>) =>
    dialog.getByRole("group", { name: /^(Standardroller|Anpassade roller)$/ });

  await page.goto(`/admin/users?search_name=${name}`);
  const dialog = await openEditor();
  // The form saves once the password policy has loaded; until then a submit is ignored.
  await expect(dialog.getByRole("checkbox", { name: /^Generera ett nytt lösenord/ })).toBeVisible();
  const role = await roles(dialog)
    .getByRole("checkbox", { checked: false })
    .first()
    .evaluate((input) => (input as HTMLInputElement).labels?.[0]?.textContent ?? "");
  expect(role).toBeTruthy();
  const box = page.getByRole("checkbox", { name: role, exact: true });
  // The whole row is the target a user taps.
  await roles(dialog).getByRole("listitem").filter({ has: box }).click();
  await expect(roles(dialog).getByRole("checkbox", { name: role, exact: true })).toBeChecked();

  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === apiPath(`/admin/users/${name}/`)
  );
  await dialog.getByRole("button", { name: "Spara ändringar" }).click();
  const response = await saved;
  expect(response.status(), await response.text()).toBe(200);
  await expect(dialog).toBeHidden();

  await page.reload();
  const reopened = await openEditor();
  await expect(roles(reopened).getByRole("checkbox", { name: role, exact: true })).toBeChecked();
  await reopened.getByRole("button", { name: "Avbryt" }).click();
  await expect(reopened).toBeHidden();
});

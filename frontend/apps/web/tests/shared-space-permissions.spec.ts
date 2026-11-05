import { expect, test } from "@playwright/test";
import { backendFetch, expectOk, loginViaUi, uniqueName } from "./helpers";

test("a shared-space viewer can read the space but cannot create assistants or members", async ({
  page,
  request
}) => {
  test.setTimeout(60_000);

  await page.goto("/");

  const viewerEmail = `${uniqueName("e2e-viewer").toLowerCase().replaceAll(" ", "-")}@example.com`;
  const viewerPassword = "E2eViewerPassword1!";
  const spaceName = uniqueName("E2E Shared Space");

  const createUserResponse = await backendFetch(page, request, "/api/v1/admin/users/", {
    method: "POST",
    data: {
      email: viewerEmail,
      username: viewerEmail.split("@")[0],
      password: viewerPassword
    }
  });
  await expectOk(createUserResponse, "creating viewer user");
  const viewer = await createUserResponse.json();

  const createSpaceResponse = await backendFetch(page, request, "/api/v1/spaces/", {
    method: "POST",
    data: { name: spaceName }
  });
  await expectOk(createSpaceResponse, "creating shared space");
  const space = await createSpaceResponse.json();

  const addViewerResponse = await backendFetch(
    page,
    request,
    `/api/v1/spaces/${space.id}/members/`,
    {
      method: "POST",
      data: {
        id: viewer.id,
        role: "viewer"
      }
    }
  );
  await expectOk(addViewerResponse, "adding viewer to shared space");

  await page.goto("/logout");
  await page.getByRole("button", { name: /^(Logga ut|Logout)$/ }).click();
  await expect(page).toHaveURL(/\/login/);
  await loginViaUi(page, viewerEmail, viewerPassword);

  // An admin-created account chooses its own password before anything else.
  // The forced flow itself is pinned in password-lifecycle.spec; this test
  // pins the space permissions.
  await expect(page).toHaveURL(/\/password-change/);
  const chosenPassword = "ViewerChosenPassword2!";
  await page.getByLabel("Nuvarande lösenord").fill(viewerPassword);
  await page.getByLabel("Nytt lösenord", { exact: true }).fill(chosenPassword);
  await page.getByLabel("Bekräfta nytt lösenord").fill(chosenPassword);
  await page.getByRole("button", { name: "Byt lösenord" }).click();
  await expect(page).toHaveURL(/\/login\?message=password_changed/);
  await loginViaUi(page, viewerEmail, chosenPassword);

  await page.goto(`/spaces/${space.id}/members`);
  await expect(page.getByRole("heading", { name: /^(Members|Medlemmar)$/i })).toBeVisible();
  await expect(page.getByText(new RegExp(`${viewerEmail} \\((You|du)\\)`, "i"))).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Add new member|Lägg till ny medlem/i })
  ).toHaveCount(0);

  await page.goto(`/spaces/${space.id}/assistants`);
  await expect(page.getByRole("heading", { name: /^(Assistants|Assistenter)$/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Create assistant|Skapa assistent/i })).toHaveCount(
    0
  );
});

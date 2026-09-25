import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { BACKEND_URL, backendFetch, expectOk, loginViaUi, uniqueName } from "./helpers";

// Central flow: an organisation administrator oversees a shared space they
// are not a member of. The space is created by another person, so the admin
// sees it only under Admin → Ytor until they join with a written reason,
// which the space's members see (the reason only its administrators).
// Widget activation goes through the same kind of review: an editor asks,
// the admin reviews without joining and activates exactly what they saw.

const PASSWORD = "E2eOversightPassword1!";
const LATEST_RELEASE = (
  JSON.parse(
    readFileSync(new URL("../../../packages/whats-new/releases.json", import.meta.url), "utf8")
  ) as { releases: { version: string }[] }
).releases[0].version;

type Person = { id: string; email: string; token: string };
type FetchOptions = Parameters<APIRequestContext["fetch"]>[1];

/**
 * Every WCAG 2.0–2.2 A and AA violation on the page, whatever axe rates its
 * impact. Checked once entry transitions have finished: Page.Title flies in
 * from 30 % opacity, which axe would otherwise measure as low contrast.
 */
async function wcagViolations(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((animation) => animation.effect?.getComputedTiming().endTime !== Infinity)
        .map((animation) => animation.finished.catch(() => undefined))
    )
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"])
    .analyze();
  return results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    targets: v.nodes.map((node) => node.target)
  }));
}

/** A person who is not an organisation administrator, with their own API token. */
async function createPerson(
  page: Page,
  request: APIRequestContext,
  prefix: string,
  permissions: string[] = []
): Promise<Person> {
  const email = `${uniqueName(prefix).toLowerCase().replaceAll(" ", "-")}@example.com`;
  const roles: { id: string }[] = [];
  if (permissions.length > 0) {
    const role = await backendFetch(page, request, "/api/v1/roles/", {
      method: "POST",
      data: { name: uniqueName(prefix), permissions }
    });
    await expectOk(role, `creating the role for ${prefix}`);
    roles.push({ id: (await role.json()).id });
  }

  const created = await backendFetch(page, request, "/api/v1/admin/users/", {
    method: "POST",
    data: { email, username: email.split("@")[0], password: PASSWORD, roles }
  });
  await expectOk(created, `creating ${email}`);

  const login = await request.post(`${BACKEND_URL}/api/v1/users/login/token/`, {
    form: { username: email, password: PASSWORD }
  });
  await expectOk(login, `signing in ${email}`);
  const person: Person = {
    id: (await created.json()).id,
    email,
    token: (await login.json()).access_token
  };
  // The first page after sign-in announces the newest release and records it
  // while the test may already be navigating, so the dialog can reopen over
  // the next page and block its clicks. Record it before they sign in.
  await expectOk(
    await fetchAs(person, request, "/api/v1/whats-new/announced/", {
      method: "PUT",
      data: { version: LATEST_RELEASE }
    }),
    `recording the release announcement for ${email}`
  );
  return person;
}

function fetchAs(
  person: Person,
  request: APIRequestContext,
  path: string,
  options: FetchOptions = {}
) {
  return request.fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${person.token}` }
  });
}

/** Signs the person in through the UI in a browser of their own. */
async function signIn(browser: Browser, baseURL: string, person: Person) {
  // A new context gets the project's options too, including the admin's session.
  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] }
  });
  const page = await context.newPage();
  await loginViaUi(page, person.email, PASSWORD);
  return page;
}

async function createSpace(request: APIRequestContext, owner: Person, name: string) {
  const response = await fetchAs(owner, request, "/api/v1/spaces/", {
    method: "POST",
    data: { name }
  });
  await expectOk(response, "creating the space as its owner");
  return (await response.json()) as { id: string };
}

async function addMember(
  request: APIRequestContext,
  owner: Person,
  spaceId: string,
  member: Person,
  role: "viewer" | "editor"
) {
  await expectOk(
    await fetchAs(owner, request, `/api/v1/spaces/${spaceId}/members/`, {
      method: "POST",
      data: { id: member.id, role }
    }),
    `adding a ${role} to the space`
  );
}

test("an organisation administrator oversees a space, joins it with a reason and leaves", async ({
  page,
  request,
  browser,
  baseURL
}) => {
  test.setTimeout(120_000);
  await page.goto("/");

  const owner = await createPerson(page, request, "e2e-space-owner", ["shared_spaces"]);
  const viewer = await createPerson(page, request, "e2e-space-viewer");
  const spaceName = uniqueName("E2E Oversight Space");
  const reason = "Ärende 2026-0042: kontroll av ytans kunskapskällor";
  const space = await createSpace(request, owner, spaceName);
  await addMember(request, owner, space.id, viewer, "viewer");

  // Admin → Ytor lists the space although the admin is not a member.
  await page.getByRole("link", { name: "Administratör", exact: true }).click();
  await page.getByRole("link", { name: "Ytor", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/spaces$/);
  await expect(page.getByRole("heading", { level: 1, name: "Ytor" })).toBeVisible();
  // A reused stack holds more spaces than one page of the list; the search finds this one.
  await page.goto(`/admin/spaces?q=${encodeURIComponent(spaceName)}`);
  const search = page.getByRole("searchbox", { name: "Sök bland ytor" });
  await expect(search).toHaveValue(spaceName);
  const spaceLink = page.getByRole("link", { name: spaceName, exact: true });
  const row = page.getByRole("row").filter({ has: spaceLink });
  await expect(
    row.getByText("Inte medlem", { exact: true }).filter({ visible: true })
  ).toBeVisible();
  expect(await wcagViolations(page)).toEqual([]);

  // A filter chosen on the page survives a visit to a space and Back.
  const notMember = page.getByRole("radio", { name: /^Där du inte är medlem/ });
  await notMember.click();
  await expect(page).toHaveURL(/membership=not_member/);
  await spaceLink.click();
  await expect(page).toHaveURL(new RegExp(`/admin/spaces/${space.id}$`));
  await page.goBack();
  await expect(search).toHaveValue(spaceName);
  await expect(notMember).toBeChecked();
  await expect(page).toHaveURL(/membership=not_member/);

  // The oversight page shows the space without its content.
  await spaceLink.click();
  await expect(page).toHaveURL(new RegExp(`/admin/spaces/${space.id}$`));
  await expect(page.getByRole("heading", { level: 1, name: spaceName })).toBeVisible();
  const viewingTitle = page.getByRole("heading", {
    level: 2,
    name: "Du ser ytan som organisationsadministratör"
  });
  await expect(viewingTitle).toBeVisible();
  expect(await wcagViolations(page)).toEqual([]);

  // Joining needs a reason of at least ten characters, and the lowest role is the default.
  await page.getByRole("button", { name: "Gå med i ytan…" }).click();
  const joinDialog = page.getByRole("dialog", { name: `Gå med i ${spaceName}?` });
  await expect(joinDialog.getByRole("radio", { name: "Visare" })).toBeChecked();
  await expect(joinDialog.getByRole("radio", { name: "Visare" })).toBeFocused();
  const reasonField = joinDialog.getByRole("textbox", { name: /^Anledning/ });
  await reasonField.fill("kort");
  const joinButton = joinDialog.getByRole("button", { name: "Gå med som Visare" });
  await joinButton.click();
  await expect(reasonField).toHaveAttribute("aria-invalid", "true");
  await expect(reasonField).toBeFocused();
  await reasonField.fill(reason);
  await joinButton.click();
  await expect(joinDialog).toBeHidden();

  const memberTitle = page.getByRole("heading", { level: 2, name: "Du är medlem i ytan" });
  await expect(memberTitle).toBeVisible();
  await expect(memberTitle).toBeFocused();
  await expect(page.getByText(/^Din roll: Visare\. Du gick med via tillsyn /)).toBeVisible();
  await expect(
    page.getByText(`Du har gått med i ${spaceName} med rollen Visare. Ytan finns i din ytväljare.`)
  ).toBeVisible();

  // The space is now in the admin's space selector.
  await page.getByRole("link", { name: "Öppna ytan", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/spaces/${space.id}/overview$`));
  await page.getByRole("button", { name: "Ändra yta eller skapa en ny" }).click();
  await expect(page.getByRole("menuitem", { name: spaceName })).toBeVisible();
  await page.keyboard.press("Escape");

  // A viewer is told who joined, when and with which role, but not why.
  const viewerPage = await signIn(browser, baseURL!, viewer);
  try {
    await viewerPage.goto(`/spaces/${space.id}/overview`);
    const notice = viewerPage.getByRole("note", {
      name: "En organisationsadministratör har gått med i ytan"
    });
    await expect(notice).toBeVisible();
    await expect(notice).toContainText(/ gick med .+ med rollen Visare\./);
    await expect(notice).not.toContainText("Anledning");
    await expect(viewerPage.getByText(reason)).toHaveCount(0);
  } finally {
    await viewerPage.context().close();
  }

  // The reason is in the data only for the space's administrators.
  const joinOf = async (person: Person) => {
    const response = await fetchAs(person, request, `/api/v1/spaces/${space.id}/`);
    await expectOk(response, "reading the space");
    const body = (await response.json()) as {
      members: { items: { oversight_join?: { reason?: string | null } | null }[] };
    };
    return body.members.items.find((member) => member.oversight_join)?.oversight_join;
  };
  expect((await joinOf(owner))?.reason).toBe(reason);
  expect((await joinOf(viewer))?.reason ?? null).toBeNull();

  // Leaving returns the admin to viewing the space from outside.
  await page.goto(`/admin/spaces/${space.id}`);
  await page.getByRole("button", { name: "Lämna ytan…" }).click();
  const leaveDialog = page.getByRole("alertdialog", { name: `Lämna ${spaceName}?` });
  await expect(leaveDialog.getByRole("button", { name: "Avbryt" })).toBeFocused();
  await leaveDialog.getByRole("button", { name: "Lämna ytan", exact: true }).click();
  await expect(leaveDialog).toBeHidden();
  await expect(viewingTitle).toBeFocused();
  await expect(page.getByText(`Du har lämnat ${spaceName}.`)).toBeVisible();
  expect(await joinOf(owner)).toBeUndefined();

  // Members still see the visit after the administrator has left, with when they left.
  const visitsOf = async (person: Person) => {
    const response = await fetchAs(person, request, `/api/v1/spaces/${space.id}/`);
    await expectOk(response, "reading the space");
    return ((await response.json()) as { oversight_visits: { left_at: string | null }[] })
      .oversight_visits;
  };
  expect((await visitsOf(viewer)).map((visit) => visit.left_at === null)).toEqual([false]);
  const laterPage = await signIn(browser, baseURL!, viewer);
  try {
    await laterPage.goto(`/spaces/${space.id}/overview`);
    await expect(laterPage.getByRole("note")).toContainText(/ med rollen Visare och lämnade /);
  } finally {
    await laterPage.context().close();
  }
});

test("an editor's activation request is reviewed and activated at the reviewed revision", async ({
  page,
  request,
  browser,
  baseURL
}) => {
  test.setTimeout(120_000);
  await page.goto("/");

  const owner = await createPerson(page, request, "e2e-widget-owner", [
    "shared_spaces",
    "assistants"
  ]);
  const editor = await createPerson(page, request, "e2e-widget-editor", ["assistants", "widgets"]);
  const space = await createSpace(request, owner, uniqueName("E2E Widget Review Space"));
  await addMember(request, owner, space.id, editor, "editor");

  const assistantResponse = await fetchAs(
    owner,
    request,
    `/api/v1/spaces/${space.id}/applications/assistants/`,
    { method: "POST", data: { name: "Granskningsassistenten" } }
  );
  await expectOk(assistantResponse, "creating the assistant");
  const assistantId = (await assistantResponse.json()).id as string;
  await expectOk(
    await fetchAs(owner, request, `/api/v1/assistants/${assistantId}/publish/?published=true`, {
      method: "POST"
    }),
    "publishing the assistant"
  );

  const widgetName = uniqueName("E2E review widget");
  const createdWidget = await fetchAs(editor, request, `/api/v1/spaces/${space.id}/widgets/`, {
    method: "POST",
    data: { target_id: assistantId, name: widgetName, language: "sv" }
  });
  await expectOk(createdWidget, "creating the widget");
  const widget = (await createdWidget.json()) as { id: string; revision: number };
  await expectOk(
    await fetchAs(editor, request, `/api/v1/widgets/${widget.id}/`, {
      method: "PATCH",
      data: { revision: widget.revision, allowed_origins: ["https://www.example.com"] }
    }),
    "allowing a website"
  );

  // The editor asks for activation in the widget editor.
  const editorPage = await signIn(browser, baseURL!, editor);
  try {
    await editorPage.goto(`/spaces/${space.id}/assistants/${assistantId}/widget`);
    await editorPage.getByRole("button", { name: "Begär aktivering" }).click();
    await expect(editorPage.getByRole("button", { name: "Dra tillbaka begäran" })).toBeVisible();
    await expect(editorPage.getByText("Väntar på aktivering", { exact: true })).toBeVisible();
  } finally {
    await editorPage.context().close();
  }

  // The admin finds the request in the overview and reviews it without joining.
  await page.goto("/admin/widgets");
  const requests = page.getByRole("region", { name: "Väntar på aktivering" });
  await requests.getByRole("link", { name: `Granska ${widgetName}` }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/widgets/${widget.id}$`));
  await expect(page.getByRole("heading", { level: 1, name: widgetName })).toBeVisible();
  await expect(page.getByText(/ begärde aktivering /)).toBeVisible();
  expect(await wcagViolations(page)).toEqual([]);

  const review = await backendFetch(page, request, `/api/v1/admin/widgets/${widget.id}/`);
  await expectOk(review, "reading the review");
  const reviewedRevision = ((await review.json()) as { widget: { revision: number } }).widget
    .revision;

  const activation = page.waitForRequest(
    (sent) => sent.method() === "POST" && sent.url().endsWith(`/widgets/${widget.id}/activate/`)
  );
  await page.getByRole("button", { name: "Aktivera…" }).click();
  const dialog = page.getByRole("alertdialog", { name: `Aktivera ${widgetName}?` });
  await dialog.getByRole("button", { name: "Aktivera", exact: true }).click();
  expect((await activation).postDataJSON()).toEqual({ revision: reviewedRevision });
  await expect(dialog).toBeHidden();

  const status = page.getByRole("region", { name: "Status" });
  await expect(status.getByText("Aktiv", { exact: true })).toBeVisible();
  await expect(status.getByText(/ aktiverade widgeten /)).toBeVisible();
  await expect(status.getByRole("heading", { name: "Status" })).toBeFocused();
  await expect(page.getByText(`${widgetName} är aktiv.`)).toBeVisible();

  // Paused again, so repeated local runs against one stack stay under the active-widget ceiling.
  await expectOk(
    await backendFetch(page, request, `/api/v1/widgets/${widget.id}/pause/`, { method: "POST" }),
    "pausing the widget"
  );
});

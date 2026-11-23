// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAppContext } from "@/components/providers/app-context";
import {
  QueryAppContextProvider,
  type AppContextEnv
} from "@/components/providers/app-context-from-queries";
import type { EneoClient } from "@/lib/api/browser";
import { loadSession } from "@/lib/api/session";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { RolesPage } from "./roles-page";

/*
 * An administrator changes their own role and uses what it grants in the same
 * session: the signed-in user's permissions come from /users/me, so a role
 * change has to reach that query, not only the role list.
 */

const backend = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PUT: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: backend }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const TEMPLATE = ["admin", "assistants"];
const signedIn = testAppContext();
const env: AppContextEnv = {
  links: { accessibilityStatement: null, helpCenter: null, legacyApp: null },
  frontendVersion: "0.1.0",
  backendVersion: "1.2.3"
};
const answered = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

// The backend's state: the signed-in user's only role, as the role editor changes it.
let ownRole: { id: string; name: string; permissions: string[]; predefined_source: string };

beforeEach(() => {
  vi.clearAllMocks();
  ownRole = { id: "own", name: "Ägare", permissions: [...TEMPLATE], predefined_source: "Owner" };
  const routes: Record<string, () => unknown> = {
    "/api/v1/users/me/": () => ({ ...signedIn.user, roles: [structuredClone(ownRole)] }),
    "/api/v1/users/tenant/": () => signedIn.tenant,
    "/api/v1/settings/": () => signedIn.settings,
    "/api/v1/auth/federation-status": () => signedIn.federationStatus,
    "/api/v1/limits/": () => signedIn.limits,
    "/api/v1/whats-new/state/": () => ({ seen_version: "1.0.0", announced_version: "1.0.0" }),
    "/api/v1/roles/": () => ({
      roles: { items: [structuredClone(ownRole)], count: 1 },
      predefined_roles: { items: [], count: 0 }
    }),
    "/api/v1/roles/permissions/": () =>
      ["admin", "assistants", "retention_manage", "retention_holds"].map((name) => ({
        name,
        description: name
      })),
    "/api/v1/roles/templates/": () => [{ name: "Owner", permissions: TEMPLATE }]
  };
  backend.GET.mockImplementation((path: string) => answered(routes[path]!()));
  backend.POST.mockImplementation(
    (path: string, options: { body?: { permissions?: string[] } }) => {
      if (path === "/api/v1/roles/{role_id}/reset/") ownRole.permissions = [...TEMPLATE];
      else if (options.body?.permissions) ownRole.permissions = options.body.permissions;
      return answered(structuredClone(ownRole));
    }
  );
});

/** What a screen that asks for retention_manage sees, such as a space's time. */
function ManagesRetention() {
  return <p>{useAppContext().can("retention_manage") ? "manages" : "does not manage"}</p>;
}

async function renderAdmin() {
  const queryClient = testQueryClient();
  await loadSession(queryClient, backend as unknown as EneoClient);
  renderInApp(
    <QueryAppContextProvider env={env}>
      <RolesPage />
      <ManagesRetention />
    </QueryAppContextProvider>,
    { queryClient }
  );
}

it("lets an administrator grant their own role retention_manage and lose it on a reset, without a reload", async () => {
  await renderAdmin();
  expect(await screen.findByText("does not manage")).toBeTruthy();

  const row = (await screen.findByText("Ägare")).closest("article")!;
  fireEvent.click(within(row).getByRole("button", { name: /Redigera/ }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("checkbox", { name: /^Gallring – hantera regler/ }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Spara ändringar" }));

  // The session follows the new grant.
  expect(await screen.findByText("manages")).toBeTruthy();

  // Resetting the role to its template takes the grant away again.
  const trigger = within(row).getByRole("button", { name: "Fler åtgärder för Ägare" });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Återställ till mall" }));
  fireEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", { name: "Återställ" })
  );

  expect(await screen.findByText("does not manage")).toBeTruthy();
});

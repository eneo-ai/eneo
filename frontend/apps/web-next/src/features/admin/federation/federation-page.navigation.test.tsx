// @vitest-environment jsdom
import { createRoute } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import { testAppContext } from "@/test/render";
import { renderWithRouter } from "@/test/router";
import type { FederationView } from "./federation";

vi.unmock("@/lib/link");
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { FederationPage } from "./federation-page";

const view: FederationView = {
  configured: true,
  provider: "Entra ID",
  discovery_endpoint: "https://idp.example/.well-known/openid-configuration",
  issuer: "https://idp.example",
  client_id: "eneo-client",
  client_secret_set: true,
  client_secret_updated_at: "2026-10-01T08:00:00Z",
  encryption_status: "encrypted",
  allowed_domains: ["example.org"],
  redirect_uris: ["https://eneo.example/login/callback"],
  redirect_uris_problem: null,
  scopes: ["openid", "email", "profile"],
  token_endpoint_auth_method: "client_secret_post",
  revision: "rev-1",
  configured_at: "2026-10-01T08:00:00Z"
};

async function open() {
  api.GET.mockImplementation(() => Promise.resolve({ data: view, response: new Response("{}") }));
  const result = await renderWithRouter(null, {
    route: "/admin/federation",
    appContext: testAppContext({ settings: { provisioning: false } }),
    routes: (root) => [
      createRoute({
        getParentRoute: () => root,
        path: "/admin/federation",
        component: FederationPage
      }),
      createRoute({
        getParentRoute: () => root,
        path: "/admin/settings",
        component: () => <h1>Settings</h1>
      })
    ]
  });
  await screen.findByLabelText(new RegExp(sv.federation_admin_domains));
  return result;
}

const domains = () =>
  screen.getByLabelText(new RegExp(sv.federation_admin_domains)) as HTMLTextAreaElement;

async function followSettingsLink() {
  const link = screen.getByRole("link", {
    name: sv.federation_admin_jit_link.replace("{setting}", sv.enable_provisioning)
  });
  link.focus();
  await act(async () => {
    fireEvent.click(link);
  });
}

it("keeps unsaved edits when the admin stays, and leaves only after confirmation", async () => {
  const { router } = await open();
  fireEvent.change(domains(), { target: { value: "example.org\nfoo.se" } });

  await followSettingsLink();
  await screen.findByRole("alertdialog", { name: sv.unsaved_navigation_title });
  expect(router.state.location.pathname).toBe("/admin/federation");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
  });
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(domains().value).toBe("example.org\nfoo.se");

  await followSettingsLink();
  await screen.findByRole("alertdialog");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: sv.unsaved_navigation_leave }));
  });
  await screen.findByRole("heading", { name: "Settings" });
});

it("keeps the edits while a save is under way, so a failed save can be tried again", async () => {
  let fail = () => {};
  api.PATCH.mockImplementation(
    () =>
      new Promise((resolve) => {
        fail = () =>
          resolve({ error: { message: "boom" }, response: new Response(null, { status: 500 }) });
      })
  );
  const { router } = await open();
  fireEvent.change(domains(), { target: { value: "example.org\nfoo.se" } });
  fireEvent.click(screen.getByRole("button", { name: sv.save_changes }));
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", {
      name: sv.federation_admin_confirm_action
    })
  );
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));

  await act(async () => {
    void router.navigate({ to: "/admin/settings" });
  });
  await screen.findByRole("alertdialog", { name: sv.unsaved_navigation_title });
  expect(router.state.location.pathname).toBe("/admin/federation");
  await act(async () => {
    fireEvent.click(
      within(screen.getByRole("alertdialog", { name: sv.unsaved_navigation_title })).getByRole(
        "button",
        { name: "Avbryt" }
      )
    );
  });
  await act(async () => fail());

  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(domains().value).toBe("example.org\nfoo.se");
});

it("follows the link at once when nothing is changed", async () => {
  await open();

  await followSettingsLink();

  await screen.findByRole("heading", { name: "Settings" });
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

it("follows the link at once after a successful save", async () => {
  const saved = { ...view, allowed_domains: ["example.org", "foo.se"], revision: "rev-2" };
  api.PATCH.mockImplementation(() =>
    Promise.resolve({ data: saved, response: new Response("{}") })
  );
  await open();
  fireEvent.change(domains(), { target: { value: "example.org\nfoo.se" } });
  fireEvent.click(screen.getByRole("button", { name: sv.save_changes }));
  fireEvent.click(
    within(await screen.findByRole("alertdialog")).getByRole("button", {
      name: sv.federation_admin_confirm_action
    })
  );
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());

  await followSettingsLink();

  await screen.findByRole("heading", { name: "Settings" });
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

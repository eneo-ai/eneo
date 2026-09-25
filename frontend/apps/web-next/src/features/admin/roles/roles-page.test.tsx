// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
const refresh = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post, DELETE: remove } }));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({ tenant: { default_role_id: "default" } })
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { RolesPage } from "./roles-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const defaultRole = { id: "default", name: "Everyone", permissions: ["personal_chat"] };
const customRole = {
  id: "custom",
  name: "Manager",
  permissions: ["admin"],
  predefined_source: "Admin"
};
const roleResponse = {
  roles: { items: [customRole], count: 1 },
  predefined_roles: { items: [defaultRole], count: 1 }
};

beforeEach(() => {
  get.mockImplementation((path: string) =>
    path === "/api/v1/roles/"
      ? ok(roleResponse)
      : path === "/api/v1/roles/permissions/"
        ? ok([
            { name: "personal_chat", description: "Chat" },
            { name: "admin", description: "Admin" }
          ])
        : ok([{ name: "Reader", permissions: ["personal_chat"] }])
  );
  post.mockImplementation(() => ok(customRole));
  remove.mockImplementation(() => ok(customRole));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RolesPage />
    </QueryClientProvider>
  );
}

describe("role administration", () => {
  it("shows the default role and searches the permissions granted by a role", async () => {
    show();
    expect(await screen.findByText("Everyone")).toBeTruthy();
    expect(screen.getByText("roles_default_badge")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "permission_admin" } });
    expect(screen.getByText("Manager")).toBeTruthy();
    expect(screen.queryByText("Everyone")).toBeNull();
  });

  it("creates a role from selected template permissions", async () => {
    show();
    await screen.findByText("Everyone");
    fireEvent.click(screen.getByRole("button", { name: "create_role" }));
    fireEvent.change(screen.getByLabelText("role_name"), { target: { value: "Readers" } });
    fireEvent.click(screen.getByRole("button", { name: "Reader" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "create_role" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/roles/", {
        body: { name: "Readers", permissions: ["personal_chat"] }
      })
    );
  });

  it("updates only changed fields and refreshes the role list", async () => {
    show();
    const row = (await screen.findByText("Manager")).closest("article");
    if (!row) throw new Error("Role row missing");
    fireEvent.click(within(row).getByRole("button", { name: "edit" }));
    fireEvent.change(screen.getByLabelText("role_name"), { target: { value: "Operations" } });
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "save_changes" })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/roles/{role_id}/", {
        params: { path: { role_id: "custom" } },
        body: { name: "Operations" }
      })
    );
  });

  it("requires confirmation before changing the default and prevents deleting it", async () => {
    show();
    const defaultRow = (await screen.findByText("Everyone")).closest("article");
    const customRow = screen.getByText("Manager").closest("article");
    if (!defaultRow || !customRow) throw new Error("Role row missing");
    expect(
      within(defaultRow).getByRole("button", { name: "delete_role" }).hasAttribute("disabled")
    ).toBe(true);
    fireEvent.click(within(customRow).getByRole("button", { name: "set_as_default_role" }));
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "confirm" })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/roles/{role_id}/set-default/", {
        params: { path: { role_id: "custom" } }
      })
    );
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

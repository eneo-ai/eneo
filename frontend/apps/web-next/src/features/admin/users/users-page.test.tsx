// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("role_id=custom")
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("./user-editor", () => ({ UserEditorDialog: () => null }));

import { AdminUsersPage } from "./users-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("filters users by the selected role and can return to all users", async () => {
  get.mockImplementation((path: string) =>
    path === "/api/v1/roles/"
      ? ok({
          roles: { items: [{ id: "custom", name: "Manager", permissions: [] }] },
          predefined_roles: { items: [] }
        })
      : ok({
          items: [],
          metadata: { page: 1, total_pages: 1, counts: {}, has_next: false, has_previous: false }
        })
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AdminUsersPage />
    </QueryClientProvider>
  );
  await waitFor(() =>
    expect(get).toHaveBeenCalledWith("/api/v1/admin/users/", {
      params: {
        query: {
          page: 1,
          page_size: 100,
          search_email: undefined,
          state_filter: "active",
          role_id: "custom"
        }
      }
    })
  );
  expect(await screen.findByText("Manager")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "roles_clear_filter" }));
  await waitFor(() =>
    expect(get).toHaveBeenCalledWith("/api/v1/admin/users/", {
      params: {
        query: {
          page: 1,
          page_size: 100,
          search_email: undefined,
          state_filter: "active",
          role_id: undefined
        }
      }
    })
  );
});

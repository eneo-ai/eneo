// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";

const get = vi.hoisted(() => vi.fn());
const searchParams = vi.hoisted(() => ({ value: "role_id=custom" }));
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(searchParams.value)
}));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({ user: { id: "me" } })
}));
vi.mock("./user-editor", () => ({ UserEditorDialog: () => null }));

import { AdminUsersPage } from "./users-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

const users = [
  {
    id: "u1",
    email: "anna.lind@kommun.se",
    username: "anna.lind",
    used_tokens: 0,
    email_verified: true,
    quota_limit: null,
    is_active: true,
    state: "active",
    roles: [{ id: "custom", name: "Manager", permissions: [] }],
    user_groups: []
  },
  {
    id: "u2",
    email: "per.berg@kommun.se",
    username: null,
    used_tokens: 0,
    email_verified: true,
    quota_limit: null,
    is_active: true,
    state: "invited",
    roles: [],
    user_groups: []
  }
];

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {}
  }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  searchParams.value = "role_id=custom";
});

function renderPage(items: unknown[] = []) {
  get.mockImplementation((path: string) =>
    path === "/api/v1/roles/"
      ? ok({
          roles: { items: [{ id: "custom", name: "Manager", permissions: [] }] },
          predefined_roles: { items: [] }
        })
      : ok({
          items,
          metadata: {
            page: 1,
            total_pages: 1,
            total_count: items.length,
            counts: { active: 1, inactive: 3 },
            has_next: false,
            has_previous: false
          }
        })
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <QueryClientProvider client={client}>
        <AdminUsersPage />
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}

it("filters users by the selected role and can return to all users", async () => {
  renderPage();
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
  fireEvent.click(screen.getByRole("button", { name: "Visa alla användare" }));
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

it("lists users with avatar, roles, status and a named row menu", async () => {
  searchParams.value = "";
  renderPage(users);

  const table = await screen.findByRole("table", { name: "Aktiva användare" });
  const [, anna, per] = within(table).getAllByRole("row");
  expect(within(anna!).getByText("anna.lind")).toBeTruthy();
  expect(within(anna!).getByText("anna.lind@kommun.se")).toBeTruthy();
  expect(within(anna!).getByTitle("Manager")).toBeTruthy();
  expect(within(anna!).getByText("Aktiv")).toBeTruthy();
  expect(
    within(anna!).getByRole("button", { name: "Fler åtgärder för anna.lind@kommun.se" })
  ).toBeTruthy();
  // Without a username the email is the name.
  expect(within(per!).getByText("per.berg@kommun.se")).toBeTruthy();
  expect(within(per!).getByText("Inbjuden")).toBeTruthy();

  expect(screen.getByRole("heading", { level: 1, name: "Användare" })).toBeTruthy();
  expect(screen.getByRole("textbox", { name: "Sök användare på e-post" })).toBeTruthy();
  expect(screen.getByText("2 användare")).toBeTruthy();
  await expectNoAxeViolations(document.body);
});

it("switches between active and inactive users with the tabs", async () => {
  searchParams.value = "";
  renderPage(users);
  const inactive = await screen.findByRole("tab", { name: "Inaktiva användare 3" });
  expect(
    screen.getByRole("tab", { name: "Aktiva användare 1" }).getAttribute("aria-selected")
  ).toBe("true");

  fireEvent.click(inactive);

  expect(inactive.getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(inactive.id);
  await waitFor(() =>
    expect(get).toHaveBeenCalledWith("/api/v1/admin/users/", {
      params: {
        query: {
          page: 1,
          page_size: 100,
          search_email: undefined,
          state_filter: "inactive",
          role_id: undefined
        }
      }
    })
  );
});

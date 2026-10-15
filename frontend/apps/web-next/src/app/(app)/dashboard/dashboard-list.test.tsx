// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { DashboardList } from "./dashboard-list.client";
import type { Dashboard } from "./queries";

const DASHBOARD = {
  spaces: {
    items: [
      {
        id: "s1",
        name: "Upphandling",
        personal: false,
        organization: false,
        applications: {
          assistants: { items: [{ id: "a1", name: "Upphandlingsassistenten" }] },
          apps: { items: [{ id: "app1", name: "Avtalsanalys" }] }
        }
      },
      {
        id: "empty",
        name: "Tom yta",
        personal: false,
        organization: false,
        applications: { assistants: { items: [] }, apps: { items: [] } }
      },
      {
        id: "p",
        name: "Personal",
        personal: true,
        organization: false,
        default_assistant: { id: "default" },
        applications: { assistants: { items: [] }, apps: { items: [] } }
      }
    ]
  }
} as unknown as Dashboard;

function renderList(dashboard: Dashboard = DASHBOARD) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } }
  });
  queryClient.setQueryData(["dashboard"], dashboard);
  return render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <QueryClientProvider client={queryClient}>
        <h1>Assistenter</h1>
        <DashboardList />
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DashboardList", () => {
  it("shows assistants and apps as cards grouped under space headings", async () => {
    const { container } = renderList();
    const upphandling = screen.getByRole("region", { name: "Upphandling" });
    expect(within(upphandling).getByRole("heading", { level: 2 })).toBeTruthy();
    expect(
      within(upphandling)
        .getByRole("link", { name: "Upphandlingsassistenten, Upphandling" })
        .getAttribute("href")
    ).toBe("/dashboard/a1?tab=chat");
    expect(
      within(upphandling)
        .getByRole("link", { name: "Avtalsanalys, App i Upphandling" })
        .getAttribute("href")
    ).toBe("/dashboard/app/app1");
    expect(screen.queryByRole("region", { name: "Tom yta" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("filters as you type and announces the number of results", async () => {
    renderList();
    fireEvent.change(screen.getByRole("textbox", { name: "Sök assistenter och appar" }), {
      target: { value: "avtal" }
    });
    // Announced through Astryx's persistent polite live region (WCAG 4.1.3).
    await waitFor(() =>
      expect(document.querySelector("[data-astryx-live-region='polite']")?.textContent).toBe(
        "1 träff"
      )
    );
    expect(screen.getByRole("link", { name: "Avtalsanalys, App i Upphandling" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Upphandlingsassistenten/ })).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Sök assistenter och appar" }), {
      target: { value: "zzz" }
    });
    expect(screen.getByRole("heading", { name: "Inga träffar" })).toBeTruthy();
  });

  it("explains an empty catalog", () => {
    renderList({ spaces: { items: [] } } as unknown as Dashboard);
    expect(screen.getByRole("heading", { name: "Inga assistenter än" })).toBeTruthy();
  });
});

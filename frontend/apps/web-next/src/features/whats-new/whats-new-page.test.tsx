// @vitest-environment jsdom
import type { Release } from "@eneo/whats-new";
import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContextProvider } from "@/components/providers/app-context";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("./tour", () => ({ runTour: vi.fn(() => Promise.resolve("unavailable")) }));
const catalog = vi.hoisted(() => ({ releases: [] as Release[] }));
vi.mock("@eneo/whats-new", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/whats-new")>();
  return { ...actual, releases: catalog.releases, latestRelease: () => catalog.releases[0] };
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: { PUT: vi.fn(), DELETE: vi.fn() }
}));

import { TourProvider } from "./tour-provider";
import { WhatsNewPage } from "./whats-new-page";
import { WhatsNewProvider } from "./whats-new-provider";

const restricted: Release = {
  version: "2.3.0",
  date: "2026-10-29",
  entries: [
    {
      id: "websites",
      type: "new",
      area: "knowledge",
      permissions: { allOf: ["websites"] },
      title: { en: "Website news", sv: "Webbplatsnyheter" },
      body: { en: "Website changes.", sv: "Ändringar för webbplatser." }
    }
  ]
};
const general: Release = {
  version: "2.2.0",
  date: "2026-10-07",
  entries: [
    {
      id: "general",
      type: "improved",
      area: "chat",
      title: { en: "General news", sv: "Allmänna nyheter" },
      body: { en: "General changes.", sv: "Allmänna ändringar." }
    }
  ]
};

function newsPage(permissions: Permission[] = []) {
  return (
    <AppContextProvider value={testAppContext({ permissions })}>
      <WhatsNewProvider enabled initialSeen="9.0.0" initialAnnounced="9.0.0">
        <TourProvider>
          <WhatsNewPage title="Nyheter" />
        </TourProvider>
      </WhatsNewProvider>
    </AppContextProvider>
  );
}

beforeEach(() => {
  catalog.releases.splice(0, catalog.releases.length, restricted, general);
});

describe("What's new visible releases", () => {
  it("selects the first visible release and omits empty versions from the picker", async () => {
    const { container } = renderInApp(newsPage());

    expect(screen.queryByRole("button", { name: /^2\.3\.0/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^2\.2\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
    expect(screen.getByRole("heading", { name: "Version 2.2.0" })).toBeTruthy();
    expect(screen.getByText("Allmänna nyheter")).toBeTruthy();
    expect(screen.queryByText("Webbplatsnyheter")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("shows the empty state when none of the releases has visible news", async () => {
    catalog.releases.splice(1);
    const { container } = renderInApp(newsPage());

    expect(screen.getByText("Inga nyheter ännu.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^2\./ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /^Version / })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("omits permission-empty history as well as the latest version", () => {
    catalog.releases.splice(0, catalog.releases.length, general, {
      ...restricted,
      version: "2.1.1"
    });
    renderInApp(newsPage());

    expect(screen.queryByRole("button", { name: /^2\.1\.1/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^2\.2\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
  });

  it("keeps permitted versions selectable", () => {
    renderInApp(newsPage(["websites"]));

    expect(screen.getByRole("button", { name: /^2\.3\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
    fireEvent.click(screen.getByRole("button", { name: /^2\.2\.0/ }));
    expect(screen.getByRole("heading", { name: "Version 2.2.0" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^2\.3\.0/ }));
    expect(screen.getByText("Webbplatsnyheter")).toBeTruthy();
  });

  it("falls back to visible history if the selected version becomes inaccessible", () => {
    const { rerender } = renderInApp(newsPage(["websites"]));
    expect(screen.getByRole("heading", { name: "Version 2.3.0" })).toBeTruthy();

    rerender(newsPage());

    expect(screen.queryByRole("button", { name: /^2\.3\.0/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "Version 2.2.0" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^2\.2\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
  });
});

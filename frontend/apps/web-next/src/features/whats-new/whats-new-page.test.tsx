// @vitest-environment jsdom
import { UNRELEASED, type Release } from "@eneo/whats-new";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppContextProvider } from "@/components/providers/app-context";
import { sessionKeys } from "@/lib/api/session";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("./tour", () => ({ runTour: vi.fn(() => Promise.resolve("unavailable")) }));
const catalog = vi.hoisted(() => ({ releases: [] as Release[] }));
vi.mock("@eneo/whats-new", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/whats-new")>();
  return {
    ...actual,
    // The test build is no release candidate: it lists the test's catalog as authored.
    releasesForVersion: () => catalog.releases,
    // As the real one, over the test's catalog: the unreleased block is never the latest.
    latestRelease: (list = catalog.releases) => actual.latestRelease(list)
  };
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: { PUT: vi.fn(), DELETE: vi.fn() }
}));

import { runTour } from "./tour";
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
const upcoming: Release = {
  version: UNRELEASED,
  entries: [
    {
      id: "planned",
      type: "new",
      area: "spaces",
      title: { en: "Planned news", sv: "Planerade nyheter" },
      body: { en: "Planned changes.", sv: "Planerade ändringar." },
      showMe: { href: "/spaces", anchor: "spaces" }
    }
  ]
};

function newsPage(permissions: Permission[] = []) {
  return (
    <AppContextProvider value={testAppContext({ permissions })}>
      <WhatsNewProvider>
        <TourProvider>
          <WhatsNewPage title="Nyheter" />
        </TourProvider>
      </WhatsNewProvider>
    </AppContextProvider>
  );
}

/** The news page over markers past every release: all seen and announced. */
function renderNewsPage(permissions?: Permission[]) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(sessionKeys.whatsNew, {
    seen_version: "9.0.0",
    announced_version: "9.0.0"
  });
  return renderInApp(newsPage(permissions), { queryClient });
}

beforeEach(() => {
  catalog.releases.splice(0, catalog.releases.length, restricted, general);
});

describe("What's new visible releases", () => {
  it("selects the first visible release and omits empty versions from the picker", async () => {
    const { container } = renderNewsPage();

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
    const { container } = renderNewsPage();

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
    renderNewsPage();

    expect(screen.queryByRole("button", { name: /^2\.1\.1/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^2\.2\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
  });

  it("keeps permitted versions selectable", () => {
    renderNewsPage(["websites"]);

    expect(screen.getByRole("button", { name: /^2\.3\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
    fireEvent.click(screen.getByRole("button", { name: /^2\.2\.0/ }));
    expect(screen.getByRole("heading", { name: "Version 2.2.0" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^2\.3\.0/ }));
    expect(screen.getByText("Webbplatsnyheter")).toBeTruthy();
  });

  it("falls back to visible history if the selected version becomes inaccessible", () => {
    const { rerender } = renderNewsPage(["websites"]);
    expect(screen.getByRole("heading", { name: "Version 2.3.0" })).toBeTruthy();

    rerender(newsPage());

    expect(screen.queryByRole("button", { name: /^2\.3\.0/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "Version 2.2.0" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^2\.2\.0/ }).getAttribute("aria-pressed")).toBe(
      "true"
    );
  });

  it("opens on the unreleased block as the upcoming release, never read or new", async () => {
    catalog.releases.splice(0, catalog.releases.length, upcoming, general);
    const { container } = renderNewsPage();

    expect(screen.getByRole("button", { name: "Kommande" }).getAttribute("aria-pressed")).toBe(
      "true"
    );
    expect(screen.getByRole("heading", { name: "Kommande version" })).toBeTruthy();
    expect(screen.getByText("Klara ändringar som ännu inte ingår i någon version.")).toBeTruthy();
    expect(screen.queryByText("Läst")).toBeNull();
    expect(screen.queryByText("Nytt för dig")).toBeNull();
    expect(screen.queryByText(UNRELEASED)).toBeNull();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Visa mig de nya funktionerna" }));
    await waitFor(() =>
      expect(runTour).toHaveBeenCalledWith(
        upcoming.entries,
        "sv",
        expect.objectContaining({ version: "Kommande" }),
        expect.any(Function),
        expect.any(AbortSignal)
      )
    );
  });
});

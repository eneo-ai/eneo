// @vitest-environment jsdom
import { latestRelease, visibleEntries } from "@eneo/whats-new";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import { WhatsNewBanner } from "./release-banner";
import { TourProvider } from "./tour-provider";
import { WhatsNewProvider } from "./whats-new-provider";

vi.mock("next/navigation", () => import("@/test/navigation"));
const put = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { PUT: put, DELETE: vi.fn() } }));
// The tour itself needs the real pages; here it reports them as unavailable.
vi.mock("./tour", () => ({ runTour: vi.fn(() => Promise.resolve("unavailable")) }));

const latest = latestRelease()!;
const count = visibleEntries(latest, false).length;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** The banner, found by its title (the harness has live regions of its own). */
const banner = () => screen.queryByText("Nytt i Eneo")?.closest('[role="status"]') ?? null;

function renderBanner(announced: string | null = null) {
  put.mockImplementation(() =>
    Promise.resolve({
      data: { announced_version: latest.version },
      response: new Response("{}", { status: 200 })
    })
  );
  return renderInApp(
    <WhatsNewProvider enabled initialSeen={null} initialAnnounced={announced}>
      <TourProvider>
        <WhatsNewBanner />
      </TourProvider>
    </WhatsNewProvider>
  );
}

describe("WhatsNewBanner", () => {
  it("tells about the release once, without blocking the page", async () => {
    const { container } = renderBanner();

    expect(banner()?.textContent).toContain(`${count} nyheter sedan du var här senast.`);
    expect(screen.getByRole("link", { name: `Alla ${count} nyheter` }).getAttribute("href")).toBe(
      "/whats-new"
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    // Recorded as announced when shown: the next visit has no banner.
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/whats-new/announced/", {
        body: { version: latest.version }
      })
    );
    await expectNoAxeViolations(container);
  });

  it("can be dismissed", async () => {
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Stäng nyhetsbannern" }));

    await waitFor(() => expect(banner()).toBeNull());
  });

  it("offers the tour and falls back to the Nyheter page when it cannot run", async () => {
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Visa mig de nya funktionerna" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/whats-new"));
    expect(banner()).toBeNull();
  });

  it("stays away once the release has been announced", () => {
    renderBanner(latest.version);

    expect(banner()).toBeNull();
    expect(put).not.toHaveBeenCalled();
  });

  it("renders nothing without the app layout's providers", () => {
    renderInApp(<WhatsNewBanner />);

    expect(banner()).toBeNull();
  });
});

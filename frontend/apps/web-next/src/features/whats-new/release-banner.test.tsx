// @vitest-environment jsdom
import { latestRelease, visibleEntries } from "@eneo/whats-new";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "@/lib/toast";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { sessionKeys } from "@/lib/api/session";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { WhatsNewBanner } from "./release-banner";
import { TourProvider } from "./tour-provider";
import { WhatsNewProvider } from "./whats-new-provider";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const put = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { PUT: put, DELETE: vi.fn() } }));
// The tour itself needs the real pages; here it reports them as unavailable.
vi.mock("./tour", () => ({ runTour: vi.fn(() => Promise.resolve("unavailable")) }));
// The tour button exists only for a release with a `showMe` entry; whether the
// catalog's latest release has one changes from release to release, so the
// test guarantees one instead of depending on the current notes.
vi.mock("@eneo/whats-new", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/whats-new")>();
  const release = actual.latestRelease()!;
  const tourEntry = actual.visibleEntries(release, () => false)[0]!;
  const withTour = {
    ...release,
    entries: release.entries.map((entry) =>
      entry === tourEntry
        ? { ...entry, showMe: { href: "/whats-new", anchor: "whats-new" } }
        : entry
    )
  };
  return { ...actual, latestRelease: () => withTour };
});

const latest = latestRelease()!;
const count = visibleEntries(latest, () => false).length;

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

/** Where this browser keeps the "Later" reminder for the test user and the latest release. */
const reminderKey = `eneo:whats-new:remind-after:user-1:${latest.version}`;
const DAY_MS = 24 * 60 * 60 * 1000;

/** The banner, found by its title (the harness has live regions of its own). */
const banner = () => screen.queryByText("Nytt i Eneo")?.closest('[role="status"]') ?? null;

function renderBanner(
  announced: string | null = null,
  seen: string | null = null,
  appContext = testAppContext()
) {
  put.mockImplementation(() =>
    Promise.resolve({
      data: { seen_version: null, announced_version: latest.version },
      response: new Response("{}", { status: 200 })
    })
  );
  const queryClient = testQueryClient();
  queryClient.setQueryData(sessionKeys.whatsNew, {
    seen_version: seen,
    announced_version: announced
  });
  return renderInApp(
    <WhatsNewProvider>
      <TourProvider>
        <WhatsNewBanner />
      </TourProvider>
    </WhatsNewProvider>,
    { queryClient, appContext }
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

  it("comes back a day later when put off, until the release is read", async () => {
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Senare" }));

    await waitFor(() => expect(banner()).toBeNull());
    const remindAt = Number(localStorage.getItem(reminderKey));
    expect(remindAt - Date.now()).toBeGreaterThan(DAY_MS - 60_000);
    expect(remindAt - Date.now()).toBeLessThanOrEqual(DAY_MS);

    // The next app load, before the reminder is due: no banner.
    cleanup();
    renderBanner(latest.version);
    expect(banner()).toBeNull();

    // Once it is due, the banner is back and recorded again, which uses the reminder up.
    cleanup();
    put.mockClear();
    localStorage.setItem(reminderKey, String(Date.now() - 1));
    renderBanner(latest.version);
    expect(banner()).not.toBeNull();
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/whats-new/announced/", {
        body: { version: latest.version }
      })
    );
    expect(localStorage.getItem(reminderKey)).toBeNull();
  });

  it("drops a due reminder once the release has been read", () => {
    localStorage.setItem(reminderKey, String(Date.now() - 1));
    renderBanner(latest.version, latest.version);

    expect(banner()).toBeNull();
    expect(put).not.toHaveBeenCalled();
    expect(localStorage.getItem(reminderKey)).toBeNull();
  });

  it("stays open and says so when the reminder cannot be saved", async () => {
    const error = vi.spyOn(toast, "error");
    renderBanner();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });

    fireEvent.click(screen.getByRole("button", { name: "Senare" }));

    expect(error).toHaveBeenCalledWith("Kunde inte spara påminnelsen. Försök igen.");
    expect(banner()).not.toBeNull();
  });

  it("offers the tour and falls back to the Nyheter page when it cannot run", async () => {
    renderBanner();

    fireEvent.click(screen.getByRole("button", { name: "Visa mig de nya funktionerna" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/whats-new"));
    expect(banner()).toBeNull();
  });

  it("records the release without telling an account created after it", async () => {
    expect(latest.date).toBeDefined();
    renderBanner(null, null, testAppContext({ user: { created_at: "2999-01-01T00:00:00Z" } }));

    expect(banner()).toBeNull();
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/whats-new/announced/", {
        body: { version: latest.version }
      })
    );
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

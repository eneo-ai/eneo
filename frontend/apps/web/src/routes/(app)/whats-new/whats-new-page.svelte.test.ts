// Render the actual route with its real translations, release data and controls.
// Only the authenticated shell/persistence/navigation boundaries are replaced.
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { releases, releasesForVersion, visibleEntries, type Locale } from "@eneo/whats-new";
import { getLocale, overwriteGetLocale } from "$lib/paraglide/runtime";
import { m } from "$lib/paraglide/messages";
import { announcementSummary } from "$lib/features/whats-new/announcement";
import { tourSteps } from "$lib/features/whats-new/tour";
import "../../../app.css";

const state = vi.hoisted(() => ({
  admin: false,
  installedVersion: "2.3.0",
  markSeen: vi.fn().mockResolvedValue(undefined),
  markAnnounced: vi.fn().mockResolvedValue(undefined),
  start: vi.fn().mockResolvedValue("completed")
}));

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    user: { hasPermission: () => state.admin },
    settings: { developer_tools_available: false }
  })
}));
vi.mock("$app/state", () => ({
  page: { state: {}, url: new URL("https://eneo.test/whats-new") }
}));
vi.mock("$app/navigation", () => ({
  goto: vi.fn(),
  preloadData: vi.fn(),
  replaceState: vi.fn(),
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn()
}));
vi.mock("$lib/features/whats-new/whatsNewStore", async () => {
  const { writable } = await import("svelte/store");
  return {
    getWhatsNewStore: () => ({
      releases: releasesForVersion(state.installedVersion),
      markLatestSeen: state.markSeen,
      seenVersion: writable(null),
      resetState: vi.fn(),
      enabled: writable(true),
      pendingAnnouncement: () => releasesForVersion(state.installedVersion)[0],
      markLatestAnnounced: state.markAnnounced
    })
  };
});
vi.mock("$lib/features/whats-new/tour", async (importOriginal) => {
  const original = await importOriginal<typeof import("$lib/features/whats-new/tour")>();
  const { writable } = await import("svelte/store");
  return { ...original, getWhatsNewTour: () => ({ start: state.start, running: writable(false) }) };
});

import WhatsNewPage from "./+page.svelte";
import WhatsNewAnnouncement from "$lib/features/whats-new/WhatsNewAnnouncement.svelte";

const release = releases.find((release) => release.version === "2.3.0")!;

const resolveLocale = getLocale;
afterEach(() => {
  overwriteGetLocale(resolveLocale);
  document.documentElement.removeAttribute("data-theme");
});

beforeEach(async () => {
  vi.clearAllMocks();
  state.installedVersion = "2.3.0";
  document.documentElement.dataset.theme = "light";
  await page.viewport(1280, 900);
});

for (const locale of ["sv", "en"] satisfies Locale[]) {
  describe(locale, () => {
    it("announces the four main workflows in a usable dialog", async () => {
      state.admin = false;
      overwriteGetLocale(() => locale);
      render(WhatsNewAnnouncement);
      const dialog = page.getByRole("dialog");
      await expect.element(dialog).toBeVisible();
      expect([...dialog.element().querySelectorAll("h3")].map((node) => node.textContent)).toEqual(
        announcementSummary(release, false).entries.map((entry) => entry.title[locale])
      );
      expect(state.markAnnounced).toHaveBeenCalledOnce();
      for (const width of [1280, 320]) {
        await page.viewport(width, 900);
        const element = dialog.element();
        expect(element.scrollWidth).toBeLessThanOrEqual(element.clientWidth);
        await page.screenshot({ path: `__screenshots__/announcement-${locale}-${width}.png` });
      }
      await page
        .getByRole("button", { name: m.whats_new_announcement_later(), exact: true })
        .click();
      await expect.element(dialog).not.toBeInTheDocument();
    });

    for (const admin of [false, true]) {
      it(`shows the release for ${admin ? "administrators" : "regular users"}`, async () => {
        state.admin = admin;
        overwriteGetLocale(() => locale);
        const screen = render(WhatsNewPage);
        await page.getByRole("button", { name: /^2\.3\.0/ }).click();
        const entries = visibleEntries(release, admin);
        await expect
          .element(page.getByRole("heading", { name: entries[0].title[locale], exact: true }))
          .toBeVisible();
        expect(
          [...screen.container.querySelectorAll("h3")].map((node) => node.textContent)
        ).toEqual(entries.map((entry) => entry.title[locale]));
        expect(state.markSeen).toHaveBeenCalledOnce();
        for (const entry of entries) {
          for (const alias of entry.aliases ?? []) {
            expect(screen.container.querySelector(`#${alias}`)?.closest("li")?.id).toBe(entry.id);
          }
        }
        const summary = announcementSummary(release, admin);
        expect(summary.entries.map((entry) => entry.id)).toEqual([
          "file-creation-progress",
          "file-analysis-trace",
          "compute-and-charts",
          "conversation-uploads"
        ]);
        expect(summary.total).toBe(entries.length);
        expect(summary.more).toBe(entries.length - 4);
        await page.screenshot({
          path: `__screenshots__/whats-new-${locale}-${admin ? "admin" : "user"}.png`
        });

        await page.getByRole("switch", { name: m.whats_new_filter_show_me() }).click();
        expect(screen.container.querySelectorAll("h3")).toHaveLength(
          entries.filter((entry) => entry.showMe).length
        );
        if (admin) {
          await page
            .getByRole("button", { name: m.whats_new_show_me(), exact: true })
            .first()
            .click();
          expect(state.start).toHaveBeenLastCalledWith(
            [tourSteps(release, true, locale)[0]],
            expect.objectContaining({
              version: m.whats_new_tour_version({ version: release.version })
            })
          );
          await page.getByRole("button", { name: m.whats_new_tour_start() }).click();
          expect(state.start).toHaveBeenLastCalledWith(
            tourSteps(release, true, locale),
            expect.any(Object)
          );
        } else {
          await expect
            .element(page.getByText(m.whats_new_no_match(), { exact: true }))
            .toBeVisible();
          await page.getByRole("button", { name: m.whats_new_clear_filters() }).click();
          expect(screen.container.querySelectorAll("h3")).toHaveLength(entries.length);
        }
      });
    }

    it("filters by area and fits a narrow screen", async () => {
      state.admin = true;
      overwriteGetLocale(() => locale);
      await page.viewport(320, 800);
      const screen = render(WhatsNewPage);
      await page.getByRole("button", { name: /^2\.3\.0/ }).click();
      await page.getByRole("button", { name: m.whats_new_area_admin(), exact: true }).click();
      expect(screen.container.querySelectorAll("h3")).toHaveLength(
        release.entries.filter((entry) => entry.area === "admin").length
      );
      const content = screen.container.querySelector<HTMLElement>("#content")!;
      expect(content.scrollWidth).toBeLessThanOrEqual(content.clientWidth);
      await page.screenshot({ path: `__screenshots__/whats-new-${locale}-narrow.png` });
      await page.getByRole("button", { name: m.whats_new_filter_all(), exact: true }).click();
      expect(screen.container.querySelectorAll("h3")).toHaveLength(release.entries.length);
      await page.getByRole("button", { name: /^2\.2\.0/ }).click();
      expect(screen.container.querySelector("#release-2\\.2\\.0")).not.toBeNull();
    });
  });
}

it("shows the installed RC in both the announcement and release picker", async () => {
  state.installedVersion = "2.3.0-rc.1";
  state.admin = false;
  overwriteGetLocale(() => "en");
  const announcement = render(WhatsNewAnnouncement);
  await expect.element(page.getByRole("dialog")).toBeVisible();
  await expect.element(page.getByText("Version 2.3.0-rc.1", { exact: true })).toBeVisible();
  await page.screenshot({ path: "__screenshots__/announcement-rc1.png" });
  await announcement.unmount();
  render(WhatsNewPage);
  await expect
    .element(page.getByRole("heading", { name: "Version 2.3.0-rc.1", exact: true }))
    .toBeVisible();
  await expect.element(page.getByRole("button", { name: /^2\.3\.0-rc\.1/ })).toBeVisible();
});

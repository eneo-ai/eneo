// Render the actual route with its real translations, release data and controls.
// Only the authenticated shell/persistence/navigation boundaries are replaced.
import { hasPermission } from "$lib/core/hasPermission";
import type { Permission } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  UNRELEASED,
  compareVersions,
  latestRelease,
  releases,
  visibleEntries,
  type Locale,
  type Release
} from "@eneo/whats-new";
import { getLocale, localizeHref, overwriteGetLocale } from "$lib/paraglide/runtime";
import { m } from "$lib/paraglide/messages";
import { announcementSummary } from "$lib/features/whats-new/announcement";
import { tourSteps } from "$lib/features/whats-new/tour";
import "../../../app.css";

const state = vi.hoisted(() => ({
  admin: false,
  permissions: [
    "personal_chat",
    "assistants",
    "file_creation",
    "file_analysis",
    "compute",
    "charts",
    "modules"
  ] as Permission[],
  enabled: true,
  installedVersion: "2.3.0",
  seen: null as string | null,
  markSeen: vi.fn().mockResolvedValue(undefined),
  markAnnounced: vi.fn().mockResolvedValue(undefined),
  snooze: vi.fn().mockResolvedValue(undefined),
  start: vi.fn().mockResolvedValue("completed")
}));

const can = (required: Parameters<ReturnType<typeof hasPermission>>[0]) =>
  hasPermission({
    roles: [
      {
        id: "role",
        name: "Custom",
        permissions: [...state.permissions, ...(state.admin ? ["admin" as const] : [])]
      }
    ]
  })(required);

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    user: { id: "test-user", email: "user@example.com", hasPermission: can },
    settings: { developer_tools_available: false },
    featureFlags: { showHelpCenter: false },
    environment: {},
    versions: { frontend: "2.3.0", backend: "2.3.0", client: "test" }
  })
}));
vi.mock("$app/stores", async () => {
  const { readable } = await import("svelte/store");
  return { page: readable({ url: new URL("https://eneo.test/news") }) };
});
vi.mock("$app/state", () => ({
  page: { state: {}, url: new URL("https://eneo.test/news") }
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
      releases: bundled(state.installedVersion),
      markLatestSeen: state.markSeen,
      seenVersion: writable(state.seen),
      resetState: vi.fn(),
      enabled: writable(state.enabled),
      hasUnseen: writable(state.enabled),
      pendingAnnouncement: () => bundled(state.installedVersion)[0],
      markLatestAnnounced: state.markAnnounced,
      snoozeLatest: state.snooze
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

// These tests pin the 2.3 notes. On develop they sit in the unreleased block
// until the final 2.3 release is ported, so find them by content and bundle
// them the way a 2.3 image does: under the installed identity, above history.
const pinned = releases.find((release) =>
  release.entries.some((entry) => entry.id === "assistant-attachment-modes")
)!;
const release: Release = { ...pinned, version: "2.3.0" };
function bundled(installed: string): Release[] {
  const history = releases.filter(
    (other) => other.date && compareVersions(other.version, release.version) < 0
  );
  const { date: _date, ...notes } = release;
  if (installed.startsWith("develop-")) return [{ ...notes, version: UNRELEASED }, ...history];
  return [installed === release.version ? release : { ...notes, version: installed }, ...history];
}

const resolveLocale = getLocale;
afterEach(() => {
  overwriteGetLocale(resolveLocale);
  document.documentElement.removeAttribute("data-theme");
});

beforeEach(async () => {
  vi.clearAllMocks();
  state.admin = false;
  state.permissions = [
    "personal_chat",
    "assistants",
    "file_creation",
    "file_analysis",
    "compute",
    "charts",
    "modules"
  ];
  state.installedVersion = "2.3.0";
  state.seen = null;
  state.enabled = true;
  document.documentElement.dataset.theme = "light";
  await page.viewport(1280, 900);
});

for (const locale of ["sv", "en"] satisfies Locale[]) {
  describe(locale, () => {
    it("dismisses this version explicitly without scheduling a reminder", async () => {
      overwriteGetLocale(() => locale);
      render(WhatsNewAnnouncement);
      const dialog = page.getByRole("dialog");
      await expect.element(dialog).toBeVisible();
      expect(dialog.element().querySelector('[data-slot="dialog-close"]')).toBeNull();
      await page
        .getByRole("button", { name: m.whats_new_announcement_dismiss(), exact: true })
        .click();
      await expect.element(dialog).not.toBeInTheDocument();
      expect(state.snooze).not.toHaveBeenCalled();
      expect(state.markSeen).not.toHaveBeenCalled();
    });

    it("keeps the dialog open when saving the reminder fails", async () => {
      overwriteGetLocale(() => locale);
      state.snooze.mockRejectedValueOnce(new Error("offline"));
      render(WhatsNewAnnouncement);
      await page
        .getByRole("button", { name: m.whats_new_announcement_later(), exact: true })
        .click();
      await expect.element(page.getByRole("dialog")).toBeVisible();
      expect(state.snooze).toHaveBeenCalledOnce();
    });

    it("shares account navigation and marks news as the current page", async () => {
      overwriteGetLocale(() => locale);
      render(WhatsNewPage);
      const navigation = page.getByRole("navigation", { name: m.account_and_settings() });
      for (const [name, href] of [
        [m.my_account(), "/account"],
        [m.integrations(), "/account/integrations"],
        [m.api_keys(), "/account/api-keys"],
        [m.whats_new(), "/news"]
      ]) {
        await expect
          .element(navigation.getByRole("link", { name, exact: href !== "/news" }))
          .toHaveAttribute("href", localizeHref(href));
      }
      await expect
        .element(navigation.getByRole("link", { name: m.whats_new() }))
        .toHaveAttribute("aria-current", "page");
      await expect.element(navigation.getByText(m.whats_new_unseen())).toBeInTheDocument();
    });

    it("uses the full mobile width while account navigation is closed", async () => {
      overwriteGetLocale(() => locale);
      await page.viewport(320, 800);
      const screen = render(WhatsNewPage);
      const toggle = page.getByRole("button", { name: m.account_and_settings(), exact: true });
      await expect.element(toggle).toBeVisible();
      const content = screen.container.querySelector<HTMLElement>("#content")!;
      expect(content.getBoundingClientRect().width).toBeGreaterThanOrEqual(319);
      const navigation = page.getByRole("navigation", { name: m.account_and_settings() });
      await expect.element(navigation).not.toBeInTheDocument();
      await toggle.click();
      await expect.element(navigation).toBeVisible();
      const newsLink = navigation.getByRole("link", { name: m.whats_new() });
      // Keep the component harness on its test URL while exercising menu dismissal.
      newsLink
        .element()
        .addEventListener("click", (event) => event.preventDefault(), { once: true });
      await newsLink.click();
      await expect.element(navigation).not.toBeInTheDocument();
      expect(content.getBoundingClientRect().width).toBeGreaterThanOrEqual(319);
    });

    it("shows only permitted features on the page and in the dialog", async () => {
      state.permissions = ["personal_chat", "file_creation"];
      overwriteGetLocale(() => locale);
      const screen = render(WhatsNewPage);
      const assistant = release.entries.find((entry) => entry.id === "assistant-attachment-modes")!;
      const documents = release.entries.find((entry) => entry.id === "file-creation-progress")!;
      const analysis = release.entries.find((entry) => entry.id === "file-analysis-trace")!;
      await expect
        .element(page.getByRole("heading", { name: documents.title[locale], exact: true }))
        .toBeVisible();
      await expect
        .element(page.getByRole("heading", { name: assistant.title[locale], exact: true }))
        .not.toBeInTheDocument();
      await expect
        .element(page.getByRole("heading", { name: analysis.title[locale], exact: true }))
        .not.toBeInTheDocument();
      await expect
        .element(page.getByRole("button", { name: m.whats_new_area_assistants(), exact: true }))
        .not.toBeInTheDocument();
      await screen.unmount();
      render(WhatsNewAnnouncement);
      const dialog = page.getByRole("dialog");
      await expect.element(dialog).toBeVisible();
      expect([...dialog.element().querySelectorAll("h3")].map((node) => node.textContent)).toEqual(
        announcementSummary(release, can).entries.map((entry) => entry.title[locale])
      );
      expect(dialog.element().textContent).not.toContain(assistant.title[locale]);
      expect(dialog.element().textContent).not.toContain(analysis.title[locale]);
      await page
        .getByRole("button", { name: m.whats_new_announcement_dismiss(), exact: true })
        .click();
    });

    it("announces the four main workflows in a usable dialog", async () => {
      state.admin = false;
      overwriteGetLocale(() => locale);
      render(WhatsNewAnnouncement);
      const dialog = page.getByRole("dialog");
      await expect.element(dialog).toBeVisible();
      expect([...dialog.element().querySelectorAll("h3")].map((node) => node.textContent)).toEqual(
        announcementSummary(release, can).entries.map((entry) => entry.title[locale])
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
      expect(state.snooze).toHaveBeenCalledOnce();
    });

    for (const admin of [false, true]) {
      it(`shows the release for ${admin ? "administrators" : "regular users"}`, async () => {
        state.admin = admin;
        overwriteGetLocale(() => locale);
        const screen = render(WhatsNewPage);
        await page.getByRole("button", { name: /^2\.3\.0/ }).click();
        const entries = visibleEntries(release, can);
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
        const summary = announcementSummary(release, can);
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
            [tourSteps(release, can, locale)[0]],
            expect.objectContaining({
              version: m.whats_new_tour_version({ version: release.version })
            })
          );
          await page.getByRole("button", { name: m.whats_new_tour_start() }).click();
          expect(state.start).toHaveBeenLastCalledWith(
            tourSteps(release, can, locale),
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
      const entries = visibleEntries(release, can);
      overwriteGetLocale(() => locale);
      await page.viewport(320, 800);
      const screen = render(WhatsNewPage);
      await page.getByRole("button", { name: /^2\.3\.0/ }).click();
      await page.getByRole("button", { name: m.whats_new_area_admin(), exact: true }).click();
      expect(screen.container.querySelectorAll("h3")).toHaveLength(
        entries.filter((entry) => entry.area === "admin").length
      );
      const content = screen.container.querySelector<HTMLElement>("#content")!;
      expect(content.scrollWidth).toBeLessThanOrEqual(content.clientWidth);
      await page.screenshot({ path: `__screenshots__/whats-new-${locale}-narrow.png` });
      await page.getByRole("button", { name: m.whats_new_filter_all(), exact: true }).click();
      expect(
        Array.from(screen.container.querySelectorAll("h3"), (heading) => heading.textContent)
      ).toEqual(entries.map((entry) => entry.title[locale]));
      await page.getByRole("button", { name: /^2\.2\.0/ }).click();
      expect(screen.container.querySelector("#release-2\\.2\\.0")).not.toBeNull();
    });
  });
}

it("hides news in the account sidebar when the organisation disables it", async () => {
  state.enabled = false;
  render(WhatsNewPage);
  const navigation = page.getByRole("navigation", { name: m.account_and_settings() });
  await expect.element(navigation.getByRole("link", { name: m.my_account() })).toBeVisible();
  await expect
    .element(navigation.getByRole("link", { name: m.whats_new() }))
    .not.toBeInTheDocument();
  await expect.element(navigation.getByText(m.whats_new_unseen())).not.toBeInTheDocument();
});

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

it("shows unreleased notes on development builds as the upcoming release", async () => {
  state.installedVersion = "develop-0123456789ab";
  state.seen = latestRelease()!.version;
  overwriteGetLocale(() => "en");
  render(WhatsNewPage);
  await expect
    .element(page.getByRole("heading", { name: m.whats_new_unreleased(), exact: true }))
    .toBeVisible();
  await expect
    .element(page.getByText(m.whats_new_unreleased_hint(), { exact: true }))
    .toBeVisible();
  await expect
    .element(page.getByRole("button", { name: m.whats_new_upcoming(), exact: true }))
    .toHaveAttribute("aria-pressed", "true");
  await expect.element(page.getByText(m.whats_new_new_for_you())).not.toBeInTheDocument();
  await expect.element(page.getByText(m.whats_new_read(), { exact: true })).not.toBeInTheDocument();
  await expect.element(page.getByText(UNRELEASED, { exact: true })).not.toBeInTheDocument();
});

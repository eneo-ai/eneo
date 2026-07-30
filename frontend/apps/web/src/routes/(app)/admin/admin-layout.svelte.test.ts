import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { readable } from "svelte/store";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../app.css";

vi.mock("$app/stores", () => ({
  page: readable({
    url: new URL("http://localhost/admin/storage")
  })
}));

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    tenant: {
      display_name: "Test tenant"
    },
    user: {
      id: "user-1"
    },
    settings: {
      using_templates: false
    },
    featureFlags: {
      showHelpCenter: false
    },
    environment: {
      baseUrl: "http://localhost",
      helpCenterUrl: "https://example.com/help"
    },
    versions: {
      frontend: "1.0.0",
      backend: "1.0.0",
      client: "1.0.0"
    }
  })
}));

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>(
    {},
    {
      get: (_target, key) => () => String(key)
    }
  )
}));

vi.mock("$lib/paraglide/runtime", () => ({
  deLocalizeHref: (href: string) => href,
  localizeHref: (href: string) => href
}));

import AdminLayout from "./+layout.svelte";

describe("admin layout navigation", () => {
  beforeEach(async () => {
    await page.viewport(375, 800);
  });

  test("opens the mobile drawer and restores focus to its localized trigger", async () => {
    render(AdminLayout);

    const trigger = page.getByRole("button", { name: "admin_nav_toggle" });
    await expect.element(trigger).toBeVisible();
    const triggerRect = trigger.element().getBoundingClientRect();
    const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
    expect(triggerRect.left).toBeGreaterThanOrEqual(8);
    expect(triggerRect.width).toBeGreaterThanOrEqual(44);
    expect(triggerRect.height).toBeGreaterThanOrEqual(44);
    expect(triggerRect.width).toBe(triggerRect.height);
    expect(triggerRect.top + triggerRect.height / 2).toBeCloseTo((4.25 * rootFontSize) / 2);
    expect({
      left: triggerRect.left,
      top: triggerRect.top,
      width: triggerRect.width,
      height: triggerRect.height
    }).toEqual({ left: 9.375, top: 9.375, width: 45, height: 45 });

    await trigger.click();

    const drawer = page.getByRole("dialog");
    await expect.element(drawer).toBeVisible();
    await vi.waitFor(() => expect(drawer.element().contains(document.activeElement)).toBe(true));

    const focusableCount = drawer
      .element()
      .querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex="0"]').length;
    for (let index = 0; index <= focusableCount; index += 1) {
      await userEvent.keyboard("{Tab}");
      expect(drawer.element().contains(document.activeElement)).toBe(true);
    }

    await userEvent.keyboard("{Escape}");

    await expect.element(drawer).not.toBeInTheDocument();
    await expect.element(trigger).toHaveFocus();
    expect(trigger.element().className).toContain("focus-visible:ring-3");
  });

  test("closes the mobile drawer when an admin navigation link is activated", async () => {
    render(AdminLayout);

    await page.getByRole("button", { name: "admin_nav_toggle" }).click();

    const drawer = page.getByRole("dialog");
    await expect.element(drawer).toBeVisible();

    const storageLink = page.getByRole("link", { name: "storage_settings_nav" });
    storageLink.element().addEventListener("click", (event) => event.preventDefault(), {
      once: true
    });
    await storageLink.click();

    await expect.element(drawer).not.toBeInTheDocument();
  });

  test("keeps the desktop navigation permanently visible", async () => {
    await page.viewport(1280, 800);
    render(AdminLayout);

    const navigation = page.getByRole("navigation", { name: "admin_nav_aria" });
    const trigger = document.querySelector<HTMLElement>('[data-slot="sidebar-trigger"]');

    await expect.element(navigation).toBeVisible();
    expect(trigger).not.toBeNull();
    expect(getComputedStyle(trigger!).display).toBe("none");
    expect(document.querySelector('[data-slot="sidebar-gap"]')).toBeNull();
    const sidebarRect = navigation.element().parentElement!.getBoundingClientRect();
    const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
    expect(sidebarRect.width).toBe(17 * rootFontSize);

    await userEvent.keyboard("{Control>}b{/Control}");

    await expect.element(navigation).toBeVisible();
    expect(document.querySelector('[data-slot="sidebar-gap"]')).toBeNull();
  });

  test.each([375, 768, 1280, 1920, 3440])(
    "uses the expected navigation mode without page overflow at %ipx",
    async (width) => {
      await page.viewport(width, 800);
      render(AdminLayout);

      const trigger = document.querySelector<HTMLElement>('[data-slot="sidebar-trigger"]');
      expect(trigger).not.toBeNull();

      if (width < 768) {
        expect(getComputedStyle(trigger!).display).not.toBe("none");
        await expect
          .element(page.getByRole("navigation", { name: "admin_nav_aria" }))
          .not.toBeInTheDocument();
      } else {
        expect(getComputedStyle(trigger!).display).toBe("none");
        await expect
          .element(page.getByRole("navigation", { name: "admin_nav_aria" }))
          .toBeVisible();
      }

      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(innerWidth);
    }
  );
});

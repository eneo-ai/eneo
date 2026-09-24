import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import axe from "axe-core";
import { afterEach, describe, expect, test, vi } from "vitest";
import "../../../app.css";

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin"), state: {} }
}));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));
vi.mock("$lib/core/AppContext.js", () => ({
  getAppContext: () => ({
    tenant: { display_name: "Test tenant", show_model_pricing: true },
    updateTenant: vi.fn()
  })
}));
vi.mock("$lib/features/whats-new/whatsNewStore", () => ({
  getWhatsNewStore: () => ({ setEnabled: vi.fn() })
}));
vi.mock("$lib/core/Eneo.js", () => ({ getEneo: () => ({ settings: {} }) }));

import AdminPage from "./+page.svelte";

function renderPage() {
  return render(AdminPage, {
    data: {
      settings: {
        using_templates: false,
        audit_logging_enabled: false,
        provisioning: false,
        whats_new_enabled: true
      }
    } as never
  });
}

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" ");
}

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("organisation settings", () => {
  test("the audit log switch says what stays logged when it is off", async () => {
    renderPage();

    await expect.element(page.getByText("admin_audit_always_logged_note")).toBeVisible();
    const auditSwitch = page.getByRole("switch", { name: "enable_audit_logging" }).element();
    expect(auditSwitch.getAttribute("aria-checked")).toBe("false");
    expect(description(auditSwitch)).toBe(
      "enable_audit_logging_description admin_audit_always_logged_note"
    );
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      renderPage();
      await expect.element(page.getByText("admin_audit_always_logged_note")).toBeVisible();

      const result = await axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
        },
        // The page is rendered without the app shell and its landmarks.
        rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
      });
      expect(result.violations.map((violation) => violation.id)).toEqual([]);
    }
  );
});

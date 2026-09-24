import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { components } from "@eneo/eneo-js";
import axe from "axe-core";
import { tick } from "svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

type CategoryConfig = components["schemas"]["CategoryConfig"];
type ActionConfig = components["schemas"]["ActionConfig"];

const audit = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getActionConfig: vi.fn(),
  updateConfig: vi.fn(),
  updateActionConfig: vi.fn()
}));

vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ audit }) }));

// The tab and its label modules import the catalogue as a namespace, so every
// key has to exist as a named export as well as on `m`.
vi.mock("$lib/paraglide/messages", async () => {
  const { default: en } = await import("../../../../../messages/en.json");
  const message = (key: string) => (params?: Record<string, unknown>) =>
    params ? `${key}(${Object.values(params).join("|")})` : key;
  const keys = Object.keys(en).filter((key) => key !== "$schema");
  return {
    ...Object.fromEntries(keys.map((key) => [key, message(key)])),
    m: new Proxy({}, { get: (_target, key) => message(String(key)) })
  };
});
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import AuditConfigTab from "./AuditConfigTab.svelte";

const categories: CategoryConfig[] = [
  { category: "admin_actions", enabled: true, action_count: 4, example_actions: [] },
  { category: "user_actions", enabled: true, action_count: 1, example_actions: [] }
];

const actions: ActionConfig[] = [
  { action: "space_oversight_joined", category: "admin_actions", enabled: true, mandatory: true },
  { action: "widget_activated", category: "admin_actions", enabled: true, mandatory: true },
  { action: "user_created", category: "admin_actions", enabled: true, mandatory: false },
  { action: "role_modified", category: "admin_actions", enabled: true, mandatory: false },
  { action: "space_member_added", category: "user_actions", enabled: true, mandatory: false }
];

const lockedRow = () => page.getByRole("checkbox", { name: "audit_action_space_oversight_joined" });
const categorySwitch = () => page.getByRole("switch", { name: "audit_category_admin_actions" });

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" ");
}

async function renderExpanded() {
  render(AuditConfigTab);
  await page.getByRole("button", { name: /^audit_category_admin_actions/ }).click();
  await expect.element(lockedRow()).toBeVisible();
  // The list slides open; axe must not measure it half-drawn.
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
}

beforeEach(() => {
  vi.clearAllMocks();
  audit.getConfig.mockResolvedValue({ categories: structuredClone(categories) });
  audit.getActionConfig.mockResolvedValue({ actions: structuredClone(actions) });
  audit.updateConfig.mockResolvedValue({});
  audit.updateActionConfig.mockResolvedValue({});
  delete document.documentElement.dataset.theme;
});

describe("always-logged audit actions", () => {
  test("a locked row stays checked, focusable and described by its visible reason", async () => {
    await renderExpanded();
    const row = lockedRow().element() as HTMLButtonElement;

    expect(row.getAttribute("aria-checked")).toBe("true");
    expect(row.getAttribute("aria-disabled")).toBe("true");
    expect(row.disabled).toBe(false);
    expect(description(row)).toBe("audit_config_always_logged");
    await expect
      .element(page.getByText("audit_config_always_logged", { exact: true }).first())
      .toBeVisible();

    // Checked separately: a click and a key press would cancel each other out.
    row.click();
    await tick();
    expect(row.getAttribute("aria-checked")).toBe("true");

    row.focus();
    await userEvent.keyboard(" ");
    await tick();
    expect(row).toHaveFocus();
    expect(row.getAttribute("aria-checked")).toBe("true");
    expect(page.getByText("audit_config_unsaved_changes").elements()).toHaveLength(0);
  });

  test("the category states how many actions are always logged, also to its switch", async () => {
    await renderExpanded();

    await expect.element(page.getByText("audit_config_always_logged_count(2)")).toBeVisible();
    expect(description(categorySwitch().element())).toBe(
      "audit_config_always_logged_count(2) audit_config_always_logged_help"
    );
    // A category without locked actions gets no note.
    const userSwitch = page.getByRole("switch", { name: "audit_category_user_actions" }).element();
    expect(userSwitch.hasAttribute("aria-describedby")).toBe(false);
  });

  test("turning the category off leaves locked actions on and never sends them", async () => {
    await renderExpanded();

    (categorySwitch().element() as HTMLElement).click();

    await expect
      .element(page.getByRole("checkbox", { name: "audit_action_user_created" }))
      .toHaveAttribute("aria-checked", "false");
    await expect
      .element(page.getByRole("checkbox", { name: "audit_action_role_modified" }))
      .toHaveAttribute("aria-checked", "false");
    await expect.element(lockedRow()).toHaveAttribute("aria-checked", "true");
    await expect
      .element(page.getByRole("checkbox", { name: "audit_action_widget_activated" }))
      .toHaveAttribute("aria-checked", "true");

    await page.getByRole("button", { name: "audit_config_save" }).click();

    await vi.waitFor(() => expect(audit.updateActionConfig).toHaveBeenCalledTimes(1));
    expect(audit.updateActionConfig).toHaveBeenCalledWith({
      updates: [
        { action: "user_created", enabled: false },
        { action: "role_modified", enabled: false }
      ]
    });
    expect(audit.updateConfig).toHaveBeenCalledWith({
      updates: [
        { category: "admin_actions", enabled: false },
        { category: "user_actions", enabled: true }
      ]
    });
  });

  test("unchecking every changeable action turns the category off", async () => {
    await renderExpanded();

    await page.getByRole("checkbox", { name: "audit_action_user_created" }).click();
    await expect.element(categorySwitch()).toHaveAttribute("aria-checked", "true");
    await page.getByRole("checkbox", { name: "audit_action_role_modified" }).click();

    await expect.element(categorySwitch()).toHaveAttribute("aria-checked", "false");
    await expect.element(lockedRow()).toHaveAttribute("aria-checked", "true");
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule with a locked row open (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      await renderExpanded();

      const result = await axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
        },
        // A tab rendered on its own has no page landmarks around it.
        rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
      });
      expect(result.violations.map((violation) => violation.id)).toEqual([]);
    }
  );
});

import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => "sv" }));

import SpaceMemberRole from "./SpaceMemberRole.svelte";

function props(patch: Record<string, unknown> = {}) {
  return {
    name: "Anna Berg",
    role: "editor" as const,
    roles: ["admin", "editor", "viewer"] as const,
    onChangeRole: vi.fn().mockResolvedValue(undefined),
    onRemove: vi.fn().mockResolvedValue(undefined),
    removeTitle: "remove_title",
    removeDescription: "remove_description",
    ...patch
  };
}

// bits-ui renders the select's trigger as a button that opens a listbox.
const role = (name = "Anna Berg") =>
  page.getByRole("button", { name: new RegExp(`^admin_spaces_role_for\\(${name}\\)`) });
const remove = () => page.getByRole("button", { name: "admin_spaces_remove_named(Anna Berg)" });

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.trim())
    .join(" | ");
}

async function choose(option: string) {
  await role().click();
  await page.getByRole("option", { name: option }).click();
}

beforeEach(() => {
  delete document.documentElement.dataset.theme;
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  document.body.classList.remove("bg-primary");
});

describe("SpaceMemberRole", () => {
  test("names both controls after the member and reads the role out with its value", async () => {
    render(SpaceMemberRole, props());

    await expect
      .element(role())
      .toHaveAccessibleName("admin_spaces_role_for(Anna Berg) space_role_editor");
    await expect.element(remove()).toBeVisible();

    await role().click();
    const options = page.getByRole("option").elements();
    // Lowest first, and translated.
    expect(options.map((option) => option.textContent?.trim())).toEqual([
      "space_role_viewer",
      "space_role_editor",
      "space_role_admin"
    ]);
  });

  test("shows the new role at once and keeps it when the change is saved", async () => {
    const onChangeRole = vi.fn().mockResolvedValue(undefined);
    render(SpaceMemberRole, props({ onChangeRole }));

    await choose("space_role_admin");

    expect(onChangeRole).toHaveBeenCalledWith("admin");
    await expect
      .element(role())
      .toHaveAccessibleName("admin_spaces_role_for(Anna Berg) space_role_admin");
  });

  test("puts the previous role back when the change fails", async () => {
    let fail: (error: Error) => void = () => {};
    const onChangeRole = vi.fn(() => new Promise((_resolve, reject) => (fail = reject)));
    render(SpaceMemberRole, props({ onChangeRole }));

    await choose("space_role_viewer");
    await expect.element(role()).toHaveAttribute("aria-busy", "true");
    await expect
      .element(role())
      .toHaveAccessibleName("admin_spaces_role_for(Anna Berg) space_role_viewer");

    fail(new Error("last admin"));
    await expect
      .element(role())
      .toHaveAccessibleName("admin_spaces_role_for(Anna Berg) space_role_editor");
    expect(role().element().hasAttribute("aria-busy")).toBe(false);
  });

  test("a disabled member keeps focusable controls that say why and do nothing", async () => {
    const onChangeRole = vi.fn();
    const onRemove = vi.fn();
    const { container } = render(
      SpaceMemberRole,
      props({ disabled: true, disabledReasonId: "why", onChangeRole, onRemove })
    );
    container.insertAdjacentHTML("beforeend", '<p id="why">Only administrator</p>');

    for (const control of [role(), remove()]) {
      await expect.element(control).toHaveAttribute("aria-disabled", "true");
      expect(description(control.element())).toBe("Only administrator");
      expect((control.element() as HTMLButtonElement).disabled).toBe(false);
    }

    // Playwright refuses to click an aria-disabled control; a person can still press it.
    (role().element() as HTMLElement).click();
    (role().element() as HTMLElement).focus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{Enter}");
    (remove().element() as HTMLElement).click();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(page.getByRole("listbox").elements()).toHaveLength(0);
    expect(page.getByRole("alertdialog").elements()).toHaveLength(0);
    expect(onChangeRole).not.toHaveBeenCalled();
    expect(onRemove).not.toHaveBeenCalled();

    (remove().element() as HTMLElement).focus();
    expect(document.activeElement).toBe(remove().element());
  });

  test("asks before removing, and shows a refusal inside the confirmation", async () => {
    const onRemove = vi
      .fn()
      .mockRejectedValueOnce(new Error("nope"))
      .mockResolvedValueOnce(undefined);
    render(SpaceMemberRole, props({ onRemove, removeErrorContext: "could_not_remove" }));

    await remove().click();
    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toHaveAccessibleName("remove_title");
    await expect.element(dialog).toHaveAccessibleDescription("remove_description");
    await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
    // Cancel first: a stray Enter must not remove anyone.
    await expect.element(page.getByRole("button", { name: "cancel" })).toHaveFocus();

    await page.getByRole("button", { name: "remove", exact: true }).click();
    await expect.element(page.getByRole("alert")).toHaveTextContent(/^could_not_remove: /);
    expect(onRemove).toHaveBeenCalledTimes(1);

    await page.getByRole("button", { name: "remove", exact: true }).click();
    await expect.element(dialog).not.toBeInTheDocument();
    expect(onRemove).toHaveBeenCalledTimes(2);
  });

  test("reads a note about the roles on offer with the role picker", async () => {
    const { container } = render(
      SpaceMemberRole,
      props({ roles: ["viewer", "editor"], roleDescriptionId: "offered" })
    );
    container.insertAdjacentHTML("beforeend", '<p id="offered">Only lower roles</p>');

    expect(description(role().element())).toBe("Only lower roles");
    expect(description(remove().element())).toBe("");
  });

  test.each(["light", "dark"] as const)(
    "keeps the open removal confirmation readable (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(SpaceMemberRole, props());
      await remove().click();
      const dialog = page.getByRole("alertdialog");
      await expect.element(dialog).toBeVisible();
      await userEvent.unhover(document.body);
      await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));

      // The confirm button is the shared destructive variant.
      const result = await axe.run(dialog.element(), {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
        }
      });
      expect(
        result.violations.flatMap((violation) =>
          violation.nodes.map((node) => `${violation.id}: ${node.html}`)
        )
      ).toEqual([]);
    }
  );

  test("gives both controls a 44 px target on a phone", async () => {
    await page.viewport(375, 700);
    try {
      render(SpaceMemberRole, props());
      for (const control of [role(), remove()]) {
        const box = control.element().getBoundingClientRect();
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
      expect(remove().element().getBoundingClientRect().width).toBeGreaterThanOrEqual(44);
    } finally {
      await page.viewport(1280, 720);
    }
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule, also when disabled (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(SpaceMemberRole, props());
      render(SpaceMemberRole, {
        ...props({ name: "Bo", disabled: true, disabledReasonId: "why" }),
        // The reason is the caller's visible text; here a stand-in.
        class: "mt-4"
      });
      document.body.insertAdjacentHTML("beforeend", '<p id="why">Only administrator</p>');
      await expect.element(role()).toBeVisible();
      await userEvent.unhover(document.body);

      const result = await axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
        },
        rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
      });
      document.getElementById("why")?.remove();
      expect(
        result.violations.flatMap((violation) =>
          violation.nodes.map((node) => `${violation.id}: ${node.html}`)
        )
      ).toEqual([]);
    }
  );
});

import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type AdminSpaceViewerMembership } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import sv from "../../../../../messages/sv.json";
import "../../../../app.css";

const navigation = vi.hoisted(() => ({ invalidateAll: vi.fn() }));
const admin = vi.hoisted(() => ({ join: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
// Messages read as their keys, or as the real Swedish text where length matters.
const i18n = vi.hoisted(() => ({ catalog: null as Record<string, string> | null }));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: navigation.invalidateAll,
  onNavigate: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/admin/spaces/space-1"), state: {} }
}));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ spaces: { admin } }) }));
vi.mock("$lib/components/toast", () => ({ toast }));
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) => {
        const text = i18n.catalog?.[String(key)];
        if (text) return text.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? ""));
        return params ? `${String(key)}(${Object.values(params).join("|")})` : String(key);
      }
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));

import JoinSpaceDialog from "./JoinSpaceDialog.svelte";

const space = {
  id: "space-1",
  name: "Ekonomi",
  security_classification: { name: "Konfidentiell", security_level: 2 }
};

function membership(patch: Partial<AdminSpaceViewerMembership> = {}): AdminSpaceViewerMembership {
  return {
    via_groups: [],
    joinable_roles: ["viewer", "editor", "admin"],
    can_leave: false,
    ...patch
  };
}

const groupMember = membership({
  group_role: "viewer",
  via_groups: [
    { id: "g1", name: "Ekonomistöd" },
    { id: "g2", name: "Controllers" }
  ],
  joinable_roles: ["editor", "admin"]
});

const members = { users: [], groups: [] };
const REASON = "Ärende 2026-114: granskning av behörigheter";

const trigger = () => page.getByRole("button", { name: "admin_spaces_join_open" });
const dialog = () => page.getByRole("dialog");
const radio = (role: string) => page.getByRole("radio", { name: `space_role_${role}` });
const reason = () => page.getByRole("textbox", { name: /admin_spaces_join_reason_label/ });
const submit = () => page.getByRole("button", { name: /^admin_spaces_join_(submit|pending)/ });

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" | ");
}

async function openDialog(props: Record<string, unknown> = {}) {
  render(JoinSpaceDialog, { space, membership: membership(), ...props });
  await page.getByRole("button", { name: /^(admin_spaces_join_open|Gå med i ytan…)$/ }).click();
  await expect.element(dialog()).toBeVisible();
  // The dialog zooms in; focus, layout and axe checks must not run half-drawn.
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
}

async function axeViolations(context: Element | Document) {
  // Measure resting colours, not a hover the last click left behind.
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
  const result = await axe.run(context, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    },
    // A component rendered on its own has no page landmarks around it.
    rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html}`)
  );
}

let heading: HTMLElement | undefined;

/** The element a page would hand in to take focus after the join, e.g. its banner heading. */
function focusTarget() {
  heading = document.createElement("h2");
  heading.tabIndex = -1;
  heading.textContent = "Du är medlem i ytan";
  document.body.append(heading);
  return heading;
}

beforeEach(() => {
  vi.clearAllMocks();
  navigation.invalidateAll.mockResolvedValue(undefined);
  admin.join.mockResolvedValue(members);
  i18n.catalog = null;
  delete document.documentElement.dataset.theme;
  // The app shell paints the page; without it dark text is measured on white.
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  heading?.remove();
  document.body.classList.remove("bg-primary");
});

describe("JoinSpaceDialog", () => {
  test("offers only the joinable roles, lowest first, and opens on the lowest", async () => {
    await openDialog({ membership: membership({ joinable_roles: ["admin", "editor"] }) });

    const offered = page
      .getByRole("radio")
      .elements()
      .map((element) => element.id.replace(/.*-role-/, ""));
    expect(offered).toEqual(["editor", "admin"]);
    await expect.element(radio("editor")).toHaveAttribute("aria-checked", "true");
    await expect.element(radio("editor")).toHaveFocus();
    await expect.element(submit()).toHaveTextContent("admin_spaces_join_submit(space_role_editor)");
  });

  test("describes each role and the group role, and says what joining shows", async () => {
    await openDialog({ membership: groupMember });

    expect(description(radio("admin").element())).toBe("space_role_admin_description");
    expect(description(page.getByRole("radiogroup").element())).toBe(
      "admin_spaces_join_role_hint | " +
        "admin_spaces_join_group_note(space_role_viewer|Ekonomistöd och Controllers)"
    );
    await expect.element(page.getByRole("group", { name: "role" })).toBeVisible();
    await expect.element(dialog()).toHaveAccessibleName("admin_spaces_join_title(Ekonomi)");
    await expect
      .element(dialog())
      .toHaveAccessibleDescription(/admin_spaces_join_classified\(Konfidentiell\)/);
    await expect.element(page.getByText("admin_spaces_join_bullet_visible")).toBeVisible();
    await expect.element(page.getByText("admin_spaces_join_bullet_audit")).toBeVisible();
    await expect.element(page.getByText("admin_spaces_join_bullet_leave")).toBeVisible();
  });

  test("refuses a short reason on submit: marks it invalid, says why and focuses it", async () => {
    await openDialog();
    await expect.element(reason()).toHaveAttribute("aria-required", "true");
    expect(reason().element().hasAttribute("aria-invalid")).toBe(false);

    await reason().fill("  för   kort ");
    await submit().click();

    await expect.element(reason()).toHaveAttribute("aria-invalid", "true");
    await expect.element(reason()).toHaveFocus();
    expect(description(reason().element())).toContain("oversight_reason_too_short(10)");
    expect(admin.join).not.toHaveBeenCalled();

    await reason().fill(REASON);
    expect(reason().element().hasAttribute("aria-invalid")).toBe(false);
    expect(description(reason().element())).not.toContain("oversight_reason_too_short");
  });

  test("reads the help, the docs link and the counter with the field, without a live counter", async () => {
    await openDialog();
    await reason().fill("Ärende 12");

    const text = description(reason().element());
    expect(text).toContain("admin_spaces_join_reason_help");
    expect(text).toContain("oversight_reason_counter(9|500)");
    expect(reason().element().getAttribute("maxlength")).toBe("500");
    const counter = page.getByText("oversight_reason_counter(9|500)").element();
    expect(counter.closest("[aria-live], [role=status], [role=alert]")).toBeNull();
    await expect
      .element(page.getByRole("link", { name: "read_more" }))
      .toHaveAttribute("href", expect.stringContaining("/guides/space-oversight#join-a-space"));
  });

  test("joins with the chosen role and reason, reloads, confirms and moves focus on", async () => {
    const onJoined = vi.fn();
    const target = focusTarget();
    await openDialog({ focusAfterJoin: () => target, onJoined });

    await radio("admin").click();
    await reason().fill(REASON);
    await submit().click();

    await expect.element(dialog()).not.toBeInTheDocument();
    expect(admin.join).toHaveBeenCalledWith({ spaceId: "space-1", role: "admin", reason: REASON });
    expect(navigation.invalidateAll).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("admin_spaces_join_done(space_role_admin|Ekonomi)");
    expect(onJoined).toHaveBeenCalledWith(members, "admin");
    await vi.waitFor(() => expect(document.activeElement).toBe(target));
    // The dialog hands focus back to its opener as it closes; it must not win.
    await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(document.activeElement).toBe(target);
  });

  test("shows the server's refusal inline, in an alert, and stays open", async () => {
    admin.join.mockRejectedValue(new EneoError("Already a member", "RESPONSE", 409, 9065, {}));
    await openDialog();

    await reason().fill(REASON);
    await submit().click();

    await expect.element(page.getByRole("alert")).toHaveTextContent("eneo_error_9065");
    await expect.element(dialog()).toBeVisible();
    expect(navigation.invalidateAll).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  test("keeps the buttons focusable but inert while the join is saved", async () => {
    let finish: (value: typeof members) => void = () => {};
    admin.join.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    await openDialog();

    await reason().fill(REASON);
    await submit().click();

    await expect.element(submit()).toHaveTextContent("admin_spaces_join_pending");
    await expect.element(submit()).toHaveAttribute("aria-disabled", "true");
    expect((submit().element() as HTMLButtonElement).disabled).toBe(false);
    await userEvent.keyboard("{Escape}");
    await expect.element(dialog()).toBeVisible();

    finish(members);
    await expect.element(dialog()).not.toBeInTheDocument();
  });

  test("returns focus to the button that opened it when cancelled", async () => {
    await openDialog();
    await page.getByRole("button", { name: "cancel" }).click();

    await expect.element(dialog()).not.toBeInTheDocument();
    await expect.element(trigger()).toHaveFocus();
  });

  test("starts over each time it opens", async () => {
    await openDialog();
    await radio("admin").click();
    await reason().fill("kort");
    await submit().click();
    await expect.element(reason()).toHaveAttribute("aria-invalid", "true");
    await page.getByRole("button", { name: "cancel" }).click();
    await expect.element(dialog()).not.toBeInTheDocument();

    await trigger().click();
    await expect.element(radio("viewer")).toHaveAttribute("aria-checked", "true");
    await expect.element(radio("viewer")).toHaveFocus();
    await expect.element(reason()).toHaveValue("");
    expect(reason().element().hasAttribute("aria-invalid")).toBe(false);
  });

  test("offers no join when there is no higher role to join with", async () => {
    render(JoinSpaceDialog, { space, membership: membership({ joinable_roles: [] }) });
    expect(trigger().elements()).toHaveLength(0);
  });

  test("reflows at 320 px without scrolling sideways or clipping, in Swedish", async () => {
    i18n.catalog = sv;
    await page.viewport(320, 640);
    try {
      await openDialog({ membership: groupMember });
      const content = dialog().element() as HTMLElement;
      const box = content.getBoundingClientRect();
      expect(box.left).toBeGreaterThanOrEqual(0);
      expect(box.right).toBeLessThanOrEqual(320);

      const elements = [content, ...content.querySelectorAll<HTMLElement>("*")].filter(
        (element) => !element.closest(".sr-only")
      );
      const scrollsSideways = elements.filter(
        (element) =>
          ["auto", "scroll"].includes(getComputedStyle(element).overflowX) &&
          element.scrollWidth > element.clientWidth + 1
      );
      const outside = elements.filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && (rect.left < box.left - 1 || rect.right > box.right + 1);
      });
      expect(scrollsSideways.map((element) => element.outerHTML.slice(0, 100))).toEqual([]);
      expect(outside.map((element) => element.outerHTML.slice(0, 100))).toEqual([]);
    } finally {
      await page.viewport(1280, 720);
    }
  });

  test("at 400 % zoom (320 × 256 px) nothing is cut off and every control can be reached", async () => {
    i18n.catalog = sv;
    await page.viewport(320, 256);
    try {
      await openDialog({ membership: groupMember });
      const content = dialog().element() as HTMLElement;
      expect(content.getBoundingClientRect().bottom).toBeLessThanOrEqual(256);

      // Content hidden behind `overflow: hidden` cannot be scrolled to with a mouse or a finger.
      const clipping = [content, ...content.querySelectorAll<HTMLElement>("*")].filter(
        (element) =>
          !element.closest(".sr-only") &&
          element.scrollHeight > element.clientHeight + 1 &&
          getComputedStyle(element).overflowY === "hidden"
      );
      expect(clipping.map((element) => element.outerHTML.slice(0, 100))).toEqual([]);

      const controls = [
        page.getByRole("radio").first(),
        page.getByRole("radio").last(),
        page.getByRole("textbox"),
        page.getByRole("link"),
        page.getByRole("button", { name: "Avbryt" }),
        page.getByRole("button", { name: /^Gå med som/ })
      ].map((locator) => locator.element() as HTMLElement);
      for (const control of controls) {
        control.scrollIntoView({ block: "nearest" });
        const rect = control.getBoundingClientRect();
        const hit = document.elementFromPoint(
          rect.left + rect.width / 2,
          rect.top + rect.height / 2
        );
        expect(control.contains(hit), control.outerHTML.slice(0, 80)).toBe(true);
      }
    } finally {
      await page.viewport(1280, 720);
    }
  });

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule while closed (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      render(JoinSpaceDialog, { space, membership: membership() });
      await expect.element(trigger()).toBeVisible();

      expect(await axeViolations(document)).toEqual([]);
    }
  );

  test.each(["light", "dark"] as const)(
    "passes every WCAG 2.2 A and AA rule while open, with each kind of error (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      admin.join.mockRejectedValue(new EneoError("Already a member", "RESPONSE", 409, 9065, {}));
      await openDialog({ membership: groupMember });

      // Scoped to the dialog: the page behind the modal is inert and dimmed.
      await reason().fill("kort");
      await submit().click();
      await expect.element(reason()).toHaveAttribute("aria-invalid", "true");
      expect(await axeViolations(dialog().element())).toEqual([]);

      await reason().fill(REASON);
      await submit().click();
      await expect.element(page.getByRole("alert")).toBeVisible();
      expect(await axeViolations(dialog().element())).toEqual([]);
    }
  );
});

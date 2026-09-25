import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type Widget } from "@eneo/eneo-js";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, string>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, string>) =>
        params ? `${String(key)}(${Object.values(params).join("|")})` : String(key)
    }
  )
}));
vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv",
  localizeHref: (href: string) => href
}));
vi.mock("./errors", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./errors")>()),
  toastWidgetError: vi.fn()
}));

import { toastWidgetError } from "./errors";
import WidgetStatusBar from "./WidgetStatusBar.svelte";
import { WidgetAutosave } from "./widgetAutosave.svelte";

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    name: "Chatt",
    status: "active",
    revision: 0,
    activated_at: "2026-09-01T00:00:00Z",
    allowed_origins: ["https://www.kommun.se"],
    activation_blockers: [],
    ...overrides
  } as unknown as Widget;
}

const draft = (overrides: Partial<Widget> = {}) =>
  widget({ status: "draft", activated_at: null, ...overrides });

const requested = (overrides: Partial<Widget> = {}) =>
  draft({
    activation_requested_at: "2026-09-24T08:30:00Z",
    activation_requested_by_user_id: "u1",
    ...overrides
  });

function renderBar(
  autosave: WidgetAutosave,
  isAdmin = true,
  handlers: Partial<Record<"onRequestActivation" | "onWithdrawRequest", () => Promise<void>>> = {}
) {
  const noop = vi.fn(async () => {});
  render(WidgetStatusBar, {
    autosave,
    isAdmin,
    currentUserId: "u1",
    onActivate: noop,
    onPause: noop,
    onArchive: noop,
    onReload: noop,
    onRequestActivation: handlers.onRequestActivation ?? noop,
    onWithdrawRequest: handlers.onWithdrawRequest ?? noop
  });
}

/** Resolves the ids in `aria-describedby` to the text they point at. */
function description(element: Element): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim())
    .join(" | ");
}

async function axeViolations() {
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
  const result = await axe.run(document.body, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    },
    rules: { "landmark-one-main": { enabled: false }, region: { enabled: false } }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html} ${node.failureSummary}`)
  );
}

const requestButton = () => page.getByRole("button", { name: /^widget_request_button/ });
const withdrawButton = () => page.getByRole("button", { name: "widget_request_withdraw" });

beforeEach(() => {
  vi.mocked(toastWidgetError).mockReset();
  document.body.classList.add("bg-primary");
});

afterEach(() => {
  document.body.classList.remove("bg-primary");
  delete document.documentElement.dataset.theme;
});

describe("WidgetStatusBar", () => {
  test("an active widget that is not serving as configured says so", async () => {
    renderBar(
      new WidgetAutosave(widget({ activation_blockers: ["target_not_published"] }), vi.fn())
    );
    await expect.element(page.getByText("widget_admin_active_issues_title")).toBeVisible();
    await expect.element(page.getByText("widget_admin_blocker_target_not_published")).toBeVisible();
  });

  test("a healthy active widget shows no warning", async () => {
    renderBar(new WidgetAutosave(widget(), vi.fn()));
    await expect.element(page.getByText("widget_admin_status_active")).toBeVisible();
    expect(document.body.textContent).not.toContain("widget_admin_active_issues_title");
    expect(document.body.textContent).not.toContain("widget_admin_blockers_title");
  });

  test("an inactive widget keeps the activation wording", async () => {
    renderBar(new WidgetAutosave(draft({ activation_blockers: ["subtitle_empty"] }), vi.fn()));
    await expect.element(page.getByText("widget_admin_blockers_title")).toBeVisible();
  });

  test("a blocked widget's activate button stays focusable and is described by what blocks it", async () => {
    const onActivate = vi.fn(async () => {});
    render(WidgetStatusBar, {
      autosave: new WidgetAutosave(draft({ activation_blockers: ["subtitle_empty"] }), vi.fn()),
      isAdmin: true,
      currentUserId: "u1",
      onActivate,
      onPause: vi.fn(),
      onArchive: vi.fn(),
      onReload: vi.fn(),
      onRequestActivation: vi.fn(),
      onWithdrawRequest: vi.fn()
    });
    const activate = page.getByRole("button", { name: "widget_admin_activate" });
    await expect.element(activate).toHaveAttribute("aria-disabled", "true");
    expect((activate.element() as HTMLButtonElement).disabled).toBe(false);
    await expect
      .element(activate)
      .toHaveAccessibleDescription(/widget_admin_blocker_subtitle_empty/);
    // Playwright will not click an aria-disabled button, so a script does.
    (activate.element() as HTMLElement).click();
    expect(onActivate).not.toHaveBeenCalled();
  });

  test("lists what the server refused so it can be found on any tab", async () => {
    const autosave = new WidgetAutosave(
      widget(),
      vi.fn().mockRejectedValue(
        new EneoError("refused", "RESPONSE", 400, 0, {
          detail: {
            code: "widget_policy_violation",
            message: "raw",
            violations: ["retention_above_policy_maximum"]
          }
        })
      ),
      { delay: 0 }
    );
    renderBar(autosave);
    autosave.patch({ privacy: { retention_days: 400 } as Widget["privacy"] });
    await autosave.flush();

    await expect.element(page.getByText("widget_admin_save_refused")).toBeVisible();
    await expect.element(page.getByText("widget_admin_refusals_title")).toBeVisible();
    await expect.element(page.getByText("widget_admin_blocker_retention_max")).toBeVisible();
  });
});

describe("WidgetStatusBar for an editor who is not an administrator", () => {
  test("asks for activation instead of offering a disabled Activate", async () => {
    const onRequestActivation = vi.fn(async () => {});
    renderBar(new WidgetAutosave(draft(), vi.fn()), false, { onRequestActivation });

    const request = page.getByRole("button", { name: "widget_request_button" });
    await expect.element(request).not.toHaveAttribute("aria-disabled", "true");
    await expect.element(request).toHaveAccessibleDescription("widget_request_note");
    expect(page.getByRole("button", { name: "widget_admin_activate" }).query()).toBeNull();
    expect(page.getByRole("button", { name: "widget_admin_archive" }).query()).toBeNull();

    await userEvent.click(request);
    await vi.waitFor(() => expect(onRequestActivation).toHaveBeenCalledTimes(1));
  });

  test("a paused widget asks for reactivation", async () => {
    renderBar(new WidgetAutosave(widget({ status: "paused" }), vi.fn()), false);
    await expect
      .element(page.getByRole("button", { name: "widget_request_button_resume" }))
      .toBeVisible();
    expect(page.getByRole("button", { name: "widget_admin_resume" }).query()).toBeNull();
  });

  test("a blocked request stays focusable and is described by the blockers", async () => {
    const onRequestActivation = vi.fn(async () => {});
    renderBar(
      new WidgetAutosave(draft({ activation_blockers: ["subtitle_empty"] }), vi.fn()),
      false,
      {
        onRequestActivation
      }
    );

    const request = requestButton();
    await expect.element(request).toHaveAttribute("aria-disabled", "true");
    expect((request.element() as HTMLButtonElement).disabled).toBe(false);
    expect(description(request.element())).toContain("widget_admin_blocker_subtitle_empty");
    (request.element() as HTMLElement).click();
    expect(onRequestActivation).not.toHaveBeenCalled();
  });

  test("an unsaved edit does not hold the request back: requesting saves it first", async () => {
    let saved!: () => void;
    const save = vi.fn(
      (update: Partial<Widget>) =>
        new Promise<Widget>((resolve) => (saved = () => resolve(draft({ ...update, revision: 1 }))))
    );
    const onRequestActivation = vi.fn(async () => {});
    // A long delay keeps the edit pending instead of handing it to a save.
    const autosave = new WidgetAutosave(draft(), save, { delay: 60_000 });
    renderBar(autosave, false, { onRequestActivation });

    autosave.patch({ name: "Ny" });
    const request = requestButton();
    await expect.element(request).not.toHaveAttribute("aria-disabled", "true");
    await expect.element(request).toHaveAccessibleDescription("widget_request_note");

    await userEvent.click(request);
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(onRequestActivation).not.toHaveBeenCalled();
    saved();
    await vi.waitFor(() => expect(onRequestActivation).toHaveBeenCalledTimes(1));
  });

  test("a pending request can be withdrawn, and both steps are announced", async () => {
    let current = draft();
    const autosave = new WidgetAutosave(current, vi.fn());
    const onRequestActivation = vi.fn(async () => {
      current = requested();
      autosave.replace(current);
    });
    const onWithdrawRequest = vi.fn(async () => {
      current = draft();
      autosave.replace(current);
    });
    renderBar(autosave, false, { onRequestActivation, onWithdrawRequest });
    const status = page.getByRole("status");

    await userEvent.click(requestButton());
    await expect.element(status).toHaveTextContent("widget_request_sent");
    await expect.element(page.getByText("widget_request_badge")).toBeVisible();
    await expect.element(page.getByText(/^widget_request_mine\(/)).toBeVisible();
    await expect.element(page.getByText("widget_request_keep_editing")).toBeVisible();
    // The pressed button is replaced; focus goes to the one that undoes it.
    await expect.element(withdrawButton()).toHaveFocus();
    expect(document.querySelector("time")?.getAttribute("datetime")).toBe("2026-09-24T08:30:00Z");

    await userEvent.click(withdrawButton());
    await vi.waitFor(() => expect(onWithdrawRequest).toHaveBeenCalledTimes(1));
    await expect.element(status).toHaveTextContent("widget_request_withdrawn");
    await expect.element(requestButton()).toHaveFocus();
    expect(document.body.textContent).not.toContain("widget_request_badge");
  });

  test("someone else's request reads as theirs", async () => {
    renderBar(
      new WidgetAutosave(requested({ activation_requested_by_user_id: "u2" }), vi.fn()),
      false
    );
    await expect.element(page.getByText(/^widget_request_other\(/)).toBeVisible();
    expect(document.body.textContent).not.toContain("widget_request_mine");
  });

  test("a request that was sent back shows the reason under a heading", async () => {
    renderBar(
      new WidgetAutosave(
        draft({
          activation_declined_at: "2026-09-24T09:00:00Z",
          activation_decline_reason: "Lägg till en länk till integritetspolicyn i sidfoten."
        }),
        vi.fn()
      ),
      false
    );
    await expect
      .element(page.getByRole("heading", { level: 3, name: /^widget_request_returned_title\(/ }))
      .toBeVisible();
    const quote = document.querySelector("blockquote");
    expect(quote?.textContent?.trim()).toBe(
      "Lägg till en länk till integritetspolicyn i sidfoten."
    );
    await expect.element(page.getByText("widget_request_returned_next")).toBeVisible();
    await expect.element(page.getByRole("button", { name: "widget_request_button" })).toBeVisible();
  });

  test("a failed request is explained and nothing is announced", async () => {
    const refusal = new EneoError("blocked", "RESPONSE", 400, 0, {
      detail: { code: "widget_serving_blocked", message: "raw", blockers: ["subtitle_empty"] }
    });
    const onRequestActivation = vi.fn(async () => {
      throw refusal;
    });
    renderBar(new WidgetAutosave(draft(), vi.fn()), false, { onRequestActivation });
    await userEvent.click(requestButton());
    await vi.waitFor(() =>
      expect(toastWidgetError).toHaveBeenCalledWith(refusal, "widget_request_could_not")
    );
    expect(toastWidgetError).toHaveBeenCalledTimes(1);
    await expect.element(page.getByRole("status")).toHaveTextContent("");
    await expect.element(requestButton()).toBeVisible();
  });
});

describe("WidgetStatusBar for an administrator", () => {
  test("keeps Activate and links a pending request to its review", async () => {
    renderBar(new WidgetAutosave(requested({ activation_requested_by_user_id: "u2" }), vi.fn()));
    await expect.element(page.getByRole("button", { name: "widget_admin_activate" })).toBeVisible();
    await expect.element(page.getByRole("button", { name: "widget_admin_archive" })).toBeVisible();
    await expect.element(page.getByText(/^widget_request_other\(/)).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "widget_request_admin_review" }))
      .toHaveAttribute("href", "/admin/widgets/w1");
    expect(withdrawButton().query()).toBeNull();
    expect(document.body.textContent).not.toContain("widget_request_keep_editing");
  });
});

describe.each(["light", "dark"])("WidgetStatusBar accessibility (%s)", (theme) => {
  beforeEach(() => {
    document.documentElement.dataset.theme = theme;
  });

  test("a pending request has no violations", async () => {
    renderBar(new WidgetAutosave(requested(), vi.fn()), false);
    await expect.element(withdrawButton()).toBeVisible();
    expect(await axeViolations()).toEqual([]);
  });

  test("a sent-back request and a blocked request have no violations", async () => {
    renderBar(
      new WidgetAutosave(
        draft({
          activation_blockers: ["subtitle_empty"],
          activation_declined_at: "2026-09-24T09:00:00Z",
          activation_decline_reason: "Beskrivningen saknar AI-upplysning."
        }),
        vi.fn()
      ),
      false
    );
    await expect.element(page.getByRole("heading", { level: 3 })).toBeVisible();
    expect(await axeViolations()).toEqual([]);
  });

  test("a paused widget has no violations", async () => {
    renderBar(new WidgetAutosave(widget({ status: "paused" }), vi.fn()));
    await expect.element(page.getByText("widget_admin_status_paused")).toBeVisible();
    expect(await axeViolations()).toEqual([]);
  });

  test("an administrator's view of a request has no violations", async () => {
    renderBar(new WidgetAutosave(requested(), vi.fn()));
    await expect
      .element(page.getByRole("link", { name: "widget_request_admin_review" }))
      .toBeVisible();
    expect(await axeViolations()).toEqual([]);
  });
});

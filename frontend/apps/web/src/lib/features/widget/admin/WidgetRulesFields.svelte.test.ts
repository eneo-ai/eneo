/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { EneoError, type Widget, type WidgetPolicy, type WidgetUpdate } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
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

import WidgetRulesFields from "./WidgetRulesFields.svelte";
import { WidgetAutosave } from "./widgetAutosave.svelte";

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: "w1",
    name: "Chatt",
    status: "draft",
    revision: 0,
    texts: { title: "", welcome: "" },
    theme: { primary_color: "#1F4E79", radius: 12 },
    limits: {
      messages_per_visitor_10min: 10,
      messages_per_ip_hour: 60,
      daily_token_budget: 4000,
      max_question_chars: 2000,
      max_session_turns: 30
    },
    privacy: { retention_days: 30, store_feedback_text: false },
    allowed_origins: ["https://www.kommun.se"],
    bot_protection: "altcha",
    activation_blockers: [],
    ...overrides
  } as unknown as Widget;
}

const policy: WidgetPolicy = {
  max_daily_token_budget: 5000,
  min_retention_days: 7,
  max_retention_days: 90,
  allow_bot_protection_none: false
};

type Save = (update: WidgetUpdate) => Promise<Widget>;

function setup(
  start: Widget,
  save: Save = vi.fn(async (update: WidgetUpdate) => widget(update as Partial<Widget>)),
  rules: WidgetPolicy | null = policy
) {
  const autosave = new WidgetAutosave(start, save, { delay: 10 });
  render(WidgetRulesFields, { autosave, policy: rules });
  return { autosave, save };
}

const origins = () => page.getByLabelText("widget_admin_allowed_origins", { exact: true });
const budget = () => page.getByLabelText("widget_admin_daily_budget", { exact: true });

describe("WidgetRulesFields origins", () => {
  test("a pasted page address is flagged at the field and never sent", async () => {
    const save = vi.fn(async (update: WidgetUpdate) => widget(update as Partial<Widget>));
    const { autosave } = setup(widget(), save);
    await userEvent.fill(origins(), "https://www.kommun.se\nhttps://www.kommun.se/kontakt");
    await userEvent.tab();

    await expect.element(origins()).toHaveAttribute("aria-invalid", "true");
    await expect
      .element(origins())
      .toHaveAccessibleDescription(
        /widget_admin_origins_invalid\(https:\/\/www.kommun.se\/kontakt\)/
      );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(save).not.toHaveBeenCalled();
    // The valid new line is held back with the bad one: leaving must ask first.
    expect(autosave.stranded).toBe(true);

    await userEvent.fill(origins(), "HTTPS://WWW.Kommun.se/\nhttps://*.kommun.se");
    await userEvent.tab();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({
      allowed_origins: ["https://www.kommun.se", "https://*.kommun.se"],
      revision: 0
    });
    // Settled on the canonical form the server stores.
    await expect.element(origins()).toHaveValue("https://www.kommun.se\nhttps://*.kommun.se");
    await expect.element(origins()).toHaveAttribute("aria-invalid", "false");
    expect(autosave.stranded).toBe(false);
  });

  test("follows the saved list after a reload instead of keeping a stale copy", async () => {
    const { autosave } = setup(widget());
    await expect.element(origins()).toHaveValue("https://www.kommun.se");
    autosave.reload(widget({ allowed_origins: ["https://www.kommun.se", "https://annan.se"] }));
    await expect.element(origins()).toHaveValue("https://www.kommun.se\nhttps://annan.se");
  });

  test("a list the server refuses stays with its reason while other rules keep saving", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(
        new EneoError("refused", "RESPONSE", 422, 0, {
          detail: [{ loc: ["body", "allowed_origins"], type: "value_error", msg: "Invalid value" }]
        })
      )
      .mockImplementation(async (update: WidgetUpdate) => widget(update as Partial<Widget>));
    setup(widget(), save);

    await userEvent.fill(origins(), "https://ny.kommun.se");
    await userEvent.tab();
    await expect.element(origins()).toHaveAccessibleDescription(/widget_admin_origins_refused/);
    await expect.element(origins()).toHaveValue("https://ny.kommun.se");

    await userEvent.fill(budget(), "3000");
    await userEvent.tab();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenLastCalledWith({
      limits: expect.objectContaining({ daily_token_budget: 3000 }),
      revision: 0
    });
    await expect.element(origins()).toHaveAccessibleDescription(/widget_admin_origins_refused/);
  });

  test("a live widget's list cannot be emptied: it stays in the field and is not sent", async () => {
    const save = vi.fn(async (update: WidgetUpdate) => widget(update as Partial<Widget>));
    setup(widget({ status: "active" }), save);

    await userEvent.clear(origins());
    await userEvent.tab();

    await expect.element(origins()).toHaveValue("");
    await expect
      .element(origins())
      .toHaveAccessibleDescription(/widget_admin_blocker_allowed_origins_empty/);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(save).not.toHaveBeenCalled();
  });

  test("a list emptied on a live widget is sent once the widget is paused", async () => {
    const save = vi.fn(async (update: WidgetUpdate) => widget(update as Partial<Widget>));
    const { autosave } = setup(widget({ status: "active" }), save);
    await userEvent.clear(origins());
    await userEvent.tab();
    expect(autosave.stranded).toBe(true);

    autosave.replace(widget({ status: "paused", revision: 1 }));
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({ allowed_origins: [], revision: 1 });
    await vi.waitFor(() => expect(autosave.unsaved).toBe(false));
    await expect.element(origins()).toHaveValue("");
  });
});

describe("WidgetRulesFields policy", () => {
  test("an editor is held to the organisation's limits before saving", async () => {
    const save = vi.fn();
    setup(widget(), save);
    await userEvent.fill(budget(), "6000");
    await userEvent.tab();
    await expect.element(budget()).toHaveAttribute("aria-invalid", "true");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(save).not.toHaveBeenCalled();

    const protection = page.getByLabelText("widget_admin_bot_protection", { exact: true });
    await expect
      .element(protection)
      .toHaveAccessibleDescription("widget_admin_blocker_bot_protection");
  });

  test.each([
    ["an older, looser policy", { ...policy, max_daily_token_budget: 3_000_000_000 }],
    ["no readable policy", null]
  ])("a budget above the API's ceiling stays in the field under %s", async (_case, rules) => {
    const save = vi.fn(async (update: WidgetUpdate) => widget(update as Partial<Widget>));
    setup(widget(), save, rules);
    await userEvent.fill(budget(), "2000000001");
    await userEvent.tab();
    await expect.element(budget()).toHaveAttribute("aria-invalid", "true");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(save).not.toHaveBeenCalled();

    await userEvent.fill(budget(), "2000000000");
    await userEvent.tab();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({
      limits: expect.objectContaining({ daily_token_budget: 2_000_000_000 }),
      revision: 0
    });
  });

  test("a saved value outside a tightened policy is flagged at its field", async () => {
    setup(widget({ activation_blockers: ["daily_token_budget_exceeds_policy"] }));
    await expect.element(budget()).toHaveAttribute("aria-invalid", "true");
    await expect
      .element(budget())
      .toHaveAccessibleDescription(/widget_admin_blocker_budget_policy/);
  });

  test("a forbidden 'none' is explained once, not as a hint and an error both", async () => {
    setup(
      widget({
        bot_protection: "none",
        activation_blockers: ["bot_protection_none_not_allowed"]
      })
    );
    const protection = page.getByLabelText("widget_admin_bot_protection", { exact: true });
    await expect.element(protection).toHaveAttribute("aria-invalid", "true");
    await expect
      .element(protection)
      .toHaveAccessibleDescription("widget_admin_blocker_bot_protection");
  });

  test("each card title is a section heading", async () => {
    setup(widget());
    for (const name of [
      "widget_admin_placement",
      "widget_admin_limits",
      "widget_admin_privacy",
      "widget_admin_protection"
    ]) {
      await expect.element(page.getByRole("heading", { level: 2, name })).toBeVisible();
    }
  });
});

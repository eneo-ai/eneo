// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const apiKey = {
  id: "key-1",
  key_prefix: "sk_ab",
  key_suffix: "wxyz",
  name: "Min integration",
  key_type: "sk_",
  permission: "read",
  scope_type: "tenant",
  state: "active",
  expires_at: null,
  created_at: "2026-09-01T08:00:00Z"
} as Schema<"ApiKeyV2">;

const state = vi.hoisted(() => ({
  preferences: {
    enabled: true,
    days_before_expiry: [30, 14, 7],
    auto_follow_published_assistants: false,
    auto_follow_published_apps: false
  },
  policy: {
    enabled: true,
    default_days_before_expiry: [30, 14, 7],
    max_days_before_expiry: 60,
    allow_auto_follow_published_assistants: true,
    allow_auto_follow_published_apps: false
  },
  failRead: false,
  failSave: false,
  saveGate: null as Promise<void> | null,
  writes: [] as object[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      if (path === "/api/v1/api-keys/notification-preferences" && state.failRead)
        return Promise.reject(new Error("Temporarily unavailable"));
      const data =
        path === "/api/v1/api-keys"
          ? { items: [apiKey], next_cursor: null, total_count: 1 }
          : path === "/api/v1/api-keys/notification-preferences"
            ? state.preferences
            : path === "/api/v1/api-keys/policy-constraints"
              ? { notification_policy: state.policy }
              : {};
      return Promise.resolve({ data, response: new Response("{}") });
    },
    PUT: async (
      _path: string,
      { body }: { body: Schema<"ApiKeyNotificationPreferencesUpdate"> }
    ) => {
      state.writes.push(body);
      if (state.saveGate) await state.saveGate;
      if (state.failSave) return Promise.reject(new Error("Temporarily unavailable"));
      return Promise.resolve({
        data: { ...state.preferences, ...body },
        response: new Response("{}")
      });
    }
  }
}));

import { ApiKeys } from "./account-api-keys";

afterEach(cleanup);
beforeEach(() => {
  state.preferences.enabled = true;
  state.preferences.days_before_expiry = [30, 14, 7];
  state.policy.enabled = true;
  state.failRead = false;
  state.failSave = false;
  state.saveGate = null;
  state.writes = [];
});

describe("ApiKeys (account)", () => {
  it("names the key table like the account page it is on", async () => {
    renderInApp(<ApiKeys />, { appContext: testAppContext({ permissions: ["api_keys"] }) });

    const table = await screen.findByRole("table", { name: "API-nycklar" });
    expect(await within(table).findByText("Min integration")).toBeTruthy();
  });

  it("shows the keys in the panel of the selected state tab", async () => {
    const { container } = renderInApp(<ApiKeys />, {
      appContext: testAppContext({ permissions: ["api_keys"] })
    });

    const panel = screen.getByRole("tabpanel", { name: "Aktiv" });
    expect(screen.getByRole("tab", { name: "Aktiv" }).getAttribute("aria-controls")).toBe(panel.id);
    expect(await within(panel).findByText("Min integration")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows and saves every reminder day, within the tenant's maximum", async () => {
    renderInApp(<ApiKeys />);
    const days = await screen.findByRole("textbox", { name: "Påminnelsedagar" });
    expect((days as HTMLInputElement).value).toBe("30, 14, 7");
    expect(screen.getByText("Maxgräns från organisationen: 60 dagar.")).toBeTruthy();

    fireEvent.change(days, { target: { value: "21, 14, 7, 14" } });
    fireEvent.blur(days);
    await vi.waitFor(() => expect(state.writes).toEqual([{ days_before_expiry: [21, 14, 7] }]));
  });

  it("keeps an invalid reminder draft without sending it", async () => {
    renderInApp(<ApiKeys />);
    const days = await screen.findByRole("textbox", { name: "Påminnelsedagar" });
    fireEvent.change(days, { target: { value: "90, 7" } });
    fireEvent.blur(days);
    expect(days.getAttribute("aria-invalid")).toBe("true");
    expect((days as HTMLInputElement).value).toBe("90, 7");
    expect(state.writes).toEqual([]);
  });

  it("adds a preset without discarding existing reminder days", async () => {
    renderInApp(<ApiKeys />);
    const preset = await screen.findByRole("button", { name: "Lägg till 60 dagar" });
    expect(screen.queryByRole("button", { name: "Lägg till 90 dagar" })).toBeNull();
    fireEvent.click(preset);
    await vi.waitFor(() => expect(state.writes).toEqual([{ days_before_expiry: [60, 30, 14, 7] }]));
    expect(
      (screen.getByRole("textbox", { name: "Påminnelsedagar" }) as HTMLInputElement).value
    ).toBe("60, 30, 14, 7");
  });

  it("explains a policy-locked option and refuses its mutation", async () => {
    renderInApp(<ApiKeys />);
    const apps = await screen.findByRole("switch", { name: "Följ automatiskt publicerade appar" });
    await act(async () => fireEvent.click(apps));
    expect(state.writes).toEqual([]);
    expect(
      screen.getByText("Inaktiverad av organisationens policy.", { selector: "p" })
    ).toBeTruthy();
  });

  it("keeps a saving switch focused and suppresses another toggle until the write settles", async () => {
    let finish!: () => void;
    state.saveGate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    renderInApp(<ApiKeys />);
    const toggle = await screen.findByRole("switch", {
      name: "Följ automatiskt publicerade assistenter"
    });
    toggle.focus();
    try {
      fireEvent.click(toggle);
      await vi.waitFor(() =>
        expect(toggle.closest("section")?.getAttribute("aria-busy")).toBe("true")
      );
      expect(toggle.hasAttribute("disabled")).toBe(false);
      expect(toggle.getAttribute("aria-disabled")).not.toBe("true");
      expect(document.activeElement).toBe(toggle);
      await act(async () => fireEvent.click(toggle));
      expect(state.writes).toEqual([{ auto_follow_published_assistants: true }]);
    } finally {
      await act(async () => finish());
    }
    await vi.waitFor(() =>
      expect(toggle.closest("section")?.getAttribute("aria-busy")).toBe("false")
    );
    expect(document.activeElement).toBe(toggle);
  });

  it("shows the tenant's disabled policy and prevents enabling reminders", async () => {
    state.policy.enabled = false;
    state.preferences.enabled = false;
    renderInApp(<ApiKeys />);
    const toggle = await screen.findByRole("switch", { name: "Utgångspåminnelser" });
    await act(async () => fireEvent.click(toggle));
    expect(state.writes).toEqual([]);
    expect(
      screen.getByText(
        "Organisationens policy har inaktiverat utgångspåminnelser för detta konto.",
        { selector: "p" }
      )
    ).toBeTruthy();
  });

  it("retries a failed preferences read without hiding the key list", async () => {
    state.failRead = true;
    renderInApp(<ApiKeys />);
    const retry = await screen.findByRole("button", { name: /Försök igen/ });
    expect(screen.getByRole("table", { name: "API-nycklar" })).toBeTruthy();
    state.failRead = false;
    fireEvent.click(retry);
    expect(await screen.findByRole("textbox", { name: "Påminnelsedagar" })).toBeTruthy();
  });

  it("keeps the reminder draft after a failed save and retries the same full setting", async () => {
    state.failSave = true;
    renderInApp(<ApiKeys />);
    const days = await screen.findByRole("textbox", { name: "Påminnelsedagar" });
    fireEvent.change(days, { target: { value: "21, 14, 7" } });
    fireEvent.blur(days);
    await vi.waitFor(() => expect(state.writes).toHaveLength(1));
    expect((days as HTMLInputElement).value).toBe("21, 14, 7");
    state.failSave = false;
    fireEvent.blur(days);
    await vi.waitFor(() =>
      expect(state.writes).toEqual([
        { days_before_expiry: [21, 14, 7] },
        { days_before_expiry: [21, 14, 7] }
      ])
    );
  });
});

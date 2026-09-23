/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import type { WidgetTheme } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, () => string>>({}, { get: (_target, key) => () => String(key) })
}));

import WidgetThemeFields from "./WidgetThemeFields.svelte";

// The same fields serve the widget editor and the template editor; both
// spread each change into the theme and autosave it whole, so what leaves
// onChange is exactly what the PATCH carries.
function renderFields(theme: Partial<WidgetTheme> = {}) {
  const onChange = vi.fn<(change: Partial<WidgetTheme>) => void>();
  let current: WidgetTheme = { primary_color: "#1F4E79", radius: 12, ...theme } as WidgetTheme;
  const screen = render(WidgetThemeFields, {
    theme: current,
    onChange: (change) => {
      onChange(change);
      current = { ...current, ...change };
      void screen.rerender({ theme: current });
    }
  });
  return { onChange, screen };
}

const primary = () => page.getByLabelText("widget_admin_primary_color", { exact: true });
const header = () => page.getByLabelText("widget_admin_header_color", { exact: true });

describe("WidgetThemeFields colours", () => {
  test("a shorthand colour is sent as #RRGGBB and shown that way once settled", async () => {
    const { onChange } = renderFields();
    await userEvent.fill(primary(), "#abc");
    expect(onChange).toHaveBeenLastCalledWith({ primary_color: "#AABBCC" });
    // The draft keeps what was typed until the field is left...
    await expect.element(primary()).toHaveValue("#abc");
    const picker = document.querySelector<HTMLInputElement>("input[type=color]");
    expect(picker?.value).toBe("#aabbcc");
    await userEvent.tab();
    await expect.element(primary()).toHaveValue("#AABBCC");

    await userEvent.fill(header(), "#fed");
    expect(onChange).toHaveBeenLastCalledWith({ header_color: "#FFEEDD" });
  });

  test("typing a six-digit colour is not interrupted by its valid three-digit prefix", async () => {
    const { onChange } = renderFields();
    await userEvent.fill(primary(), "");
    await userEvent.type(primary(), "#1f4e79");
    await expect.element(primary()).toHaveValue("#1f4e79");
    expect(onChange).toHaveBeenLastCalledWith({ primary_color: "#1F4E79" });
    const sent = onChange.mock.calls.map(([change]) => change.primary_color);
    expect(sent).toContain("#11FF44");
    expect(sent.every((colour) => /^#[0-9A-F]{6}$/.test(colour ?? ""))).toBe(true);
  });
});

describe("WidgetThemeFields locks", () => {
  test("a template-governed appearance freezes every control and says why", async () => {
    const onChange = vi.fn();
    render(WidgetThemeFields, {
      theme: { primary_color: "#1F4E79", radius: 12 } as WidgetTheme,
      onChange,
      locked: true,
      lockHint: "Styrs av mallen Kommunblå"
    });
    await expect.element(primary()).toBeDisabled();
    await expect.element(page.getByLabelText("widget_admin_radius")).toBeDisabled();
    await expect.element(page.getByText("Styrs av mallen Kommunblå")).toBeVisible();
    expect(document.querySelector<HTMLInputElement>("input[type=color]")?.disabled).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("WidgetThemeFields radius", () => {
  test("a fraction stays in the field with an error instead of reaching the API", async () => {
    const { onChange } = renderFields();
    const radius = page.getByLabelText("widget_admin_radius", { exact: true });
    await userEvent.fill(radius, "1.5");
    await expect.element(radius).toHaveAttribute("aria-invalid", "true");
    await expect.element(radius).toHaveAccessibleDescription(/widget_admin_value_out_of_range/);
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.fill(radius, "8");
    expect(onChange).toHaveBeenLastCalledWith({ radius: 8 });
    await expect.element(radius).toHaveAttribute("aria-invalid", "false");
  });
});

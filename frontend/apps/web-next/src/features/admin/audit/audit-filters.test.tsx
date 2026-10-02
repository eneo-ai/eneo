// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import type { AuditFilters } from "./audit";
import { activeFilterCount, AuditFilterBar } from "./audit-filters";
import { DEFAULT_AUDIT_FILTERS } from "./audit-url-filters";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) =>
      Promise.resolve({
        data:
          path === "/api/v1/audit/config/actions"
            ? {
                actions: [
                  { action: "user_created", category: "admin_actions", enabled: true },
                  { action: "user_deleted", category: "admin_actions", enabled: true }
                ]
              }
            : { items: [{ id: "u1", email: "anna.lind@example.se" }], total_count: 1 },
        response: new Response("{}")
      })
  }
}));

afterEach(() => {
  cleanup();
  setViewport("desktop");
});

const filtered: AuditFilters = {
  ...DEFAULT_AUDIT_FILTERS,
  actions: ["user_created", "user_deleted"],
  from_date: "2026-09-01",
  to_date: "2026-09-30"
};

describe("AuditFilterBar", () => {
  it("has the search as the primary field and counts the other filters on the button", async () => {
    const onChange = vi.fn();
    const { container } = renderInApp(
      <AuditFilterBar filters={DEFAULT_AUDIT_FILTERS} onChange={onChange} />
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Sök" }), { target: { value: "anna" } });
    expect(onChange).toHaveBeenCalledWith({ search: "anna" });
    expect(screen.getByRole("button", { name: "Filter" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Filter" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rensa alla filter" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("shows the active filters as chips that can be removed one by one", async () => {
    const onChange = vi.fn();
    const { container } = renderInApp(<AuditFilterBar filters={filtered} onChange={onChange} />);

    expect(activeFilterCount(filtered)).toBe(3);
    expect(screen.getByRole("button", { name: "Filter (3)" })).toBeTruthy();
    const chips = screen.getByRole("list", { name: "Filter" });
    expect(
      within(chips)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["Användare skapad", "Användare borttagen", "1 sep. 2026 – 30 sep. 2026"]);

    fireEvent.click(within(chips).getByRole("button", { name: "Ta bort Användare skapad" }));
    expect(onChange).toHaveBeenLastCalledWith({ actions: ["user_deleted"] });
    fireEvent.click(
      within(chips).getByRole("button", { name: "Ta bort 1 sep. 2026 – 30 sep. 2026" })
    );
    expect(onChange).toHaveBeenLastCalledWith({ from_date: undefined, to_date: undefined });

    fireEvent.click(screen.getByRole("button", { name: "Rensa alla filter" }));
    expect(onChange).toHaveBeenLastCalledWith({
      actions: [],
      from_date: undefined,
      to_date: undefined,
      search: "",
      userId: undefined,
      userLabel: undefined
    });
    await expectNoAxeViolations(container);
  });

  it("pins the per-user view: a user chip, no action filter and the search explains why it waits", () => {
    const onChange = vi.fn();
    renderInApp(
      <AuditFilterBar
        filters={{ ...DEFAULT_AUDIT_FILTERS, userId: "u1", userLabel: "anna.lind@example.se" }}
        onChange={onChange}
      />
    );
    const chips = screen.getByRole("list", { name: "Filter" });
    expect(within(chips).getByText("anna.lind@example.se")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Sök" }).getAttribute("aria-disabled")).toBe("true");

    fireEvent.click(within(chips).getByRole("button", { name: "Ta bort anna.lind@example.se" }));
    expect(onChange).toHaveBeenLastCalledWith({ userId: undefined, userLabel: undefined });
  });

  it("opens the user, action and period fields in a popover on a wide screen", async () => {
    const onChange = vi.fn();
    renderInApp(<AuditFilterBar filters={DEFAULT_AUDIT_FILTERS} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const dialog = await screen.findByRole("dialog", { name: "Filter" });
    expect(within(dialog).getByRole("combobox", { name: "Användare" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: /Åtgärd/ })).toBeTruthy();
    const period = within(dialog).getByRole("button", { name: /Period/ });
    expect(period).toBeTruthy();
    // globals.css (section 11) sizes the range input's calendar toggle by this markup.
    const toggle = within(dialog).getByRole("button", { name: "Öppna kalender" });
    expect(
      toggle.matches(
        ".astryx-date-range-input > button:has(> .astryx-date-range-input-toggle-icon)"
      )
    ).toBe(true);

    fireEvent.click(within(dialog).getByRole("button", { name: "Klar" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Filter" })).toBeNull());
  });

  it("opens the fields in a bottom sheet on a phone", async () => {
    setViewport("phone");
    renderInApp(<AuditFilterBar filters={DEFAULT_AUDIT_FILTERS} onChange={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Filter" });
    expect(button.getAttribute("aria-haspopup")).toBe("dialog");
    fireEvent.click(button);
    const sheet = await screen.findByRole("dialog", { name: "Filter" });
    expect(within(sheet).getByRole("combobox", { name: "Användare" })).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Klar" }));
    await waitFor(() => expect(button.getAttribute("aria-expanded")).toBe("false"));
  });
});

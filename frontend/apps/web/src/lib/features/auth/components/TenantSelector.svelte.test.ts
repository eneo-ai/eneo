import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (args?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (args?: Record<string, unknown>) =>
        args ? `${String(key)}:${Object.values(args).join(",")}` : String(key)
    }
  )
}));

import TenantSelector from "./TenantSelector.svelte";

const tenants = [
  { slug: "sundsvall", name: "sundsvall.se", display_name: "Sundsvalls kommun" },
  { slug: "ange", name: "ange.se", display_name: "Ånge kommun" },
  { slug: "timra", name: "timra.se", display_name: "Timrå kommun" }
];

describe("tenant selector", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  test("lists organisations as a labelled list of buttons", async () => {
    render(TenantSelector, { onTenantSelect: vi.fn(), tenants });
    const list = page.getByRole("list", { name: "select_your_organization" });
    await expect.element(list).toBeVisible();
    await expect.element(page.getByRole("button", { name: /Sundsvalls kommun/ })).toBeVisible();
    await expect.element(page.getByLabelText("search_organizations")).toBeVisible();
    await expect.element(page.getByText("tenant_results_other:3")).toBeInTheDocument();
  });

  test("filters by name and announces the result count", async () => {
    render(TenantSelector, { onTenantSelect: vi.fn(), tenants });
    await page.getByLabelText("search_organizations").click();
    await userEvent.keyboard("timr");
    await expect.element(page.getByRole("button", { name: /Timrå kommun/ })).toBeVisible();
    await expect.element(page.getByText("tenant_results_one")).toBeInTheDocument();
    expect(page.getByRole("button", { name: /Sundsvalls kommun/ }).query()).toBeNull();
    await userEvent.keyboard("zzz");
    await expect.element(page.getByText("try_different_search_term")).toBeVisible();
  });

  test("remembers the chosen organisation and notifies the parent", async () => {
    const onTenantSelect = vi.fn();
    render(TenantSelector, { onTenantSelect, tenants });
    await page.getByRole("button", { name: /Ånge kommun/ }).click();
    expect(onTenantSelect).toHaveBeenCalledWith("ange");
    expect(localStorage.getItem("eneo:last-tenant")).toBe("ange");
  });

  test("auto-selects a remembered organisation that is still available", async () => {
    localStorage.setItem("eneo:last-tenant", "timra");
    const onTenantSelect = vi.fn();
    render(TenantSelector, { onTenantSelect, tenants });
    await expect.poll(() => onTenantSelect.mock.calls).toEqual([["timra"]]);
  });

  test("forgets a remembered organisation that no longer exists", async () => {
    localStorage.setItem("eneo:last-tenant", "gone");
    const onTenantSelect = vi.fn();
    render(TenantSelector, { onTenantSelect, tenants });
    await expect.element(page.getByRole("list")).toBeVisible();
    expect(onTenantSelect).not.toHaveBeenCalled();
    expect(localStorage.getItem("eneo:last-tenant")).toBeNull();
  });
});

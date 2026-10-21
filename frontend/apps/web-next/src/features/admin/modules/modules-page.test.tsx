// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({
  GET: vi.fn((path: string) =>
    Promise.resolve({
      data: path === "/api/v1/admin/api-keys" ? { items: [], next_cursor: null } : { items: [] },
      response: new Response("{}")
    })
  ),
  PUT: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ModulesPage } from "./modules-page";

afterEach(() => vi.clearAllMocks());

const problemOf = (control: HTMLElement) =>
  document.getElementById(control.getAttribute("aria-describedby")!.split(" ")[0]!)?.textContent;

it("shows each problem at its field on install, and moves focus to the first", async () => {
  const { container } = renderInApp(<ModulesPage title="Moduler" />);
  const install = screen.getByRole("button", { name: "Installera modul" });
  // Never disabled: a disabled button says nothing about what is missing.
  expect((install as HTMLButtonElement).disabled).toBe(false);
  // Loaded: the service keys to pick from.
  await waitFor(() =>
    expect((screen.getByLabelText("Service key") as HTMLSelectElement).disabled).toBe(false)
  );

  fireEvent.click(install);
  const key = screen.getByLabelText("Modulnyckel");
  const urls = screen.getByLabelText("Callback-URL:er");
  const serviceKey = screen.getByLabelText("Service key");
  expect(problemOf(key)).toBe("Detta fält är obligatoriskt");
  expect(problemOf(urls)).toBe("Detta fält är obligatoriskt");
  expect(problemOf(serviceKey)).toBe("Detta fält är obligatoriskt");
  expect(document.activeElement).toBe(key);
  await expectNoAxeViolations(container);

  // The key's format is checked too.
  fireEvent.change(key, { target: { value: "-diariet" } });
  fireEvent.click(install);
  expect(problemOf(key)).toBe(
    "Börja med en bokstav eller siffra och använd bara bokstäver, siffror, punkt, bindestreck och understreck."
  );

  fireEvent.change(key, { target: { value: "diariet" } });
  fireEvent.click(install);
  expect(key.getAttribute("aria-invalid")).toBeNull();
  expect(document.activeElement).toBe(urls);
  expect(api.PUT).not.toHaveBeenCalled();
});

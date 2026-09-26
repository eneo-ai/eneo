// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({
  POST: vi.fn(),
  GET: vi.fn((path: string) =>
    Promise.resolve({
      data: {
        items:
          path === "/api/v1/templates/apps/"
            ? [
                {
                  id: "t1",
                  name: "Protokollsammanfattning",
                  description: "Sammanfattar ett protokoll.",
                  wizard: {}
                }
              ]
            : []
      },
      response: new Response("{}")
    })
  )
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => ({ space: makeSpace(), routeId: "space-1", can: () => true }) };
});

import { CreateAppButton } from "./create-app";

afterEach(() => vi.clearAllMocks());

describe("CreateAppButton", () => {
  it("names the split button's menu after what it offers", () => {
    renderInApp(<CreateAppButton />, {
      appContext: testAppContext({ settings: { using_templates: true } })
    });

    const more = screen.getByRole("button", { name: "Fler sätt att skapa" });
    fireEvent.keyDown(more, { key: "Enter" });
    const menu = screen.getByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent?.trim())
    ).toEqual(["Börja med en mall..."]);
  });

  it("shows a missing name at the field on create, which takes focus", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(<CreateAppButton />, { appContext: testAppContext() });
    fireEvent.click(screen.getByRole("button", { name: "Skapa app" }));
    const dialog = await screen.findByRole("dialog", { name: "Skapa en tom app" });
    const create = within(dialog).getByRole("button", { name: "Skapa app" }) as HTMLButtonElement;
    // Never disabled: a disabled button says nothing about what is missing.
    expect(create.disabled).toBe(false);

    fireEvent.click(create);
    const name = within(dialog).getByLabelText("Namn");
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(name.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Detta fält är obligatoriskt"
    );
    expect(document.activeElement).toBe(name);
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(dialog);

    fireEvent.change(name, { target: { value: "Upphandling" } });
    fireEvent.click(create);
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  });

  it("says a template is needed, then its name, when creating from a template", async () => {
    renderInApp(<CreateAppButton />, {
      appContext: testAppContext({ settings: { using_templates: true } })
    });
    fireEvent.keyDown(screen.getByRole("button", { name: "Fler sätt att skapa" }), {
      key: "Enter"
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Börja med en mall..." }));
    const dialog = await screen.findByRole("dialog", { name: "Välj en mall" });
    const template = await within(dialog).findByRole("button", {
      name: /Protokollsammanfattning/
    });
    const create = within(dialog).getByRole("button", { name: "Skapa app" });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((create as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(create);
    const templates = within(dialog).getByRole("group", { name: "Välj en mall" });
    expect(templates.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(template);

    fireEvent.click(template);
    expect(template.getAttribute("aria-pressed")).toBe("true");
    const name = within(dialog).getByLabelText("Namn");
    fireEvent.change(name, { target: { value: "" } });
    fireEvent.click(create);
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(name);
    expect(api.POST).not.toHaveBeenCalled();
    await expectNoAxeViolations(dialog);
  });
});

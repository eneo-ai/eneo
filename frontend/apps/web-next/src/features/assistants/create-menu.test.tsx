// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => ({ space: makeSpace(), routeId: "space-1", can: () => true }) };
});

import { CreateChatAppMenu } from "./create-menu";

afterEach(() => vi.clearAllMocks());

describe("CreateChatAppMenu", () => {
  it("names the split button's menu after what it offers", () => {
    renderInApp(<CreateChatAppMenu />, {
      appContext: testAppContext({ settings: { using_templates: true } })
    });

    const more = screen.getByRole("button", { name: "Fler sätt att skapa" });
    fireEvent.keyDown(more, { key: "Enter" });
    const menu = screen.getByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent?.trim())
    ).toEqual(["Skapa ny assistent", "Börja med en mall...", "Skapa ny gruppchatt"]);
  });

  it("shows a missing name at the field on create, which takes focus", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });
    fireEvent.click(screen.getByRole("button", { name: "Skapa assistent" }));
    const dialog = await screen.findByRole("dialog", { name: "Skapa ny assistent" });
    const create = within(dialog).getByRole("button", {
      name: "Skapa assistent"
    }) as HTMLButtonElement;
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
});

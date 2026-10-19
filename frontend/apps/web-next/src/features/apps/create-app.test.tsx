// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";
import { clearJustCreated, isJustCreated } from "@/features/spaces/just-created";

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

const created = (id: string) =>
  Promise.resolve({ data: { id }, response: new Response("{}", { status: 200 }) });
const collision = () =>
  Promise.resolve({
    error: { message: "Name collision", eneo_error_code: 9017 },
    response: new Response("{}", { status: 400 })
  });

afterEach(() => {
  vi.clearAllMocks();
  clearJustCreated("app", "p-new");
});

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

  it("creates the app as 'Ny app' at once and opens its editor", async () => {
    let finish!: (value: Awaited<ReturnType<typeof created>>) => void;
    api.POST.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderInApp(<CreateAppButton />, { appContext: testAppContext() });

    const create = screen.getByRole("button", { name: "Skapa app" }) as HTMLButtonElement;
    fireEvent.click(create);
    // No name dialog in between: the editor's first field is the name.
    expect(screen.queryByRole("dialog")).toBeNull();
    // Busy, the button stays enabled so it keeps focus; a second press is ignored.
    await waitFor(() => expect(create.getAttribute("aria-busy")).toBe("true"));
    expect(create.disabled).toBe(false);
    fireEvent.click(create);
    expect(api.POST).toHaveBeenCalledTimes(1);

    await act(async () => finish(await created("p-new")));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/apps/p-new/edit")
    );
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST.mock.calls[0]?.[1]).toMatchObject({ body: { name: "Ny app" } });
    expect(isJustCreated("app", "p-new")).toBe(true);
  });

  it("numbers the name when 'Ny app' is taken", async () => {
    api.POST.mockReturnValueOnce(collision()).mockReturnValueOnce(created("p-new"));
    renderInApp(<CreateAppButton />, { appContext: testAppContext() });

    fireEvent.click(screen.getByRole("button", { name: "Skapa app" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledTimes(1));
    expect(
      api.POST.mock.calls.map((call) => (call[1] as { body: { name: string } }).body.name)
    ).toEqual(["Ny app", "Ny app 2"]);
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

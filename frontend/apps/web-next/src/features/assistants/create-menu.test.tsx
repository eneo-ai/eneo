// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";
import { clearJustCreated, isJustCreated } from "@/features/spaces/just-created";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => ({ space: makeSpace(), routeId: "space-1", can: () => true }) };
});

import { CreateChatAppMenu } from "./create-menu";

const created = (id: string) =>
  Promise.resolve({ data: { id }, response: new Response("{}", { status: 200 }) });
const collision = () =>
  Promise.resolve({
    error: { message: "Name collision", eneo_error_code: 9017 },
    response: new Response("{}", { status: 400 })
  });

afterEach(() => {
  vi.clearAllMocks();
  clearJustCreated("assistant", "a-new");
  clearJustCreated("group-chat", "g-new");
});

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

  it("creates the assistant as 'Ny assistent' at once and opens its editor", async () => {
    let finish!: (value: Awaited<ReturnType<typeof created>>) => void;
    api.POST.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });

    const create = screen.getByRole("button", { name: "Skapa assistent" }) as HTMLButtonElement;
    fireEvent.click(create);
    // No name dialog in between: the editor's first field is the name.
    expect(screen.queryByRole("dialog")).toBeNull();
    // Busy, the button stays enabled so it keeps focus; a second press is ignored.
    await waitFor(() => expect(create.getAttribute("aria-busy")).toBe("true"));
    expect(create.disabled).toBe(false);
    fireEvent.click(create);
    expect(api.POST).toHaveBeenCalledTimes(1);

    await act(async () => finish(await created("a-new")));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/assistants/a-new/edit")
    );
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST.mock.calls[0]?.[1]).toMatchObject({ body: { name: "Ny assistent" } });
    // The editor focuses the name and announces the creation.
    expect(isJustCreated("assistant", "a-new")).toBe(true);
  });

  it("numbers the name when 'Ny assistent' is taken", async () => {
    api.POST.mockReturnValueOnce(collision()).mockReturnValueOnce(created("a-new"));
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });

    fireEvent.click(screen.getByRole("button", { name: "Skapa assistent" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledTimes(1));
    expect(
      api.POST.mock.calls.map((call) => (call[1] as { body: { name: string } }).body.name)
    ).toEqual(["Ny assistent", "Ny assistent 2"]);
  });

  it("creates a group chat as 'Ny gruppchatt' from the menu", async () => {
    api.POST.mockReturnValue(created("g-new"));
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });

    fireEvent.keyDown(screen.getByRole("button", { name: "Fler sätt att skapa" }), {
      key: "Enter"
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Skapa ny gruppchatt" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/group-chats/g-new/edit")
    );
    expect(api.POST.mock.calls[0]?.[0]).toBe("/api/v1/spaces/{id}/applications/group-chats/");
    expect(api.POST.mock.calls[0]?.[1]).toMatchObject({ body: { name: "Ny gruppchatt" } });
    expect(isJustCreated("group-chat", "g-new")).toBe(true);
  });
});

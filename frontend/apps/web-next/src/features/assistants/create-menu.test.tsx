// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { openMenuOnRelease, tap } from "@/test/menus";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { clearJustCreated, isJustCreated } from "@/features/spaces/just-created";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
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
  it("names the split button's menu after what it offers, and opens it on release", async () => {
    renderInApp(<CreateChatAppMenu />, {
      appContext: testAppContext({ settings: { using_templates: true } })
    });

    const menu = await openMenuOnRelease(
      screen.getByRole("button", { name: "Fler sätt att skapa" })
    );
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent?.trim())
    ).toEqual(["Skapa ny assistent", "Börja med en mall...", "Skapa ny gruppchatt"]);
    // The theme's coarse-pointer rule gives every row 44 px through this class.
    for (const item of within(menu).getAllByRole("menuitem")) {
      expect(item.classList).toContain("astryx-dropdown-menu-item");
    }
  });

  it("hides only its buttons on a phone: a dialog they opened is not inside the hidden part", () => {
    renderInApp(<CreateChatAppMenu isHiddenOnPhone />);
    const hidden = screen
      .getByRole("button", { name: "Skapa assistent" })
      .closest(".phone\\:hidden");
    expect(hidden).toBeTruthy();
    expect(hidden?.parentElement?.querySelector(":scope > dialog")).toBeTruthy();
  });

  it("wraps a long Skapa assistent onto a second line instead of cutting it off (1.4.4)", () => {
    // Astryx buttons keep their label on one line at a fixed height and cut it
    // with an ellipsis; at 320 px with large text this label would lose its end.
    renderInApp(<CreateChatAppMenu />);

    const create = screen.getByRole("button", { name: "Skapa assistent" });
    expect(create.className.split(" ")).toEqual(
      expect.arrayContaining(["h-auto", "min-h-(--size-element-md)", "whitespace-normal"])
    );
  });

  it("keeps its menu half as tall as a wrapped label, small or not", () => {
    // In the overview's create card the secondary label wraps to two lines:
    // the chevron half stretches with it instead of keeping one line's height.
    for (const secondary of [false, true]) {
      renderInApp(<CreateChatAppMenu secondary={secondary} />);
      const more = screen.getByRole("button", { name: "Fler sätt att skapa" });
      // Stretched, it keeps a square's width (a 44 px target on touch).
      expect(more.className.split(" ")).toEqual(
        expect.arrayContaining([
          "h-auto",
          "self-stretch",
          "pointer-coarse:min-w-11",
          secondary ? "min-w-(--size-element-sm)" : "min-w-(--size-element-md)"
        ])
      );
      cleanup();
    }
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

  it("asks for a group-chat name before creating it and opens its editor by default", async () => {
    api.POST.mockReturnValue(created("g-new"));
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });

    fireEvent.keyDown(screen.getByRole("button", { name: "Fler sätt att skapa" }), {
      key: "Enter"
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Skapa ny gruppchatt" }));

    const dialog = await screen.findByRole("dialog", { name: "Skapa en ny gruppchatt" });
    expect(api.POST).not.toHaveBeenCalled();
    expect(
      within(dialog).getByRole("switch", {
        name: "Öppna gruppchatt-redigerare efter skapande",
        checked: true
      })
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Gruppchattens namn" }), {
      target: { value: "Projektgruppen" }
    });
    await expectNoAxeViolations(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Skapa gruppchatt" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/group-chats/g-new/edit")
    );
    expect(api.POST.mock.calls[0]?.[0]).toBe("/api/v1/spaces/{id}/applications/group-chats/");
    expect(api.POST.mock.calls[0]?.[1]).toMatchObject({ body: { name: "Projektgruppen" } });
    expect(isJustCreated("group-chat", "g-new")).toBe(true);
  });

  it("validates the group name, submits once while pending and can stay on the list", async () => {
    let finish!: (value: Awaited<ReturnType<typeof created>>) => void;
    api.POST.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });
    fireEvent.keyDown(screen.getByRole("button", { name: "Fler sätt att skapa" }), {
      key: "Enter"
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Skapa ny gruppchatt" }));
    const dialog = await screen.findByRole("dialog", { name: "Skapa en ny gruppchatt" });
    const name = within(dialog).getByRole("textbox", { name: "Gruppchattens namn" });
    const create = within(dialog).getByRole("button", { name: "Skapa gruppchatt" });
    fireEvent.click(create);
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(name);
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.change(name, { target: { value: "Projektgruppen" } });
    fireEvent.click(
      within(dialog).getByRole("switch", {
        name: "Öppna gruppchatt-redigerare efter skapande"
      })
    );
    fireEvent.click(create);
    await waitFor(() => expect(create.getAttribute("aria-busy")).toBe("true"));
    const choice = within(dialog).getByRole("switch", {
      name: "Öppna gruppchatt-redigerare efter skapande"
    });
    choice.focus();
    expect(document.activeElement).toBe(choice);
    fireEvent.click(choice);
    expect(within(dialog).getByRole("switch", { checked: false })).toBe(choice);
    fireEvent.click(create);
    expect(api.POST).toHaveBeenCalledTimes(1);
    await act(async () => finish(await created("g-new")));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(router.push).not.toHaveBeenCalled();
    expect(isJustCreated("group-chat", "g-new")).toBe(false);
  });

  it.each([
    [
      "Avbryt",
      (dialog: HTMLElement) =>
        fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }))
    ],
    ["Escape", (dialog: HTMLElement) => fireEvent.keyDown(dialog, { key: "Escape" })]
  ])(
    "returns focus to the menu button when a tapped Skapa ny gruppchatt is closed with %s",
    async (_, close) => {
      renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });
      const more = screen.getByRole("button", { name: "Fler sätt att skapa" });
      // A tap: the menu closes and leaves focus on its own hidden list, which
      // the dialog would otherwise return focus to.
      tap(
        within(await openMenuOnRelease(more)).getByRole("menuitem", { name: "Skapa ny gruppchatt" })
      );
      const dialog = await screen.findByRole("dialog", { name: "Skapa en ny gruppchatt" });

      close(dialog);

      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(more));
    }
  );

  it("returns focus to the menu button when Skapa ny gruppchatt was chosen from the keyboard", async () => {
    renderInApp(<CreateChatAppMenu />, { appContext: testAppContext() });
    const more = screen.getByRole("button", { name: "Fler sätt att skapa" });
    more.focus();
    fireEvent.keyDown(more, { key: "Enter" });
    // A keyboard open focuses the first item (a pointer open, the menu itself).
    const first = await screen.findByRole("menuitem", { name: "Skapa ny assistent" });
    await waitFor(() => expect(document.activeElement).toBe(first));
    fireEvent.keyDown(first, { key: "ArrowDown" });
    const groupChat = screen.getByRole("menuitem", { name: "Skapa ny gruppchatt" });
    expect(document.activeElement).toBe(groupChat);
    fireEvent.keyDown(groupChat, { key: "Enter" });
    const dialog = await screen.findByRole("dialog", { name: "Skapa en ny gruppchatt" });

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(more));
  });

  it.each([false, true])(
    "opens a template-created assistant only when chosen (%s)",
    async (openEditor) => {
      api.GET.mockResolvedValue({
        data: { items: [{ id: "template", name: "Protokoll", description: null, wizard: {} }] },
        response: new Response("{}")
      });
      api.POST.mockReturnValue(created("a-new"));
      renderInApp(<CreateChatAppMenu />, {
        appContext: testAppContext({ settings: { using_templates: true } })
      });
      fireEvent.keyDown(screen.getByRole("button", { name: "Fler sätt att skapa" }), {
        key: "Enter"
      });
      fireEvent.click(screen.getByRole("menuitem", { name: "Börja med en mall..." }));
      const dialog = await screen.findByRole("dialog", { name: "Välj en mall" });
      fireEvent.click(await within(dialog).findByRole("button", { name: "Protokoll" }));
      const choice = within(dialog).getByRole("switch", {
        name: "Öppna assistentredigerare efter skapande",
        checked: false
      });
      if (openEditor) fireEvent.click(choice);
      fireEvent.click(within(dialog).getByRole("button", { name: "Skapa assistent" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(api.POST).toHaveBeenCalledTimes(1);
      expect(api.POST.mock.calls[0]?.[1]).toMatchObject({
        body: { name: "Protokoll", from_template: { id: "template" } }
      });
      if (openEditor)
        expect(router.push).toHaveBeenCalledWith("/spaces/space-1/assistants/a-new/edit");
      else expect(router.push).not.toHaveBeenCalled();
    }
  );
});

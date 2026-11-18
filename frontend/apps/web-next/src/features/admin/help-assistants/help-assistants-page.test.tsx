// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { openMenuOnRelease } from "@/test/menus";
import { renderInApp } from "@/test/render";

const backend = vi.hoisted(() => ({ templates: [] as unknown[], post: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    POST: backend.post,
    GET: (path: string) =>
      Promise.resolve({
        data: {
          items: path === "/api/v1/admin/help-assistants/templates/" ? backend.templates : []
        },
        response: new Response("{}")
      })
  }
}));

import { HelpAssistantsPage } from "./help-assistants-page";

const promptGuide = {
  kind: "prompt_guide",
  name: "Prompt Guide",
  description: "Hjälper användare att skriva bättre frågor."
};

afterEach(() => {
  cleanup();
  backend.post.mockReset();
  backend.templates = [];
});

describe("HelpAssistantsPage", () => {
  it("opens the add menu on release and installs a picked template once", async () => {
    backend.templates = [promptGuide];
    backend.post.mockReturnValue(new Promise(() => {}));
    renderInApp(<HelpAssistantsPage />);
    const add = await screen.findByRole("button", { name: "Lägg till hjälpassistent" });

    const menu = await openMenuOnRelease(add);
    expect(menu.getAttribute("aria-label")).toBe("Lägg till hjälpassistent");
    const item = within(menu).getByRole("menuitem", { name: /Prompt Guide/ });
    expect(item.textContent).toContain(promptGuide.description);

    fireEvent.click(item);
    await waitFor(() => expect(add.getAttribute("aria-busy")).toBe("true"));
    // Busy, the button stays enabled so focus can return to it; a second pick is ignored.
    expect(add.hasAttribute("disabled")).toBe(false);
    fireEvent.click(add);
    fireEvent.click(await within(menu).findByRole("menuitem", { name: /Prompt Guide/ }));
    expect(backend.post).toHaveBeenCalledTimes(1);
    expect(backend.post.mock.calls[0]?.[1]).toMatchObject({
      params: { path: { kind: "prompt_guide" } }
    });
  });

  it("says in text why nothing can be added", async () => {
    renderInApp(<HelpAssistantsPage />);
    const add = await screen.findByRole("button", { name: "Lägg till hjälpassistent" });

    expect(add.hasAttribute("disabled") || add.getAttribute("aria-disabled") === "true").toBe(true);
    const reason = document.getElementById(add.getAttribute("aria-describedby") ?? "");
    expect(reason?.textContent).toBe("Alla tillgängliga mallar är redan tillagda.");
  });
});

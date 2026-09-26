// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    POST: post,
    GET: () =>
      Promise.resolve({
        data: {
          security_enabled: true,
          security_classifications: [
            { id: "c1", name: "Klass 1 · Öppen", description: null, security_level: 1 },
            { id: "c2", name: "Klass 2 · Intern", description: null, security_level: 2 }
          ]
        },
        response: new Response("{}")
      })
  }
}));

import { SecurityClassificationsPage } from "./classifications-page";

afterEach(() => {
  cleanup();
  post.mockReset();
});

describe("SecurityClassificationsPage", () => {
  it("names each classification's menu after the classification", async () => {
    renderInApp(<SecurityClassificationsPage />);

    expect(
      await screen.findByRole("button", { name: "Fler åtgärder för Klass 2 · Intern" })
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Klass 1 · Öppen" })).toBeTruthy();
  });

  it("keeps focus on a busy Inaktivera and switches off once", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(<SecurityClassificationsPage />);
    fireEvent.click(await screen.findByRole("switch", { name: /Aktiverad/ }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Inaktivera säkerhetsklassificeringar"
    });
    const disable = within(dialog).getByRole("button", { name: "Inaktivera" });
    disable.focus();

    fireEvent.click(disable);

    await waitFor(() => expect(disable.getAttribute("aria-busy")).toBe("true"));
    expect(disable.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(disable);
    fireEvent.click(disable);
    expect(post).toHaveBeenCalledTimes(1);
  });
});

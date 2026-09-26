// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () =>
      Promise.resolve({
        data: {
          items: [
            {
              id: "entry-1",
              name: "Sammanfatta ett beslut",
              description: "Kort sammanfattning för tjänsteskrivelser",
              prompt: "Sammanfatta beslutet i tre meningar."
            }
          ]
        },
        response: new Response("{}")
      })
  }
}));

import { PromptLibraryPage } from "./prompt-library-page";

afterEach(cleanup);

describe("PromptLibraryPage", () => {
  it("names the prompt table by the page title", async () => {
    const { container } = renderInApp(<PromptLibraryPage />);

    const table = await screen.findByRole("table", { name: "Promptbibliotek" });
    expect(within(table).getByText("Sammanfatta ett beslut")).toBeTruthy();
    // Each row's menu says whose it is.
    expect(
      within(table).getByRole("button", { name: "Fler åtgärder för Sammanfatta ett beslut" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});

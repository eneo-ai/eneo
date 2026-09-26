// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));

import { McpServerDialog } from "./mcp-dialog";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

function renderDialog() {
  api.GET.mockImplementation(() => ok({ security_enabled: false, security_classifications: [] }));
  renderInApp(<McpServerDialog open onOpenChange={() => {}} />);
  return screen.getByRole("dialog", { name: "Lägg till MCP-server" });
}

/** Chooses bearer authentication from the keyboard. */
function chooseBearer(dialog: HTMLElement) {
  const authentication = within(dialog).getByRole("combobox", { name: "Autentisering" });
  fireEvent.keyDown(authentication, { key: "ArrowDown" });
  fireEvent.keyDown(screen.getByRole("option", { name: "Bearer-token" }), { key: "Enter" });
}

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement;
const add = (dialog: HTMLElement) =>
  within(dialog).getByRole("button", { name: "Lägg till MCP-server" }) as HTMLButtonElement;

describe("McpServerDialog", () => {
  it("asks for the bearer token twice once bearer authentication is chosen", async () => {
    const dialog = renderDialog();
    expect(within(dialog).queryByLabelText(/^Bearer-token/)).toBeNull();

    chooseBearer(dialog);

    for (const input of [field(/^Bearer-token/), field(/^Bekräfta Bearer-token/)]) {
      expect(input.getAttribute("type")).toBe("password");
      // A server's token, not the admin's own password.
      expect(input.getAttribute("autocomplete")).toBe("off");
      expect(input.getAttribute("aria-required")).toBe("true");
    }
    await expectNoAxeViolations(document.body);
  });

  it("says the tokens differ at the confirmation once it is left", async () => {
    const dialog = renderDialog();
    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.change(within(dialog).getByLabelText("URL"), {
      target: { value: "https://diariet.example.se/mcp" }
    });
    chooseBearer(dialog);
    fireEvent.change(field(/^Bearer-token/), { target: { value: "token-1234" } });
    field(/^Bekräfta Bearer-token/).focus();
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-12" } });

    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-invalid")).toBeNull();
    expect(add(dialog).disabled).toBe(true);

    fireEvent.blur(field(/^Bekräfta Bearer-token/));

    // The dialog's own copy; Astryx's live region repeats it for a while.
    const error = within(dialog).getByText("Värdena matchar inte");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-invalid")).toBe("true");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(document.body);
  });

  it("creates the server with the token once both entries match", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    const dialog = renderDialog();
    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.change(within(dialog).getByLabelText("URL"), {
      target: { value: "https://diariet.example.se/mcp" }
    });
    chooseBearer(dialog);
    fireEvent.change(field(/^Bearer-token/), { target: { value: "token-1234" } });
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-1234" } });

    expect(add(dialog).disabled).toBe(false);
    fireEvent.click(add(dialog));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/", {
        body: expect.objectContaining({
          name: "Diariet",
          http_auth_type: "bearer",
          http_auth_config_schema: { token: "token-1234" }
        })
      })
    );
  });
});

// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

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
  it.each([true, false])(
    "keeps create credentials outside mutation state while pending and after success=%s",
    async (succeeds) => {
      let finish!: (response: unknown) => void;
      api.GET.mockImplementation(() =>
        ok({ security_enabled: false, security_classifications: [] })
      );
      api.POST.mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        })
      );
      const { queryClient } = renderInApp(<McpServerDialog open onOpenChange={() => {}} />);
      const dialog = screen.getByRole("dialog");
      fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Diariet" } });
      fireEvent.change(screen.getByLabelText("URL"), {
        target: { value: "https://remote.example/mcp" }
      });
      chooseBearer(dialog);
      fireEvent.change(field(/^Bearer-token/), { target: { value: "synthetic-private-token" } });
      fireEvent.change(field(/^Bekräfta Bearer-token/), {
        target: { value: "synthetic-private-token" }
      });
      fireEvent.click(add(dialog));
      await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
      const cached = () =>
        JSON.stringify(
          queryClient
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state)
        );
      expect(cached()).not.toContain("synthetic-private-token");
      await act(async () =>
        finish(
          succeeds
            ? {
                data: { server: { id: "created" }, connection: { tools_discovered: 0 } },
                response: new Response()
              }
            : {
                error: { message: "fixture refusal" },
                response: new Response("{}", { status: 400 })
              }
        )
      );
      await waitFor(() => expect(queryClient.isMutating()).toBe(0));
      expect(cached()).not.toContain("synthetic-private-token");
    }
  );
  it("opens catalog safety and focuses its invalid limit without submitting", () => {
    const dialog = renderDialog();
    fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "https://remote.example/mcp" }
    });
    const catalog = screen.getByLabelText("Maximal katalogstorlek (MiB)");
    fireEvent.change(catalog, { target: { value: "65" } });
    fireEvent.click(add(dialog));
    expect(document.activeElement).toBe(catalog);
    expect(catalog.closest("details")?.open).toBe(true);
    expect(catalog.getAttribute("aria-invalid")).toBe("true");
    expect(api.POST).not.toHaveBeenCalled();
  });
  it("creates API-header authentication with identity forwarding and catalog limits", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    const dialog = renderDialog();
    fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "https://remote.example/mcp" }
    });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Autentisering" }), {
      key: "ArrowDown"
    });
    fireEvent.keyDown(screen.getByRole("option", { name: "API-nyckel i header" }), {
      key: "Enter"
    });
    fireEvent.change(screen.getByLabelText("Headernamn"), { target: { value: "X-Api-Key" } });
    fireEvent.change(field(/^API-nyckel/), { target: { value: " synthetic-key " } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: " synthetic-key " } });
    fireEvent.click(screen.getByLabelText("Vidarebefordra användaridentitet"));
    fireEvent.change(screen.getByLabelText("Maximalt antal verktyg"), {
      target: { value: "1024" }
    });
    fireEvent.change(screen.getByLabelText("Maximal katalogstorlek (MiB)"), {
      target: { value: "32" }
    });
    fireEvent.click(add(dialog));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/", {
        body: expect.objectContaining({
          http_auth_type: "api_key_header",
          http_auth_config_schema: { header_name: "X-Api-Key", token: " synthetic-key " },
          forward_identity: true,
          tool_catalog_max_count: 1024,
          tool_catalog_max_bytes: 32 * 1048576,
          tool_definition_max_bytes: 64 * 1024
        })
      })
    );
  });

  it("refuses credentials over remote plain HTTP before submitting", () => {
    const dialog = renderDialog();
    fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "http://remote.example/mcp" }
    });
    chooseBearer(dialog);
    fireEvent.change(field(/^Bearer-token/), { target: { value: "synthetic-token" } });
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "synthetic-token" } });
    fireEvent.click(add(dialog));
    expect(api.POST).not.toHaveBeenCalled();
    expect(screen.getByLabelText("URL").getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText("URL"));
  });

  it("keeps a pending add pending when closed and reopened, so it is not sent twice", async () => {
    api.GET.mockImplementation(() => ok({ security_enabled: false, security_classifications: [] }));
    api.POST.mockImplementation(() => new Promise(() => {}));
    const fill = () => {
      fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Diariet" } });
      fireEvent.change(screen.getByLabelText("URL"), {
        target: { value: "https://diariet.example.se/mcp" }
      });
    };
    const { rerender } = renderInApp(<McpServerDialog open onOpenChange={() => {}} />);
    fill();
    fireEvent.click(add(screen.getByRole("dialog")));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));

    rerender(<McpServerDialog open={false} onOpenChange={() => {}} />);
    rerender(<McpServerDialog open onOpenChange={() => {}} />);
    const dialog = await screen.findByRole("dialog");
    fill();
    const busy = within(dialog).getByRole("button", { name: "Ansluter…" });
    fireEvent.click(busy);

    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(api.POST).toHaveBeenCalledTimes(1);
  });

  it("starts empty again when reopened after a cancelled add", async () => {
    api.GET.mockImplementation(() => ok({ security_enabled: false, security_classifications: [] }));
    const { rerender } = renderInApp(<McpServerDialog open onOpenChange={() => {}} />);
    fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.click(add(screen.getByRole("dialog")));

    rerender(<McpServerDialog open={false} onOpenChange={() => {}} />);
    rerender(<McpServerDialog open onOpenChange={() => {}} />);

    const name = within(await screen.findByRole("dialog")).getByLabelText("Namn");
    expect((name as HTMLInputElement).value).toBe("");
    expect(name.getAttribute("aria-invalid")).toBeNull();
  });

  it("shows each problem at its field when added, and moves focus to the first", async () => {
    const dialog = renderDialog();
    // Never disabled: a disabled button says nothing about what is missing.
    expect(add(dialog).disabled).toBe(false);

    fireEvent.click(add(dialog));

    const name = within(dialog).getByLabelText("Namn");
    const url = within(dialog).getByLabelText("URL");
    for (const input of [name, url]) {
      expect(input.getAttribute("aria-invalid")).toBe("true");
      const problem = document.getElementById(input.getAttribute("aria-describedby")!);
      expect(problem?.textContent).toBe("Detta fält är obligatoriskt");
    }
    expect(document.activeElement).toBe(name);
    await expectNoAxeViolations(document.body);

    // With bearer authentication, the token is next.
    fireEvent.change(name, { target: { value: "Diariet" } });
    fireEvent.change(url, { target: { value: "https://diariet.example.se/mcp" } });
    chooseBearer(dialog);
    fireEvent.click(add(dialog));
    expect(name.getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(field(/^Bearer-token/));

    fireEvent.change(field(/^Bearer-token/), { target: { value: "token-1234" } });
    fireEvent.click(add(dialog));
    expect(document.activeElement).toBe(field(/^Bekräfta Bearer-token/));
    expect(api.POST).not.toHaveBeenCalled();
  });

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

    fireEvent.blur(field(/^Bekräfta Bearer-token/));

    // The dialog's own copy; Astryx's live region repeats it for a while.
    const error = within(dialog).getByText("Värdena matchar inte");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-invalid")).toBe("true");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(document.body);
  });

  it("creates the server with the token once both entries match without caching its secret", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    api.GET.mockImplementation(() => ok({ security_enabled: false, security_classifications: [] }));
    const { queryClient } = renderInApp(<McpServerDialog open onOpenChange={() => {}} />);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Diariet" } });
    fireEvent.change(within(dialog).getByLabelText("URL"), {
      target: { value: "https://diariet.example.se/mcp" }
    });
    chooseBearer(dialog);
    fireEvent.change(field(/^Bearer-token/), { target: { value: "token-1234" } });
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-1234" } });

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
    expect(
      JSON.stringify(
        queryClient
          .getMutationCache()
          .getAll()
          .map((mutation) => mutation.state)
      )
    ).not.toContain("token-1234");
  });
});

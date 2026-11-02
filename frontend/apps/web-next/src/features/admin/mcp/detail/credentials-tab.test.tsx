// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import type { McpServer } from "../mcp";
import { CredentialsTab } from "./credentials-tab";

const server = {
  id: "diariet",
  name: "Diariet",
  http_url: "https://diariet.example.se/mcp",
  http_auth_type: "bearer",
  has_credentials: true,
  credential_preview: "…9f2c"
} as McpServer;

// The row is a group named "Bearer-token" too.
const field = (name: RegExp) =>
  screen.getByLabelText(name, { selector: "input" }) as HTMLInputElement;
const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

afterEach(() => vi.clearAllMocks());

describe("CredentialsTab", () => {
  it.each([true, false])(
    "keeps a replacement secret outside mutation state while pending and after success=%s",
    async (succeeds) => {
      let finish!: (response: unknown) => void;
      api.POST.mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        })
      );
      const { queryClient } = renderInApp(<CredentialsTab server={server} />);
      fireEvent.click(button("Byt token"));
      fireEvent.change(field(/^Bearer-token/), { target: { value: "synthetic-private-token" } });
      fireEvent.change(field(/^Bekräfta Bearer-token/), {
        target: { value: "synthetic-private-token" }
      });
      fireEvent.click(button("Spara"));
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
            ? { data: server, response: new Response() }
            : {
                error: { message: "fixture refusal" },
                response: new Response("{}", { status: 400 })
              }
        )
      );
      await waitFor(() => expect(queryClient.isMutating()).toBe(0));
      expect(cached()).not.toContain("synthetic-private-token");
      if (!succeeds) expect(field(/^Bearer-token/).value).toBe("synthetic-private-token");
    }
  );
  it("clears a discarded failed replacement from the page's save guard", async () => {
    api.POST.mockResolvedValue({
      error: { message: "fixture refusal" },
      response: new Response("{}", { status: 400 })
    });
    renderInApp(
      <SaveStatusProvider>
        <SaveStatusIndicator />
        <CredentialsTab server={server} />
      </SaveStatusProvider>
    );
    fireEvent.click(button("Byt token"));
    fireEvent.change(field(/^Bearer-token/), { target: { value: "synthetic-token" } });
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "synthetic-token" } });
    fireEvent.click(button("Spara"));
    await screen.findByRole("link", { name: "Kunde inte spara ändringarna" });
    fireEvent.click(button("Avbryt"));
    expect(screen.queryByRole("link", { name: "Kunde inte spara ändringarna" })).toBeNull();
    const leaving = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leaving);
    expect(leaving.defaultPrevented).toBe(false);
  });

  it("collects a new API header and key before changing authentication", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(
      <CredentialsTab server={{ ...server, http_auth_type: "none", has_credentials: false }} />
    );
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Autentisering" }), {
      key: "ArrowDown"
    });
    fireEvent.keyDown(screen.getByRole("option", { name: "API-nyckel i header" }), {
      key: "Enter"
    });
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.click(button("Spara"));
    expect(document.activeElement).toBe(screen.getByLabelText("Headernamn"));
    fireEvent.change(screen.getByLabelText("Headernamn"), { target: { value: "X-Api-Key" } });
    fireEvent.change(field(/^API-nyckel/), { target: { value: "synthetic-key" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "synthetic-key" } });
    fireEvent.click(button("Spara"));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
        params: { path: { id: server.id } },
        body: {
          http_auth_type: "api_key_header",
          http_auth_config_schema: { header_name: "X-Api-Key", token: "synthetic-key" }
        }
      })
    );
  });

  it("keeps a failed replacement available for retry and blocks remote HTTP", async () => {
    api.POST.mockResolvedValue({
      error: { message: "fixture refusal" },
      response: new Response("{}", { status: 400 })
    });
    const { rerender } = renderInApp(<CredentialsTab server={server} />);
    fireEvent.click(button("Byt token"));
    fireEvent.change(field(/^Bearer-token/), { target: { value: "synthetic-token" } });
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "synthetic-token" } });
    fireEvent.click(button("Spara"));
    await waitFor(() => expect(button("Spara").getAttribute("aria-busy")).toBeNull());
    expect(field(/^Bearer-token/).value).toBe("synthetic-token");
    rerender(<CredentialsTab server={{ ...server, http_url: "http://remote.example/mcp" }} />);
    fireEvent.click(button("Spara"));
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Inloggningsuppgifter.*skickas bara över https/)).toBeTruthy();
  });

  it.each(["internal", "bundled"])("does not expose credential editing for %s auth", (auth) => {
    renderInApp(<CredentialsTab server={{ ...server, http_auth_type: auth }} />);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Byt token" })).toBeNull();
  });

  it("replaces an API-header token without converting its type or losing its saved header", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(<CredentialsTab server={{ ...server, http_auth_type: "api_key_header" }} />);
    expect(screen.getByRole("combobox", { name: "Autentisering" }).textContent).toBe(
      "API-nyckel i header"
    );
    fireEvent.click(button("Byt token"));
    fireEvent.change(field(/^API-nyckel/), { target: { value: "synthetic-key" } });
    fireEvent.change(field(/^Bekräfta API-nyckel/), { target: { value: "synthetic-key" } });
    fireEvent.click(button("Spara"));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
        params: { path: { id: server.id } },
        body: {
          http_auth_type: "api_key_header",
          http_auth_config_schema: { token: "synthetic-key" }
        }
      })
    );
  });

  it("moves focus into the new token's field, and back when the change is dropped", async () => {
    const { container } = renderInApp(<CredentialsTab server={server} />);

    button("Byt token").focus();
    fireEvent.click(button("Byt token"));

    expect(document.activeElement).toBe(field(/^Bearer-token/));
    for (const input of [field(/^Bearer-token/), field(/^Bekräfta Bearer-token/)]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("off");
    }
    await expectNoAxeViolations(container);

    fireEvent.click(button("Avbryt"));

    expect(screen.queryByLabelText(/^Bearer-token/, { selector: "input" })).toBeNull();
    expect(document.activeElement).toBe(button("Byt token"));
  });

  it("shows the token's problems at its fields on save, and moves focus to the first", async () => {
    const { container } = renderInApp(<CredentialsTab server={server} />);
    fireEvent.click(button("Byt token"));
    // Never disabled: a disabled button says nothing about what is missing.
    expect(button("Spara").disabled).toBe(false);

    fireEvent.click(button("Spara"));
    expect(field(/^Bearer-token/).getAttribute("aria-invalid")).toBe("true");
    expect(within(container).getByText("Detta fält är obligatoriskt")).toBeTruthy();
    expect(document.activeElement).toBe(field(/^Bearer-token/));
    await expectNoAxeViolations(container);

    fireEvent.change(field(/^Bearer-token/), { target: { value: "ny-token-1234" } });
    fireEvent.click(button("Spara"));
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field(/^Bekräfta Bearer-token/));
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("says the tokens differ at the confirmation, and saves once they match", async () => {
    api.POST.mockImplementation(() => Promise.resolve({ data: server, response: new Response() }));
    const { container, queryClient } = renderInApp(<CredentialsTab server={server} />);
    fireEvent.click(button("Byt token"));
    fireEvent.change(field(/^Bearer-token/), { target: { value: "token-1234" } });
    field(/^Bekräfta Bearer-token/).focus();
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-12" } });
    fireEvent.blur(field(/^Bekräfta Bearer-token/));

    const error = within(container).getByText("Värdena matchar inte");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-invalid")).toBe("true");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(container);

    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-1234" } });
    fireEvent.click(button("Spara"));

    await waitFor(() =>
      expect(screen.queryByLabelText(/^Bearer-token/, { selector: "input" })).toBeNull()
    );
    expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
      params: { path: { id: "diariet" } },
      body: { http_auth_type: "bearer", http_auth_config_schema: { token: "token-1234" } }
    });
    expect(
      JSON.stringify(
        queryClient
          .getMutationCache()
          .getAll()
          .map((mutation) => mutation.state)
      )
    ).not.toContain("token-1234");
    // Saved: back on the button that opened the fields.
    expect(document.activeElement).toBe(button("Byt token"));
  });
});

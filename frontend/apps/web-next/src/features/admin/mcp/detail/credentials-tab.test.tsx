// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

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

  it("says the tokens differ at the confirmation, and saves once they match", async () => {
    api.POST.mockImplementation(() => Promise.resolve({ data: server, response: new Response() }));
    const { container } = renderInApp(<CredentialsTab server={server} />);
    fireEvent.click(button("Byt token"));
    fireEvent.change(field(/^Bearer-token/), { target: { value: "token-1234" } });
    field(/^Bekräfta Bearer-token/).focus();
    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-12" } });
    fireEvent.blur(field(/^Bekräfta Bearer-token/));

    const error = within(container).getByText("Värdena matchar inte");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-invalid")).toBe("true");
    expect(field(/^Bekräfta Bearer-token/).getAttribute("aria-describedby")).toContain(error.id);
    expect(button("Spara").disabled).toBe(true);
    await expectNoAxeViolations(container);

    fireEvent.change(field(/^Bekräfta Bearer-token/), { target: { value: "token-1234" } });
    expect(button("Spara").disabled).toBe(false);
    fireEvent.click(button("Spara"));

    await waitFor(() =>
      expect(screen.queryByLabelText(/^Bearer-token/, { selector: "input" })).toBeNull()
    );
    expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
      params: { path: { id: "diariet" } },
      body: { http_auth_type: "bearer", http_auth_config_schema: { token: "token-1234" } }
    });
    // Saved: back on the button that opened the fields.
    expect(document.activeElement).toBe(button("Byt token"));
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

type Tool = {
  id: string;
  name: string;
  requires_approval: boolean;
  is_enabled_by_default: boolean;
};

const server = (id: string, name: string, tools: Tool[] = []) => ({
  id,
  name,
  description: null,
  http_url: `https://${id}.example.se/mcp`,
  icon_url: null,
  tags: [],
  tools,
  tools_count: tools.length,
  is_org_enabled: true,
  security_classification: null
});

const servers = vi.hoisted(() => ({ items: [] as unknown[] }));

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const remove = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    DELETE: remove,
    POST: post,
    GET: (path: string) =>
      Promise.resolve({
        data:
          path === "/api/v1/mcp-servers/settings/"
            ? { items: servers.items }
            : { security_enabled: false, security_classifications: [] },
        response: new Response("{}")
      })
  }
}));

import { McpServersPage } from "./mcp-page";

beforeEach(() => {
  servers.items = [server("diariet", "Diariet"), server("kartan", "Kartan")];
});

afterEach(() => {
  cleanup();
  remove.mockReset();
  post.mockReset();
});

it("keeps the function-server filter reachable when the tenant has only function sources", async () => {
  servers.items = [
    { ...server("images", "Images"), purpose: "image_generation", is_enabled: false }
  ];
  renderInApp(<McpServersPage />);
  fireEvent.click(await screen.findByRole("switch", { name: "Visa funktionsservrar" }));
  expect(await screen.findByRole("link", { name: "Images" })).toBeTruthy();
});

it("uses capability state and activate/deactivate endpoints for function sources", async () => {
  const provider = {
    ...server("images", "Images"),
    purpose: "image_generation",
    is_enabled: false,
    is_org_enabled: true
  };
  servers.items.push(provider);
  post.mockImplementation(() => {
    provider.is_enabled = !provider.is_enabled;
    return Promise.resolve({ data: {}, response: new Response("{}") });
  });
  renderInApp(<McpServersPage />);
  fireEvent.click(await screen.findByRole("switch", { name: "Visa funktionsservrar" }));
  const toggle = await screen.findByRole("switch", { name: "Aktivera Images" });
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/activate/", {
      params: { path: { id: "images" } }
    })
  );
  await waitFor(() => expect(toggle.getAttribute("aria-busy")).not.toBe("true"));
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/deactivate/", {
      params: { path: { id: "images" } }
    })
  );
  expect(remove).not.toHaveBeenCalled();
});

it("shows a refused activation beside its server and restores the saved state", async () => {
  servers.items.push({
    ...server("images", "Images"),
    purpose: "image_generation",
    is_enabled: false,
    is_org_enabled: false
  });
  post.mockResolvedValue({
    error: { detail: "No approved tools" },
    response: new Response("{}", { status: 400 })
  });
  renderInApp(<McpServersPage />);
  fireEvent.click(await screen.findByRole("switch", { name: "Visa funktionsservrar" }));
  const toggle = await screen.findByRole("switch", { name: "Aktivera Images" });
  fireEvent.click(toggle);
  expect((await screen.findByRole("alert")).textContent).toContain("No approved tools");
  expect(toggle.getAttribute("aria-checked")).toBe("false");
});

it("finds providers by description, classification and audience, and filters by capability state", async () => {
  servers.items.push({
    ...server("images", "Images"),
    description: "Illustrationer",
    purpose: "image_generation",
    is_enabled: false,
    is_org_enabled: true,
    http_auth_type: "api_key_header",
    audience: "groups",
    user_groups: [{ id: "editors", name: "Redaktionen" }],
    security_classification: { id: "internal", name: "Intern information" },
    forward_identity: true
  });
  renderInApp(<McpServersPage />);
  fireEvent.click(await screen.findByRole("switch", { name: "Visa funktionsservrar" }));
  expect(await screen.findByText("API-nyckel i header")).toBeTruthy();
  expect(screen.getByText("Redaktionen")).toBeTruthy();
  expect(screen.getByText("Användaridentitet vidarebefordras till denna server.")).toBeTruthy();
  const search = screen.getByRole("textbox", { name: "Sök MCP-servrar" });
  for (const value of ["illustrationer", "intern information", "redaktionen"]) {
    fireEvent.change(search, { target: { value } });
    expect(screen.getByRole("link", { name: "Images" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Diariet" })).toBeNull();
  }
  fireEvent.change(search, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Inaktiva" }));
  expect(screen.getByRole("link", { name: "Images" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Diariet" })).toBeNull();
});

const pendingTile = async () => {
  const label = await screen.findByText("Väntar på granskning");
  return label.closest("div[class], button")!;
};

describe("McpServersPage", () => {
  it("keeps the pending-review tile neutral at zero", async () => {
    renderInApp(<McpServersPage />);
    const tile = await pendingTile();
    expect(tile.textContent).toContain("0");
    expect(tile.className).not.toContain("warning");
    expect(tile.tagName).toBe("DIV");
  });

  it("colours the pending-review tile as a warning once a tool waits", async () => {
    servers.items = [
      server("diariet", "Diariet", [
        { id: "t1", name: "search", requires_approval: true, is_enabled_by_default: false }
      ])
    ];
    renderInApp(<McpServersPage />);
    const tile = await pendingTile();
    expect(tile.textContent).toContain("1");
    expect(tile.className).toContain("bg-warning/10");
    expect(tile.tagName).toBe("BUTTON");
  });

  it("names each server's menu after the server", async () => {
    renderInApp(<McpServersPage />);

    expect(await screen.findByRole("button", { name: "Fler åtgärder för Diariet" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Kartan" })).toBeTruthy();
  });

  it("keeps focus on a switch while it saves, and saves each press once", async () => {
    remove.mockReturnValue(new Promise(() => {}));
    renderInApp(<McpServersPage />);
    const toggle = await screen.findByRole("switch", { name: "Aktivera Diariet" });
    toggle.focus();

    fireEvent.click(toggle);

    await waitFor(() => expect(toggle.getAttribute("aria-busy")).toBe("true"));
    // Shown at once, and never disabled, so it keeps focus.
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(toggle.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(toggle);
    expect(remove).toHaveBeenCalledTimes(1);

    // Pressed again: shown at once, and sent once the first save is done.
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    expect(remove).toHaveBeenCalledTimes(1);
  });
});

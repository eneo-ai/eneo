// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { mcpToolsKey, type McpServerTool } from "../mcp";
import { ToolsTab } from "./tools-tab";
const server = { id: "server", http_auth_type: "none", purpose: "general" } as const;
function tool(overrides: Partial<McpServerTool> = {}): McpServerTool {
  return {
    id: "a",
    mcp_server_id: "server",
    name: "read_records",
    title: "Records",
    description: "Reads records",
    input_schema: {},
    is_enabled_by_default: true,
    ...overrides
  };
}
const ok = (data: unknown) => ({ data, response: new Response("{}") });
const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("reports a partial bulk-disable failure and reloads the successful changes", async () => {
  let firstEnabled = true;
  api.GET.mockImplementation(() =>
    Promise.resolve({
      data: {
        items: [
          {
            id: "a",
            name: "Alpha",
            is_enabled_by_default: firstEnabled,
            requires_approval: false,
            input_schema: {}
          },
          {
            id: "b",
            name: "Beta",
            is_enabled_by_default: true,
            requires_approval: false,
            input_schema: {}
          }
        ]
      },
      response: new Response("{}")
    })
  );
  api.PUT.mockImplementation(
    (_path: string, { params }: { params: { path: { tool_id: string } } }) => {
      if (params.path.tool_id === "b")
        return Promise.resolve({
          error: { message: "Update refused" },
          response: new Response("{}", { status: 403 })
        });
      firstEnabled = false;
      return Promise.resolve({ data: {}, response: new Response("{}") });
    }
  );
  renderInApp(<ToolsTab server={server} />);
  fireEvent.click(await screen.findByRole("button", { name: "Alla av" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(
      screen.getByRole("switch", { name: "Aktivera Alpha" }).getAttribute("aria-checked")
    ).toBe("false")
  );
  expect(screen.getByRole("switch", { name: "Aktivera Beta" }).getAttribute("aria-checked")).toBe(
    "true"
  );
  expect(api.PUT).toHaveBeenCalledTimes(2);
});

it("marks schema-only changes as changed without an empty description diff", async () => {
  api.GET.mockResolvedValue(
    ok({
      items: [
        tool({
          requires_approval: true,
          pending_input_schema: { type: "object", required: ["query"] }
        })
      ]
    })
  );
  renderInApp(<ToolsTab server={server} />);
  expect(await screen.findByText("Ändrad")).toBeTruthy();
  expect(screen.queryByText("Ny beskrivning")).toBeNull();
});

it("shows the pending view address, size and all domain permissions, with retry on failure", async () => {
  let failed = true;
  api.GET.mockImplementation((path: string) =>
    Promise.resolve(
      path.endsWith("/view/")
        ? failed
          ? { error: { message: "Unavailable" }, response: new Response("{}", { status: 503 }) }
          : ok({
              uri: "ui://records/view.html",
              pending: true,
              size_bytes: 2048,
              connect_domains: ["https://data.example"],
              resource_domains: ["https://cdn.example"],
              frame_domains: ["https://frame.example"],
              permissions: []
            })
        : ok({
            items: [
              tool({
                requires_approval: true,
                pending_ui_resource_sha256: "new-hash",
                pending_meta: { ui: { resourceUri: "ui://records/view.html" } }
              })
            ]
          })
    )
  );
  renderInApp(<ToolsTab server={server} />);
  expect(await screen.findByText("ui://records/view.html")).toBeTruthy();
  const retry = await screen.findByRole("button", { name: /Försök igen/ });
  expect(screen.queryByText("Kan inte nå nätverket")).toBeNull();
  failed = false;
  fireEvent.click(retry);
  expect(await screen.findByText("https://data.example")).toBeTruthy();
  expect(screen.getByText("https://cdn.example")).toBeTruthy();
  expect(screen.getByText("https://frame.example")).toBeTruthy();
  expect(screen.getByText(/Storlek: 2/)).toBeTruthy();
  expect(document.querySelector("iframe")).toBeNull();
});

it("saves and clears an override while retaining the protocol name", async () => {
  let current = tool();
  api.GET.mockImplementation(() => Promise.resolve(ok({ items: [current] })));
  api.PUT.mockImplementation(
    (_path: string, { body }: { body: { display_name: string | null } }) => {
      current = { ...current, display_name: body.display_name };
      return Promise.resolve(ok(current));
    }
  );
  renderInApp(<ToolsTab server={server} />);
  fireEvent.click(await screen.findByRole("button", { name: /Byt visningsnamn/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "Visningsnamn" }), {
    target: { value: "  Our records  " }
  });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  expect(await screen.findByText("Our records")).toBeTruthy();
  expect(screen.getByText("read_records")).toBeTruthy();
  expect(api.PUT).toHaveBeenLastCalledWith(
    "/api/v1/mcp-servers/{id}/tools/{tool_id}/display-name/",
    { params: { path: { id: "server", tool_id: "a" } }, body: { display_name: "Our records" } }
  );
  fireEvent.click(screen.getByRole("button", { name: /Byt visningsnamn/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "Visningsnamn" }), {
    target: { value: "   " }
  });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  expect(await screen.findByText("Records")).toBeTruthy();
  expect(api.PUT).toHaveBeenLastCalledWith(
    expect.anything(),
    expect.objectContaining({ body: { display_name: null } })
  );
});

it("keeps an unsuccessful rename editable and returns focus on cancel", async () => {
  api.GET.mockResolvedValue(ok({ items: [tool()] }));
  api.PUT.mockResolvedValue({
    error: { message: "Forbidden" },
    response: new Response("{}", { status: 403 })
  });
  renderInApp(<ToolsTab server={server} />);
  fireEvent.click(await screen.findByRole("button", { name: /Byt visningsnamn/ }));
  const input = screen.getByRole("textbox", { name: "Visningsnamn" });
  fireEvent.change(input, { target: { value: "Keep my draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  await screen.findByRole("alert");
  expect((input as HTMLInputElement).value).toBe("Keep my draft");
  fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /Byt visningsnamn/ }))
  );
});

it("shows internal provider tools as localized read-only information", async () => {
  api.GET.mockResolvedValue(ok({ items: [tool({ name: "generate_image", title: "Raw title" })] }));
  renderInApp(
    <ToolsTab server={{ ...server, http_auth_type: "internal", purpose: "image_generation" }} />
  );
  expect(await screen.findByText("Generera bild")).toBeTruthy();
  expect(screen.getByText("Genererar en bild utifrån en textbeskrivning.")).toBeTruthy();
  expect(screen.queryByRole("switch")).toBeNull();
  expect(
    screen.queryByRole("button", { name: /Synkronisera|Byt visningsnamn|Alla på|Alla av/ })
  ).toBeNull();
});

it("does not treat an external provider's matching tool name as built-in", async () => {
  api.GET.mockResolvedValue(
    ok({ items: [tool({ name: "generate_image", title: "External image tool" })] })
  );
  renderInApp(<ToolsTab server={{ ...server, purpose: "image_generation" }} />);
  expect(await screen.findByText("External image tool")).toBeTruthy();
  expect(screen.queryByText("Generera bild")).toBeNull();
  expect(screen.getByRole("switch")).toBeTruthy();
});

it("reports a failed catalog load with retry rather than an empty catalog", async () => {
  api.GET.mockResolvedValue({
    error: { message: "Unavailable" },
    response: new Response("{}", { status: 503 })
  });
  renderInApp(<ToolsTab server={server} />);
  expect(await screen.findByRole("button", { name: /Försök igen/ })).toBeTruthy();
  expect(screen.queryByText("Inga verktyg hittades")).toBeNull();
});

it("loads new view facts when the pending content changes for the same tool", async () => {
  const queryClient = testQueryClient();
  const pending = tool({ requires_approval: true, pending_ui_resource_sha256: "first" });
  let domain = "https://first.example";
  api.GET.mockImplementation((path: string) =>
    Promise.resolve(
      ok(
        path.endsWith("/view/")
          ? {
              uri: "ui://records/view.html",
              pending: true,
              size_bytes: 12,
              connect_domains: [domain],
              resource_domains: [],
              frame_domains: [],
              permissions: []
            }
          : { items: [pending] }
      )
    )
  );
  renderInApp(<ToolsTab server={server} />, { queryClient });
  expect(await screen.findByText(domain)).toBeTruthy();
  domain = "https://replacement.example";
  act(() =>
    queryClient.setQueryData(mcpToolsKey(server.id), [
      { ...pending, pending_ui_resource_sha256: "second" }
    ])
  );
  expect(await screen.findByText(domain)).toBeTruthy();
  expect(screen.queryByText("https://first.example")).toBeNull();
});

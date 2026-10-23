// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { ToolsTab } from "./tools-tab";
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
  renderInApp(<ToolsTab serverId="server" />);
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

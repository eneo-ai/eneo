import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "$lib/test/mcpTestApi";

vi.mock("$app/navigation", () => ({ invalidate: vi.fn() }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => api.testEneo() }));

import MCPServerEnabledSwitch from "./MCPServerEnabledSwitch.svelte";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the stored state and the failure when the save fails", async () => {
  // Kills: the switch keeps showing the flipped state after a failed save
  api.stubFetch(api.refused);
  const onError = vi.fn();
  render(MCPServerEnabledSwitch, { mcpServer: api.mcpServer({ is_org_enabled: false }), onError });
  await fireEvent.click(screen.getByRole("switch"));
  await waitFor(() => expect(onError).toHaveBeenCalledWith("Refused"));
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
});

it("ignores a second activation during its own save and keeps focus", async () => {
  // Kills: the switch is disabled during its save (focus lost) or sends a second request
  const requests = api.stubFetch(api.never);
  render(MCPServerEnabledSwitch, { mcpServer: api.mcpServer() });
  const toggle = screen.getByRole("switch");
  await api.activateDuringSave(toggle, toggle, () => requests.mock.calls.length);
});

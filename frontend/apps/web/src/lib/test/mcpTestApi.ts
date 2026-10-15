import { createEneo, type components } from "@eneo/eneo-js";
import { fireEvent, waitFor } from "@testing-library/svelte";
import { expect, vi } from "vitest";
type Tool = components["schemas"]["MCPServerToolPublic"];
type Server = components["schemas"]["MCPServerSettingsPublic"];
const ids = { id: "s1", mcp_server_id: "s1", name: "Server one", http_url: "https://x/mcp" };
const unset = { description: null, documentation_url: null, icon_url: null, tags: null };
const flags = { has_credentials: false, is_available: true, is_org_enabled: true, tools_count: 0 };
const server = { ...ids, ...unset, ...flags, http_auth_type: "none" } satisfies Server;
const tool = { id: "t", mcp_server_id: "s1", name: "tool" };
const toolRest = { description: null, input_schema: null, is_enabled_by_default: false };
export const mcpServer = (overrides: Partial<Server> = {}): Server => ({ ...server, ...overrides });
export const mcpTool = (overrides: Partial<Tool>): Tool => ({ ...tool, ...toolRest, ...overrides });
export const testEneo = () => createEneo({ baseUrl: "https://eneo.example", token: "t" });
export const stubFetch = (answer: (...request: Parameters<typeof fetch>) => Promise<Response>) => {
  const stub = vi.fn(answer);
  vi.stubGlobal("fetch", stub);
  return stub;
};
export const refused = () =>
  Promise.resolve(Response.json({ message: "Refused", eneo_error_code: 9007 }, { status: 400 }));
export const never = () => new Promise<Response>(() => {});
// Activates `first`, then `second` while the first save is pending: focus must stay on `first`.
export async function activateDuringSave(
  first: HTMLElement,
  second: HTMLElement,
  sent: () => number
) {
  first.focus();
  await fireEvent.click(first);
  await waitFor(() => expect(first.getAttribute("aria-busy")).toBe("true"));
  await fireEvent.click(second);
  expect(sent()).toBe(1);
  expect(document.activeElement).toBe(first);
  expect(first.hasAttribute("disabled")).toBe(false);
}

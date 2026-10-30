import { EneoError } from "@eneo/eneo-js";
import { cleanup, render, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({}) }));
vi.mock("$lib/features/security-classifications/SecurityContext.js", () => ({
  getSecurityContext: () => ({ security_classifications: [] })
}));

import MCPServerDialog from "./MCPServerDialog.svelte";

afterEach(cleanup);

const long = `Server at http://${"a".repeat(400)}/mcp answered with a redirect (HTTP 307)`;
const duplicate = "An MCP server with this name already exists for this purpose.";

it.each([
  ["a long message", new EneoError(long, "SERVER", 400, 0), long],
  ["a code with a model translation", new EneoError(duplicate, "SERVER", 409, 9017), duplicate]
])("shows the backend's own sentence in a focused alert: %s", async (_case, error, text) => {
  // Kills: the alert does not take focus or cut the message; the shared 9017 "model" sentence is shown
  render(MCPServerDialog, {
    openController: writable(true),
    onSubmit: () => Promise.reject(error)
  });
  document.querySelector("form")?.dispatchEvent(new Event("submit", { cancelable: true }));
  await waitFor(() => expect(document.activeElement?.getAttribute("role")).toBe("alert"));
  expect(document.activeElement?.textContent?.trim()).toBe(text);
});

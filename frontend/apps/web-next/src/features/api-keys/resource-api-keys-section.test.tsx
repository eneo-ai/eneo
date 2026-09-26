// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { renderInApp, testAppContext } from "@/test/render";

const apiKey = {
  id: "key-1",
  key_prefix: "sk_ab",
  key_suffix: "wxyz",
  name: "Upphandlingsflödet",
  key_type: "sk_",
  permission: "read",
  scope_type: "space",
  scope_id: "space-1",
  state: "active",
  expires_at: null,
  created_at: "2026-09-01T08:00:00Z"
} as Schema<"ApiKeyV2">;

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) =>
      Promise.resolve({
        data: path === "/api/v1/api-keys" ? { items: [apiKey], next_cursor: null } : {},
        response: new Response("{}")
      })
  }
}));

import { ResourceApiKeysSection } from "./resource-api-keys-section";

afterEach(cleanup);

describe("ResourceApiKeysSection", () => {
  it("names the key table like its settings group", async () => {
    renderInApp(
      <ResourceApiKeysSection scopeType="space" scopeId="space-1" resourceName="Upphandling" />,
      { appContext: testAppContext({ permissions: ["api_keys"] }) }
    );

    expect(screen.getByRole("heading", { level: 2, name: "API-nycklar" })).toBeTruthy();
    const table = await screen.findByRole("table", { name: "API-nycklar" });
    expect(await within(table).findByText("Upphandlingsflödet")).toBeTruthy();
  });
});

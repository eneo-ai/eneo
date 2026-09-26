// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
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

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) =>
      Promise.resolve({
        data: path === "/api/v1/api-keys" ? { items: [apiKey], next_cursor: null } : {},
        response: new Response("{}")
      }),
    POST: post
  }
}));

import { ResourceApiKeysSection } from "./resource-api-keys-section";

afterEach(() => {
  cleanup();
  post.mockReset();
});

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

  it("shows the keys in the panel of the selected state tab", async () => {
    const { container } = renderInApp(
      <ResourceApiKeysSection scopeType="space" scopeId="space-1" resourceName="Upphandling" />,
      { appContext: testAppContext({ permissions: ["api_keys"] }) }
    );

    const panel = screen.getByRole("tabpanel", { name: "Aktiv" });
    expect(screen.getByRole("tab", { name: "Aktiv" }).getAttribute("aria-controls")).toBe(panel.id);
    expect(await within(panel).findByText("Upphandlingsflödet")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("names the resource in the create dialog's title", async () => {
    renderInApp(
      <ResourceApiKeysSection scopeType="space" scopeId="space-1" resourceName="Upphandling" />,
      { appContext: testAppContext({ permissions: ["api_keys"] }) }
    );

    fireEvent.click(screen.getByRole("button", { name: "Skapa" }));
    expect(
      await screen.findByRole("dialog", { name: "Skapa API-nyckel för Upphandling" })
    ).toBeTruthy();
  });

  it("shows a missing name at the field on submit, then creates the key", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(
      <ResourceApiKeysSection scopeType="space" scopeId="space-1" resourceName="Upphandling" />,
      { appContext: testAppContext({ permissions: ["api_keys"] }) }
    );
    fireEvent.click(screen.getByRole("button", { name: "Skapa" }));
    const dialog = await screen.findByRole("dialog", { name: "Skapa API-nyckel för Upphandling" });
    const create = within(dialog).getByRole("button", { name: "Skapa" }) as HTMLButtonElement;
    // Never disabled: a disabled button says nothing about what is missing.
    expect(create.disabled).toBe(false);

    fireEvent.click(create);
    const name = within(dialog).getByLabelText("Namn");
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(name.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Detta fält är obligatoriskt"
    );
    expect(document.activeElement).toBe(name);
    expect(post).not.toHaveBeenCalled();
    // Its pickers are named by their labels.
    expect(within(dialog).getByRole("combobox", { name: "Behörighetsnivå" })).toBeTruthy();
    await expectNoAxeViolations(dialog);

    fireEvent.change(name, { target: { value: "Upphandlingsflödet" } });
    fireEvent.click(create);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/api-keys", {
        body: expect.objectContaining({ name: "Upphandlingsflödet", scope_id: "space-1" })
      })
    );
  });
});

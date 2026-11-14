import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import "../../../../app.css";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

const api = vi.hoisted(() => ({
  update: vi.fn<(request: unknown) => Promise<object>>(),
  invalidate: vi.fn<() => Promise<void>>(),
  toastError: vi.fn(),
  toast: { success: vi.fn() }
}));
vi.mock("$app/navigation", () => ({ invalidate: api.invalidate }));
vi.mock("$lib/core/Eneo", () => ({ getEneo: () => ({ roles: { update: api.update } }) }));
vi.mock("$lib/core/errors", () => ({ toastError: api.toastError }));
vi.mock("$lib/components/toast", () => ({ toast: api.toast }));

import type { Permission, Role } from "@eneo/eneo-js";
import RoleEditor from "./RoleEditor.svelte";

const permissions = (["admin", "retention_manage", "retention_holds"] as Permission[]).map(
  (name) => ({ name, description: `${name} description` })
);
const role: Role = {
  id: "role-1",
  name: "Arkivansvarig",
  permissions: ["admin"] as Permission[],
  predefined_source: null
};

describe("RoleEditor", () => {
  test("saves a retention permission granted to a role", async () => {
    api.update.mockResolvedValue({});
    api.invalidate.mockResolvedValue();
    render(RoleEditor, { mode: "update", role, permissions, open: true, hideTrigger: true });

    await page.getByRole("switch", { name: "permission_retention_manage", exact: true }).click();
    await page.getByRole("button", { name: "save_changes" }).click();

    await expect.poll(() => api.update.mock.calls.length).toBe(1);
    expect(api.update).toHaveBeenCalledWith({
      role: { id: "role-1" },
      update: { permissions: ["admin", "retention_manage"] }
    });
    expect(api.toastError).not.toHaveBeenCalled();
  });
});

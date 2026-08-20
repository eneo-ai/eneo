import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import "../../../../app.css";

const listModules = vi.hoisted(() => vi.fn());
const installModule = vi.hoisted(() => vi.fn());
const uninstallModule = vi.hoisted(() => vi.fn());
const listApiKeys = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    modules: {
      list: listModules,
      install: installModule,
      uninstall: uninstallModule
    },
    apiKeys: { admin: { list: listApiKeys } }
  })
}));

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, unknown>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

import ModulesPage from "./+page.svelte";

function clickElement(element: Element): void {
  if (!(element instanceof HTMLElement)) throw new TypeError("Expected an HTML element");
  element.click();
}

const installation = {
  module_id: "8b63d76e-3fa5-4d1f-930c-ef33f827439a",
  module_key: "reports",
  redirect_uris: ["https://reports.example/auth/callback"],
  service_key_id: "40eff4f1-4471-47fd-8670-abda02baf73e",
  configured: true
};

const serviceKey = {
  id: "40eff4f1-4471-47fd-8670-abda02baf73e",
  ownership: "service",
  key_prefix: "sk_",
  key_suffix: "f827439a",
  name: "Reports module",
  key_type: "sk_",
  permission: "write",
  scope_type: "tenant",
  state: "active"
};

describe("module administration page", () => {
  beforeEach(() => {
    listModules.mockReset().mockResolvedValue({ items: [installation], count: 1 });
    listApiKeys
      .mockReset()
      .mockResolvedValue({ items: [serviceKey], total_count: 1, count: 1, next_cursor: null });
    installModule.mockReset().mockResolvedValue(installation);
    uninstallModule.mockReset().mockResolvedValue({
      module_id: installation.module_id,
      module_key: installation.module_key,
      enabled: false,
      changed: true
    });
  });

  test("edits an installation with the complete tenant-implicit command", async () => {
    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    clickElement(page.getByRole("button", { name: /edit/ }).element());
    await userEvent.fill(
      page.getByLabelText("module_admin_callback_urls"),
      "https://reports.example/login/callback"
    );
    clickElement(page.getByRole("button", { name: "module_admin_update" }).element());

    await vi.waitFor(() =>
      expect(installModule).toHaveBeenCalledWith({
        moduleKey: "reports",
        config: {
          redirect_uris: ["https://reports.example/login/callback"],
          service_key_id: serviceKey.id
        }
      })
    );
    await vi.waitFor(() => expect(listModules).toHaveBeenCalledTimes(2));
    expect(listApiKeys).toHaveBeenNthCalledWith(1, {
      limit: 200,
      state: "active",
      key_type: "sk_"
    });
    expect(installModule.mock.calls[0][0]).not.toHaveProperty("tenantId");
  });

  test("loads compatible service keys from every cursor page", async () => {
    listApiKeys
      .mockReset()
      .mockResolvedValueOnce({ items: [], count: 0, next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [serviceKey], count: 1, next_cursor: null });

    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    await vi.waitFor(() => expect(listApiKeys).toHaveBeenCalledTimes(2));
    expect(listApiKeys).toHaveBeenNthCalledWith(1, {
      limit: 200,
      state: "active",
      key_type: "sk_"
    });
    expect(listApiKeys).toHaveBeenNthCalledWith(2, {
      limit: 200,
      cursor: "page-2",
      state: "active",
      key_type: "sk_"
    });

    clickElement(page.getByRole("button", { name: /edit/ }).element());
    await expect.element(page.getByText(/Reports module/)).toBeVisible();
  });

  test("requires confirmation before uninstalling", async () => {
    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    clickElement(page.getByRole("button", { name: /remove/ }).element());
    expect(uninstallModule).not.toHaveBeenCalled();

    const dialog = page.getByRole("alertdialog");
    await expect.element(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "remove" }).click();

    await vi.waitFor(() => expect(uninstallModule).toHaveBeenCalledWith({ moduleKey: "reports" }));
    await vi.waitFor(() => expect(listModules).toHaveBeenCalledTimes(2));
    await expect.element(dialog).not.toBeInTheDocument();
  });

  test("keeps uninstall errors in the open confirmation dialog", async () => {
    uninstallModule.mockRejectedValueOnce(new Error("uninstall failed"));
    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    clickElement(page.getByRole("button", { name: /remove/ }).element());

    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("button", { name: "remove" }).click();

    await vi.waitFor(() => expect(uninstallModule).toHaveBeenCalledTimes(1));
    await expect.element(dialog).toBeVisible();
    await expect.element(dialog.getByRole("alert")).toHaveTextContent("request_failed");
  });
});

import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { EneoError } from "@eneo/eneo-js";
import "../../../../app.css";

const listModules = vi.hoisted(() => vi.fn());
const listModuleServiceKeys = vi.hoisted(() => vi.fn());
const getModuleServiceKey = vi.hoisted(() => vi.fn());
const installModule = vi.hoisted(() => vi.fn());
const uninstallModule = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    modules: {
      list: listModules,
      listServiceKeys: listModuleServiceKeys,
      getServiceKey: getModuleServiceKey,
      install: installModule,
      uninstall: uninstallModule
    }
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

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
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
    listModuleServiceKeys
      .mockReset()
      .mockResolvedValue({ items: [serviceKey], total_count: 1, count: 1, next_cursor: null });
    getModuleServiceKey.mockReset().mockResolvedValue(serviceKey);
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
    expect(listModuleServiceKeys).toHaveBeenCalledTimes(1);
    expect(listModuleServiceKeys).toHaveBeenNthCalledWith(1, { limit: 50 });
    expect(installModule.mock.calls[0][0]).not.toHaveProperty("tenantId");
  });

  test("keeps the initial service-key request bounded and loads more on demand", async () => {
    const secondServiceKey = {
      ...serviceKey,
      id: "2f1623ee-158f-4b58-85a5-ff26fbd67f0a",
      name: "Later module key"
    };
    listModules.mockResolvedValue({
      items: [{ ...installation, service_key_id: secondServiceKey.id }],
      count: 1
    });
    listModuleServiceKeys
      .mockReset()
      .mockResolvedValueOnce({ items: [serviceKey], count: 1, next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [secondServiceKey], count: 1, next_cursor: null });

    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    expect(listModuleServiceKeys).toHaveBeenCalledTimes(1);

    clickElement(page.getByRole("button", { name: "load_more" }).element());

    await vi.waitFor(() =>
      expect(listModuleServiceKeys).toHaveBeenNthCalledWith(2, {
        limit: 50,
        cursor: "page-2"
      })
    );
    clickElement(page.getByRole("button", { name: /edit/ }).element());
    await expect
      .element(page.getByLabelText("module_admin_service_key", { exact: true }))
      .toHaveTextContent("Later module key");
  });

  test("keeps catalog controls disabled until the guarded initial request settles", async () => {
    const initialPage = deferred<{
      items: (typeof serviceKey)[];
      count: number;
      next_cursor: string | null;
    }>();
    listModuleServiceKeys.mockReset().mockReturnValueOnce(initialPage.promise);

    render(ModulesPage);

    const searchInput = page.getByLabelText("module_admin_service_key search").element();
    const searchButton = page.getByRole("button", { name: "search", exact: true }).element();
    const controlsWereDisabled =
      searchInput instanceof HTMLInputElement &&
      searchInput.disabled &&
      searchButton instanceof HTMLButtonElement &&
      searchButton.disabled;

    initialPage.resolve({ items: [serviceKey], count: 1, next_cursor: null });

    expect(controlsWereDisabled).toBe(true);
    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    await expect.element(page.getByLabelText("module_admin_service_key search")).toBeEnabled();
  });

  test("keeps pagination paired with the applied search instead of the edited input", async () => {
    listModuleServiceKeys
      .mockReset()
      .mockResolvedValueOnce({ items: [serviceKey], count: 1, next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [], count: 0, next_cursor: null });

    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    await userEvent.fill(page.getByLabelText("module_admin_service_key search"), "payroll");
    clickElement(page.getByRole("button", { name: "load_more" }).element());

    await vi.waitFor(() =>
      expect(listModuleServiceKeys).toHaveBeenNthCalledWith(2, {
        limit: 50,
        cursor: "page-2"
      })
    );
  });

  test("searches service keys through the bounded module catalog", async () => {
    const searchedKey = { ...serviceKey, name: "Payroll module" };
    listModuleServiceKeys.mockImplementation(async ({ search }) => ({
      items: search === "payroll" ? [searchedKey] : [serviceKey],
      count: 1,
      next_cursor: null
    }));

    render(ModulesPage);
    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    await userEvent.fill(page.getByLabelText("module_admin_service_key search"), "payroll");
    clickElement(page.getByRole("button", { name: "search", exact: true }).element());

    await vi.waitFor(() =>
      expect(listModuleServiceKeys).toHaveBeenLastCalledWith({
        limit: 50,
        search: "payroll"
      })
    );
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

  test("blocks saving a stale bound key when it is no longer eligible", async () => {
    listModuleServiceKeys
      .mockReset()
      .mockResolvedValue({ items: [], total_count: 0, count: 0, next_cursor: null });
    getModuleServiceKey.mockRejectedValueOnce(
      new EneoError("Not found", "RESPONSE", 404, 0, undefined, {
        endpoint: "GET@/api/v1/admin/modules/service-keys/{service_key_id}/"
      })
    );
    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    clickElement(page.getByRole("button", { name: /edit/ }).element());

    await expect.element(page.getByText("module_admin_bound_key_missing")).toBeVisible();
    expect(getModuleServiceKey).toHaveBeenCalledWith({ serviceKeyId: installation.service_key_id });
    clickElement(page.getByRole("button", { name: "module_admin_update" }).element());
    expect(installModule).not.toHaveBeenCalled();
  });

  test("reports a bound-key lookup failure without mislabeling the key as ineligible", async () => {
    listModuleServiceKeys.mockResolvedValue({ items: [], count: 0, next_cursor: null });
    getModuleServiceKey.mockRejectedValueOnce(new Error("network unavailable"));
    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    clickElement(page.getByRole("button", { name: /edit/ }).element());

    await expect.element(page.getByText("request_failed", { exact: true })).toBeVisible();
    await expect.element(page.getByText("module_admin_bound_key_missing")).not.toBeInTheDocument();
  });

  test("explicitly unbinds ticket exchange without uninstalling", async () => {
    render(ModulesPage);

    await expect.element(page.getByText("reports", { exact: true })).toBeVisible();
    clickElement(page.getByRole("button", { name: /edit/ }).element());
    const serviceKeySelect = page
      .getByLabelText("module_admin_service_key", { exact: true })
      .element();
    if (!(serviceKeySelect instanceof HTMLElement)) {
      throw new TypeError("Expected the service key select to be an HTML element");
    }
    serviceKeySelect.focus();
    await userEvent.keyboard("{Enter}");
    await page.getByRole("option", { name: "module_admin_service_key_unbound" }).click();
    clickElement(page.getByRole("button", { name: "module_admin_update" }).element());

    await vi.waitFor(() =>
      expect(installModule).toHaveBeenCalledWith({
        moduleKey: "reports",
        config: {
          redirect_uris: installation.redirect_uris,
          service_key_id: null
        }
      })
    );
    expect(uninstallModule).not.toHaveBeenCalled();
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

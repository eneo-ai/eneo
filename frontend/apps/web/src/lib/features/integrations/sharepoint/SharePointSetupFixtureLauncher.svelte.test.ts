import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.hoisted(() =>
  vi.fn(async (path: string) => {
    throw new Error(`Unexpected API call in fixture mode: ${path}`);
  })
);

const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    client: { fetch: apiFetch }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { error: toastError, success: toastSuccess, warning: vi.fn(), info: vi.fn() }
}));

vi.mock("$lib/core/errors", () => ({
  toastError: vi.fn(),
  getErrorMessage: (error: unknown) => String(error)
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

import SharePointSetupFixtureLauncher from "./SharePointSetupFixtureLauncher.svelte";

describe("SharePointSetupFixtureLauncher", () => {
  beforeEach(() => {
    apiFetch.mockClear();
    toastSuccess.mockClear();
    toastError.mockClear();
  });

  it("walks through a simulated tenant-app setup without touching the API", async () => {
    render(SharePointSetupFixtureLauncher, {});

    await page.getByRole("button", { name: "sharepoint_setup_fixture_open" }).click();

    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent("sharepoint_fixture_compact_title");

    await page.getByText("tenant_app_option").click();

    await page.getByLabelText("client_id").fill("12345678-1234-1234-1234-123456789012");
    await page.getByLabelText("client_secret").fill("fixture-secret");
    await page.getByLabelText("tenant_id_or_domain").fill("kommunen.onmicrosoft.com");

    await page.getByRole("button", { name: "test_connection" }).click();
    await expect.element(page.getByText("connection_successful")).toBeVisible();

    await page.getByRole("button", { name: "sharepoint_fixture_simulate_save" }).click();
    await expect.element(page.getByText("current_configuration")).toBeVisible();
    expect(toastSuccess).toHaveBeenCalledWith("sharepoint_fixture_simulated_saved");

    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows the configured scenario and simulates deletion", async () => {
    render(SharePointSetupFixtureLauncher, {});

    await page.getByRole("button", { name: "sharepoint_setup_fixture_open" }).click();
    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent("sharepoint_fixture_compact_title");

    await page.getByRole("button", { name: "sharepoint_fixture_scenario_label" }).click();
    await page
      .getByRole("option", { name: "sharepoint_setup_fixture_scenario_configured" })
      .click();

    await expect.element(page.getByText("current_configuration")).toBeVisible();

    await page.getByRole("button", { name: "delete_sharepoint_app" }).click();
    await expect.element(page.getByRole("alertdialog")).toBeInTheDocument();

    await page
      .getByLabelText('type_to_confirm {"word":"sharepoint_delete_confirmation_word"}')
      .fill("sharepoint_delete_confirmation_word");
    await page.getByRole("button", { name: "permanent_delete" }).click();

    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    await vi.waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("sharepoint_fixture_simulated_deleted")
    );

    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("simulates a connection error with the realistic Entra message", async () => {
    render(SharePointSetupFixtureLauncher, {});

    await page.getByRole("button", { name: "sharepoint_setup_fixture_open" }).click();
    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent("sharepoint_fixture_compact_title");

    await page.getByRole("button", { name: "sharepoint_fixture_scenario_label" }).click();
    await page
      .getByRole("option", { name: "sharepoint_setup_fixture_scenario_connection_error" })
      .click();

    await page.getByText("tenant_app_option").click();
    await page.getByLabelText("client_id").fill("12345678-1234-1234-1234-123456789012");
    await page.getByLabelText("client_secret").fill("wrong-secret");
    await page.getByLabelText("tenant_id_or_domain").fill("kommunen.onmicrosoft.com");

    await page.getByRole("button", { name: "test_connection" }).click();

    await expect.element(page.getByText("connection_failed")).toBeVisible();
    await expect.element(page.getByText(/AADSTS7000215/)).toBeVisible();

    expect(apiFetch).not.toHaveBeenCalled();
  });
});

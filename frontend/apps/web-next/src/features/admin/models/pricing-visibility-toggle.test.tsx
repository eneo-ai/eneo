// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { useAppContext } from "@/components/providers/app-context";
import { QueryAppContextProvider } from "@/components/providers/app-context-from-queries";
import { browserApi } from "@/lib/api/browser";
import { loadSession, sessionKeys } from "@/lib/api/session";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError }));

import { PricingVisibilityToggle } from "./pricing-visibility-toggle";

const pricingShown = testAppContext({ tenant: { show_model_pricing: true } });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("hides model prices from users and invalidates only the tenant", async () => {
  api.PUT.mockResolvedValue({ data: {}, response: new Response("{}") });
  const { queryClient } = renderInApp(<PricingVisibilityToggle />, { appContext: pricingShown });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const toggle = screen.getByRole("switch", { name: "Visa modellpriser för användare" });
  expect((toggle as HTMLInputElement).checked).toBe(true);
  await expectNoAxeViolations(document.body);

  fireEvent.click(toggle);

  await waitFor(() =>
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: sessionKeys.tenant })
  );
  expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/settings/model-pricing-visibility", {
    body: { show_model_pricing: false }
  });
  expect((toggle as HTMLInputElement).checked).toBe(false);
});

it("falls back to the saved value when saving fails", async () => {
  api.PUT.mockResolvedValue({
    error: { message: "nope" },
    response: new Response("{}", { status: 500 })
  });
  const { queryClient } = renderInApp(<PricingVisibilityToggle />, { appContext: pricingShown });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const toggle = screen.getByRole("switch", { name: "Visa modellpriser för användare" });

  fireEvent.click(toggle);

  await waitFor(() => expect(toastApiError).toHaveBeenCalled());
  await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true));
  expect(invalidate).not.toHaveBeenCalled();
});

function Models() {
  const { tenant } = useAppContext();
  return (
    <ModelSelector
      models={[
        {
          id: "model",
          name: "Example",
          max_input_tokens: 128000,
          max_output_tokens: 4096,
          is_deprecated: false,
          vision: false,
          reasoning: false,
          token_limit: 128000,
          supported_model_kwargs: {},
          input_cost_per_token: "0.0000025",
          output_cost_per_token: "0.00001"
        }
      ]}
      selectedId="model"
      onSelect={() => {}}
      showPricing={tenant.show_model_pricing === true}
    />
  );
}

it("updates prices in an existing model picker through the shared tenant query", async () => {
  let tenant = pricingShown.tenant;
  const replies = new Map<string, unknown>([
    ["/api/v1/users/me/", pricingShown.user],
    ["/api/v1/settings/", { ...pricingShown.settings, whats_new_enabled: false }],
    ["/api/v1/auth/federation-status", pricingShown.federationStatus],
    ["/api/v1/limits/", pricingShown.limits],
    ["/api/v1/whats-new/state/", null]
  ]);
  api.GET.mockImplementation(async (path: string) => ({
    data: path === "/api/v1/users/tenant/" ? tenant : replies.get(path),
    response: new Response("{}")
  }));
  api.PUT.mockImplementation(async (_path, { body }) => {
    tenant = { ...tenant, show_model_pricing: body.show_model_pricing };
    return { data: body, response: new Response("{}") };
  });
  const queryClient = testQueryClient();
  await loadSession(queryClient, browserApi);
  renderInApp(
    <QueryAppContextProvider
      env={{ links: pricingShown.links, frontendVersion: "1", backendVersion: "1" }}
    >
      <PricingVisibilityToggle />
      <Models />
    </QueryAppContextProvider>,
    { queryClient }
  );
  api.GET.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "Chattmodell: Example" }));
  expect((await screen.findByRole("option", { name: /^Example/ })).textContent).toContain(
    "$2.50 / $10.00"
  );
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
  fireEvent.click(screen.getByRole("switch", { name: "Visa modellpriser för användare" }));
  await waitFor(() =>
    expect(queryClient.getQueryData(sessionKeys.tenant)).toMatchObject({
      show_model_pricing: false
    })
  );
  fireEvent.click(screen.getByRole("button", { name: "Chattmodell: Example" }));
  expect((await screen.findByRole("option", { name: /^Example/ })).textContent).not.toContain("$");
  expect(api.GET).toHaveBeenCalledExactlyOnceWith("/api/v1/users/tenant/");
});

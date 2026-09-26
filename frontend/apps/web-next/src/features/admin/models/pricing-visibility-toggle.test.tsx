// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ PUT: vi.fn() }));
const refresh = vi.hoisted(() => vi.fn());
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({ tenant: { show_model_pricing: true } })
}));

import { PricingVisibilityToggle } from "./pricing-visibility-toggle";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("hides model prices from users and refreshes the app", async () => {
  api.PUT.mockResolvedValue({ data: {}, response: new Response("{}") });
  renderInApp(<PricingVisibilityToggle />);
  const toggle = screen.getByRole("switch", { name: "Visa modellpriser för användare" });
  expect((toggle as HTMLInputElement).checked).toBe(true);
  await expectNoAxeViolations(document.body);

  fireEvent.click(toggle);

  await waitFor(() => expect(refresh).toHaveBeenCalled());
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
  renderInApp(<PricingVisibilityToggle />);
  const toggle = screen.getByRole("switch", { name: "Visa modellpriser för användare" });

  fireEvent.click(toggle);

  await waitFor(() => expect(toastApiError).toHaveBeenCalled());
  await waitFor(() => expect((toggle as HTMLInputElement).checked).toBe(true));
  expect(refresh).not.toHaveBeenCalled();
});

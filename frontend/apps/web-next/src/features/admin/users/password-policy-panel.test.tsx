// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { PasswordPolicyPanel } from "./password-policy-panel";

afterEach(() => vi.clearAllMocks());

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

async function show(
  policy: { require_change_after_admin_set: boolean; max_age_days: number | null } = {
    require_change_after_admin_set: true,
    max_age_days: null
  }
) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/password-policy" ? ok(policy) : ok({})
  );
  renderInApp(<PasswordPolicyPanel />);
  const panel = screen.getByRole("region", { name: "Lösenordspolicy" });
  await within(panel).findByRole("switch");
  return panel;
}

it("saves both rules in one request and reports the saved policy", async () => {
  api.PATCH.mockImplementation((_path: string, init: { body: unknown }) => ok(init.body));
  const panel = await show();
  const save = within(panel).getByRole("button", { name: "Spara" });
  expect(save.hasAttribute("disabled")).toBe(true);

  fireEvent.click(within(panel).getByRole("switch"));
  fireEvent.change(within(panel).getByLabelText(/Längsta giltighetstid/), {
    target: { value: "90" }
  });
  expect(save.hasAttribute("disabled")).toBe(false);
  fireEvent.click(save);

  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/password-policy", {
      body: { require_change_after_admin_set: false, max_age_days: 90 }
    })
  );
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Lösenordspolicyn är sparad."));
  // The form now shows the saved policy, with nothing left to save.
  await waitFor(() =>
    expect(within(panel).getByRole("button", { name: "Spara" }).hasAttribute("disabled")).toBe(true)
  );
  await expectNoAxeViolations(panel);
});

it("explains a malformed age at the field and never sends it", async () => {
  const panel = await show({ require_change_after_admin_set: true, max_age_days: 30 });
  const maxAge = within(panel).getByLabelText(/Längsta giltighetstid/);
  fireEvent.change(maxAge, { target: { value: "ninety" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Spara" }));

  expect(api.PATCH).not.toHaveBeenCalled();
  await waitFor(() => expect(maxAge.getAttribute("aria-invalid")).toBe("true"));
  expect(within(panel).getByText(/heltal mellan 1 och 3650/)).toBeTruthy();
  expect(document.activeElement).toBe(maxAge);
  await expectNoAxeViolations(panel);
});

// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ApiKeyPolicyDialog } from "./policy-panel";

afterEach(() => vi.clearAllMocks());

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

function show() {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/api-key-policy"
      ? ok({
          require_expiration: false,
          max_expiration_days: 90,
          auto_expire_unused_days: null,
          max_rate_limit_override: null,
          rotation_grace_hours: 24,
          max_delegation_depth: null,
          revocation_cascade_enabled: false
        })
      : ok({ super_api_key_configured: true })
  );
  const onOpenChange = vi.fn();
  renderInApp(<ApiKeyPolicyDialog open onOpenChange={onOpenChange} />);
  return { onOpenChange, dialog: screen.getByRole("dialog", { name: "Organisationspolicy" }) };
}

it("closes on Save with nothing changed, without sending anything", async () => {
  const { onOpenChange, dialog } = show();
  const save = await within(dialog).findByRole("button", { name: "Spara ändringar" });
  expect(save.hasAttribute("disabled")).toBe(false);

  fireEvent.click(save);

  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(api.PATCH).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);
});

it("keeps focus on a busy Save and sends a change once", async () => {
  let resolve: (value: unknown) => void = () => {};
  api.PATCH.mockReturnValue(
    new Promise((done) => {
      resolve = done;
    })
  );
  const { onOpenChange, dialog } = show();
  const days = await within(dialog).findByRole("spinbutton", {
    name: "Maximalt antal utgångsdagar"
  });
  fireEvent.change(days, { target: { value: "30" } });
  const save = within(dialog).getByRole("button", { name: "Spara ändringar" });
  save.focus();

  fireEvent.click(save);
  await waitFor(() => expect(save.getAttribute("aria-busy")).toBe("true"));
  expect(save.hasAttribute("disabled")).toBe(false);
  expect(document.activeElement).toBe(save);
  fireEvent.click(save);
  expect(api.PATCH).toHaveBeenCalledTimes(1);
  expect(api.PATCH).toHaveBeenCalledWith("/api/v1/admin/api-key-policy", {
    body: { max_expiration_days: 30 }
  });

  resolve({ data: {}, response: new Response("{}") });
  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});

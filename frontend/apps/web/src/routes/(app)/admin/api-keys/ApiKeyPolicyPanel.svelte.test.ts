import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../../../../app.css";
import { overwriteGetLocale } from "$lib/paraglide/runtime";
import { m } from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
import ApiKeyPolicyPanel from "./ApiKeyPolicyPanel.svelte";

const getPolicy = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    apiKeys: { admin: { getPolicy, updatePolicy: vi.fn() } }
  })
}));

afterEach(() => vi.clearAllMocks());

describe("ApiKeyPolicyPanel", () => {
  it.each([
    ["sv", ["kl. 01:00 UTC", "tjänstenycklar", "längsta uppehåll"]],
    ["en", ["01:00 UTC", "service keys", "longest pause"]]
  ] as const)(
    "tells the admin in %s when unused keys expire and that service keys count",
    async (locale, phrases) => {
      overwriteGetLocale(() => locale);
      getPolicy.mockResolvedValue({ auto_expire_unused_days: 30 });
      render(ApiKeyPolicyPanel);

      const days = page.getByRole("spinbutton", { name: m.api_keys_admin_policy_auto_expire() });
      await expect.element(days).toHaveValue(30);
      for (const phrase of phrases) {
        await expect.element(days).toHaveAccessibleDescription(new RegExp(phrase));
      }
      await expectNoAxeViolations(document.body);
    }
  );
});

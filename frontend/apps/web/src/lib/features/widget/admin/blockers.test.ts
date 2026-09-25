import type { Widget, WidgetPolicy } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({ m: {} }));

import { policyViolations } from "./blockers";

const policy: WidgetPolicy = {
  max_daily_token_budget: 1000,
  min_retention_days: 7,
  max_retention_days: 90,
  allow_bot_protection_none: false
};

function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    limits: { daily_token_budget: 1000 },
    privacy: { retention_days: 30 },
    bot_protection: "altcha",
    ...overrides
  } as Widget;
}

describe("policyViolations", () => {
  it("finds nothing for a widget within the policy, or without a policy", () => {
    expect(policyViolations(widget(), policy)).toEqual([]);
    expect(policyViolations(widget({ bot_protection: "none" }), null)).toEqual([]);
  });

  it("names every setting outside the policy, as the API does", () => {
    expect(
      policyViolations(
        widget({
          limits: { daily_token_budget: 1001 },
          privacy: { retention_days: 91 },
          bot_protection: "none"
        }),
        policy
      )
    ).toEqual([
      "daily_token_budget_exceeds_policy",
      "retention_above_policy_maximum",
      "bot_protection_none_not_allowed"
    ]);
    expect(policyViolations(widget({ privacy: { retention_days: 6 } }), policy)).toEqual([
      "retention_below_policy_minimum"
    ]);
  });

  it("checks settings a widget never saved at the API's defaults", () => {
    expect(policyViolations(widget({ limits: {}, privacy: {} }), policy)).toEqual([
      "daily_token_budget_exceeds_policy"
    ]);
    expect(
      policyViolations(widget({ bot_protection: "none" }), {
        ...policy,
        allow_bot_protection_none: true
      })
    ).toEqual([]);
  });
});

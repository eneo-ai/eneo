import { describe, expect, it } from "vitest";
import {
  SHAREPOINT_FIXTURE_QUERY_PARAMETER,
  assertSharePointFixtureEnvelope,
  isSharePointFixtureModeRequested,
  parseSharePointFixtureScenario
} from "./fixtureMode";

describe("SharePoint fixture mode", () => {
  it.each(["representative", "large_tenant", "empty"] as const)(
    "accepts the documented %s scenario",
    (scenario) => {
      const params = new URLSearchParams({ [SHAREPOINT_FIXTURE_QUERY_PARAMETER]: scenario });
      expect(parseSharePointFixtureScenario(params)).toBe(scenario);
    }
  );

  it("stays off without an explicit valid scenario", () => {
    expect(parseSharePointFixtureScenario(new URLSearchParams())).toBeNull();
    expect(
      parseSharePointFixtureScenario(
        new URLSearchParams({ [SHAREPOINT_FIXTURE_QUERY_PARAMETER]: "production" })
      )
    ).toBeNull();
  });

  it("keeps an invalid explicit request in fixture mode instead of falling back", () => {
    const params = new URLSearchParams({
      [SHAREPOINT_FIXTURE_QUERY_PARAMETER]: "misspelled"
    });

    expect(isSharePointFixtureModeRequested(params)).toBe(true);
    expect(parseSharePointFixtureScenario(params)).toBeNull();
  });

  it("rejects responses that are not explicitly marked as fixture data", () => {
    expect(() =>
      assertSharePointFixtureEnvelope({ scenario: "representative" }, "representative")
    ).toThrow("invalid fixture envelope");
    expect(() =>
      assertSharePointFixtureEnvelope({ fixture: true, scenario: "large_tenant" }, "representative")
    ).toThrow("invalid fixture envelope");
    expect(() =>
      assertSharePointFixtureEnvelope(
        { fixture: true, scenario: "representative" },
        "representative"
      )
    ).not.toThrow();
  });
});

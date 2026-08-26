import { describe, expect, it } from "vitest";
import {
  SHAREPOINT_FIXTURE_QUERY_PARAMETER,
  assertSharePointFixtureEnvelope,
  isSharePointFixtureModeRequested,
  parseSharePointFixtureScenario,
  withSharePointFixtureIntegration
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

  it.each(["user_oauth", "tenant_app"] as const)(
    "offers a connected fixture integration for %s spaces without Microsoft configuration",
    (authType) => {
      const params = new URLSearchParams({
        [SHAREPOINT_FIXTURE_QUERY_PARAMETER]: "representative"
      });

      const integrations = withSharePointFixtureIntegration([], params, authType);

      expect(integrations).toEqual([
        expect.objectContaining({
          name: "SharePoint test data",
          integration_type: "sharepoint",
          connected: true,
          auth_type: authType,
          tenant_app_configured: false
        })
      ]);
    }
  );

  it("does not expose or duplicate the fixture integration outside its explicit request", () => {
    const connectedSharePoint = {
      id: "00000000-0000-4000-8000-000000000010",
      name: "SharePoint",
      description: "Connected SharePoint",
      integration_type: "sharepoint" as const,
      tenant_integration_id: "00000000-0000-4000-8000-000000000011",
      connected: true,
      auth_type: "user_oauth"
    };

    expect(
      withSharePointFixtureIntegration([connectedSharePoint], new URLSearchParams(), "user_oauth")
    ).toEqual([connectedSharePoint]);
    expect(
      withSharePointFixtureIntegration(
        [connectedSharePoint],
        new URLSearchParams({ [SHAREPOINT_FIXTURE_QUERY_PARAMETER]: "empty" }),
        "user_oauth"
      )
    ).toEqual([connectedSharePoint]);
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

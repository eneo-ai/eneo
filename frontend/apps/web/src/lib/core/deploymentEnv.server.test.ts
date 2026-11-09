import { describe, expect, it, vi } from "vitest";
import { assertDeploymentEnv, inspectDeploymentEnv } from "./deploymentEnv.server";

const configured = {
  ENEO_BACKEND_URL: "https://eneo.example.com",
  PUBLIC_ENEO_BACKEND_URL: "https://eneo.example.com"
};

describe("inspectDeploymentEnv", () => {
  it("accepts a configured environment", () => {
    expect(inspectDeploymentEnv(configured)).toEqual({ errors: [], warnings: [] });
  });

  it.each([
    ["INTRIC_BACKEND_URL", "ENEO_BACKEND_URL"],
    ["INTRIC_BACKEND_SERVER_URL", "ENEO_BACKEND_SERVER_URL"],
    ["PUBLIC_INTRIC_BACKEND_URL", "PUBLIC_ENEO_BACKEND_URL"]
  ])("rejects %s without %s and names the replacement", (removed, replacement) => {
    const env: Record<string, string | undefined> = {
      ...configured,
      [removed]: "https://eneo.example.com"
    };
    delete env[replacement];

    const { errors } = inspectDeploymentEnv(env);

    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain(`Rename it to ${replacement}`);
  });

  it("only warns about a removed name next to its replacement", () => {
    const report = inspectDeploymentEnv({ ...configured, INTRIC_BACKEND_URL: "https://old" });

    expect(report.errors).toEqual([]);
    expect(report.warnings).toEqual([
      "INTRIC_BACKEND_URL is ignored because ENEO_BACKEND_URL is set. Remove INTRIC_BACKEND_URL."
    ]);
  });

  it("rejects a missing backend URL", () => {
    const { errors } = inspectDeploymentEnv({ ENEO_BACKEND_URL: " " });

    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("ENEO_BACKEND_URL is not set");
  });

  it("reports only the rename when the old backend URL is the one set", () => {
    const { errors } = inspectDeploymentEnv({ INTRIC_BACKEND_URL: "https://old" });

    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("Rename it to ENEO_BACKEND_URL");
  });
});

describe("removed MobilityGuard settings", () => {
  it.each(["MOBILITY_GUARD_AUTH", "MOBILITYGUARD_CLIENT_ID"])(
    "warns that %s is no longer read and points to the OIDC settings",
    (name) => {
      const report = inspectDeploymentEnv({ ...configured, [name]: "old" });

      expect(report.errors).toEqual([]);
      expect(report.warnings).toHaveLength(1);
      expect(report.warnings[0]).toContain(`${name} is no longer used for sign-in`);
      expect(report.warnings[0]).toContain("OIDC_");
      expect(report.warnings[0]).toContain(
        "https://docs.eneo.ai/guides/oidc-federation#migrate-from-the-mobilityguard-settings"
      );
      expect(report.warnings[0]).not.toContain("Eneo 2.2");
    }
  );
});

describe("deprecated Zitadel settings", () => {
  const guide = "https://docs.eneo.ai/guides/oidc-federation#migrate-from-the-zitadel-settings";

  it.each([
    [{ ZITADEL_INSTANCE_URL: "https://zitadel.example.com" }],
    [{ ZITADEL_PROJECT_CLIENT_ID: "client" }],
    [{ ZITADEL_INSTANCE_URL: "https://zitadel.example.com", ZITADEL_PROJECT_CLIENT_ID: "client" }]
  ])("warns once for %o and points to the OIDC settings", (zitadel) => {
    const report = inspectDeploymentEnv({ ...configured, ...zitadel });

    expect(report.errors).toEqual([]);
    expect(report.warnings).toHaveLength(1);
    const [warning] = report.warnings;
    for (const name of Object.keys(zitadel)) expect(warning).toContain(name);
    expect(warning).toContain("deprecated");
    expect(warning).toContain("removed in the next release");
    expect(warning).toContain("OIDC_DISCOVERY_ENDPOINT, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET");
    expect(warning).toContain(guide);
  });

  it("ignores Zitadel variables the web app never read", () => {
    expect(
      inspectDeploymentEnv({ ...configured, ZITADEL_MASTERKEY: "x", ZITADEL_INSTANCE_URL: " " })
    ).toEqual({ errors: [], warnings: [] });
  });
});

describe("assertDeploymentEnv", () => {
  it("throws with every problem at once", () => {
    expect(() =>
      assertDeploymentEnv({
        INTRIC_BACKEND_URL: "https://old",
        PUBLIC_INTRIC_BACKEND_URL: "https://old"
      })
    ).toThrow(/INTRIC_BACKEND_URL[\s\S]*PUBLIC_INTRIC_BACKEND_URL/);
  });

  it("passes warnings to the logger without throwing", () => {
    const warn = vi.fn();

    assertDeploymentEnv({ ...configured, INTRIC_BACKEND_URL: "https://old" }, warn);

    expect(warn).toHaveBeenCalledOnce();
  });
});

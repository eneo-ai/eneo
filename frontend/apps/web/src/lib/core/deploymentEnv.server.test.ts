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

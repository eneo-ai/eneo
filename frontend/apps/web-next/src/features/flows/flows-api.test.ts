import { describe, expect, it } from "vitest";
import type { Permission } from "@/lib/auth/permissions";
import { flowsAvailable } from "./flows-api";

const userWith = (permissions: Permission[]) => ({
  roles: [{ permissions }],
  predefined_roles: []
});

describe("flowsAvailable", () => {
  it("shows flows when the tenant has them and the user may see flows", () => {
    expect(flowsAvailable({ flows_enabled: true }, userWith(["flows_view"]))).toBe(true);
  });

  it("hides flows from a tenant that has them switched off", () => {
    expect(flowsAvailable({ flows_enabled: false }, userWith(["flows_view"]))).toBe(false);
  });

  it("hides flows when the settings do not say (an older backend)", () => {
    expect(flowsAvailable({}, userWith(["flows_view"]))).toBe(false);
  });

  it("hides flows from a user without the permission to see them", () => {
    expect(flowsAvailable({ flows_enabled: true }, userWith(["flows_run"]))).toBe(false);
  });
});

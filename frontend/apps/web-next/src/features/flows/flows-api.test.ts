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
    // Tracing alone does not include seeing flows (the backend's aliases).
    expect(flowsAvailable({ flows_enabled: true }, userWith(["flows_trace"]))).toBe(false);
    expect(flowsAvailable({ flows_enabled: true }, userWith(["apps"]))).toBe(false);
  });

  it.each<Permission>(["flows_run", "flows_manage", "flows"])(
    "shows flows to a role holding only %s, which includes seeing them",
    (permission) => {
      expect(flowsAvailable({ flows_enabled: true }, userWith([permission]))).toBe(true);
    }
  );
});

import { describe, expect, it, vi } from "vitest";
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));
import { runtimeMessages, type RuntimeDiagnostics } from "./runtimeStatus";

const ready: RuntimeDiagnostics = {
  configured: true,
  state: "ready",
  expected_version: "2.3.0",
  version: "2.3.0",
  warnings: []
};
describe("runtime status", () => {
  it.each(["not_configured", "ready", "unreachable", "unauthorized", "unverified"] as const)(
    "explains %s",
    (state) => {
      expect(runtimeMessages({ ...ready, state })).toContain("tools_runtime_" + state);
    }
  );
  it("shows mismatch advice once and retains availability", () => {
    const status = { ...ready, warnings: ["version_mismatch", "revision_mismatch"] };
    expect(runtimeMessages(status)).toEqual(["tools_runtime_ready", "tools_runtime_mismatch"]);
    expect(status.state).toBe("ready");
  });
  it("separates file connectivity from confinement", () => {
    expect(
      runtimeMessages({
        ...ready,
        warnings: ["file_origin_unreachable", "confinement_unavailable"]
      })
    ).toEqual(["tools_runtime_ready", "tools_runtime_file_origin", "tools_runtime_confinement"]);
  });
});

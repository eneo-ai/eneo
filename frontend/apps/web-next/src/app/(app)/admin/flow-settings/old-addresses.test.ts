import { redirect } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import FlowDataRetentionRoute from "../flow-data-retention/page";
import FlowInputLimitsRoute from "../flow-input-limits/page";
import FlowKnowledgeEvidenceRoute from "../flow-knowledge-evidence/page";

vi.mock("next/navigation", () => ({
  redirect: vi.fn(() => {
    throw new Error("NEXT_REDIRECT");
  })
}));

describe("the flow admin pages' old addresses", () => {
  it.each([
    [FlowInputLimitsRoute, "/admin/flow-settings#flow-files"],
    [FlowKnowledgeEvidenceRoute, "/admin/flow-settings#flow-evidence-text"],
    [FlowDataRetentionRoute, "/admin/flow-settings"]
  ])("open the flow settings at the group that took their place", (route, target) => {
    expect(() => route()).toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenLastCalledWith(target);
  });
});

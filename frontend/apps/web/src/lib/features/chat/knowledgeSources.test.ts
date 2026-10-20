import { describe, expect, it } from "vitest";
import {
  getPartnerKnowledgeMode,
  getPartnerKnowledgeSources,
  hasKnowledgeSources,
  shouldShowNoSourcesNotice
} from "./knowledgeSources";

describe("getPartnerKnowledgeSources", () => {
  it("names websites by url when they have no name and tolerates a missing partner", () => {
    expect(
      getPartnerKnowledgeSources({
        groups: [{ id: "g1", name: "Policies" }],
        websites: [{ id: "w1", url: "https://example.test" }],
        integration_knowledge_list: [{ id: "i1", name: "Intranet" }]
      })
    ).toEqual({
      collections: [{ id: "g1", name: "Policies" }],
      websites: [{ id: "w1", name: "https://example.test" }],
      integrations: [{ id: "i1", name: "Intranet" }]
    });
    expect(hasKnowledgeSources(getPartnerKnowledgeSources(null))).toBe(false);
  });
});

describe("getPartnerKnowledgeMode", () => {
  it.each([
    ["tool mode with a tool-calling model", "tool", true, "tool"],
    ["tool mode with a model that cannot call tools", "tool", false, "inject"],
    ["inject mode", "inject", true, "inject"],
    ["no stored mode", undefined, true, "inject"]
  ] as const)("%s", (_label, stored, supportsTools, expected) => {
    expect(
      getPartnerKnowledgeMode({
        knowledge_mode: stored,
        completion_model: { id: "m", supports_tool_calling: supportsTools }
      })
    ).toBe(expected);
  });
});

describe("shouldShowNoSourcesNotice", () => {
  const base = {
    hasKnowledge: true,
    knowledgeMode: "inject",
    referenceCount: 0,
    isLoading: false
  } as const;

  it("shows once an inject-mode answer with attached knowledge ends without references", () => {
    expect(shouldShowNoSourcesNotice(base)).toBe(true);
  });

  it.each([
    ["no knowledge attached", { hasKnowledge: false }],
    ["tool mode", { knowledgeMode: "tool" }],
    ["references present", { referenceCount: 2 }],
    ["still streaming", { isLoading: true }]
  ] as const)("stays hidden with %s", (_label, override) => {
    expect(shouldShowNoSourcesNotice({ ...base, ...override })).toBe(false);
  });
});

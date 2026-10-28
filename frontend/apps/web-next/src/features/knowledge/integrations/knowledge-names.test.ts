import { describe, expect, it } from "vitest";
import { fitKnowledgeName, KNOWLEDGE_NAME_MAX_LENGTH } from "./knowledge-names";

describe("fitKnowledgeName", () => {
  it("keeps a name the server takes and cuts a longer one by characters", () => {
    expect(fitKnowledgeName("Protokoll")).toBe("Protokoll");
    const long = "😀".repeat(KNOWLEDGE_NAME_MAX_LENGTH + 5);
    const fitted = fitKnowledgeName(long);
    expect(Array.from(fitted)).toHaveLength(KNOWLEDGE_NAME_MAX_LENGTH);
    expect(fitted).toBe("😀".repeat(KNOWLEDGE_NAME_MAX_LENGTH));
  });
});

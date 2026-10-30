import { describe, expect, it } from "vitest";
import { knownClassifications, levelName } from "./classification-names";

const t = (key: string, values: Record<string, string | number> = {}) =>
  key === "flow_step_editor_classification_level" ? `Nivå ${values.level}` : key;

describe("classification names", () => {
  it("names the levels the space payload carries when the list says nothing", () => {
    const known = knownClassifications(undefined, {
      security_classification: { name: "Intern", security_level: 1 },
      completion_models: [
        { security_classification: { name: "Känslig", security_level: 2 } },
        { security_classification: null }
      ],
      mcp_servers: [{ security_classification: { name: "Öppen", security_level: 0 } }]
    });
    expect(known).toEqual([
      { security_level: 0, name: "Öppen" },
      { security_level: 1, name: "Intern" },
      { security_level: 2, name: "Känslig" }
    ]);
    expect(levelName(2, known, t)).toBe("Känslig");
    expect(levelName(3, known, t)).toBe("Nivå 3");
  });

  it("prefers the organisation's list where it answers", () => {
    const known = knownClassifications(
      [{ id: "c-1", name: "Intern (ny)", description: null, security_level: 1 }],
      { security_classification: { name: "Intern", security_level: 1 } }
    );
    expect(known).toEqual([{ security_level: 1, name: "Intern (ny)" }]);
  });
});

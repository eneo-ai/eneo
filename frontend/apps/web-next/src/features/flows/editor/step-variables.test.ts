import { describe, expect, it } from "vitest";
import { makeFlow, makeStep } from "../flow-fixtures";
import { contractFields, variableGroups } from "./step-variables";

describe("variableGroups", () => {
  const flow = makeFlow({ steps: [makeStep(1), makeStep(2)] });
  const runTokens = (sectionVariables?: boolean) =>
    variableGroups({ flow, stepOrder: 2, sectionVariables })
      .filter((group) => group.type === "run")
      .flatMap((group) => group.entries.map((entry) => entry.token));

  it("offers the section's number only to an instruction run once per section", () => {
    expect(runTokens()).toEqual(["datum", "föregående_steg"]);
    expect(runTokens(true)).toEqual(["datum", "section_index", "föregående_steg"]);
  });
});

describe("contractFields", () => {
  it("types a nullable field by its first non-null type", () => {
    expect(
      contractFields({
        properties: {
          namn: { type: "string" },
          antal: { type: ["null", "integer"] },
          okänd: {}
        }
      })
    ).toEqual([
      { name: "namn", type: "string" },
      { name: "antal", type: "integer" },
      { name: "okänd", type: null }
    ]);
  });
});

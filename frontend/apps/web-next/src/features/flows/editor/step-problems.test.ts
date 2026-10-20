import { describe, expect, it } from "vitest";
import { slugifyKey, uniqueKey } from "./step-keys";
import { placeProblems } from "./step-problems";

describe("placeProblems", () => {
  it("places a problem at the field it names when it is about this step", () => {
    expect(
      placeProblems(
        [
          "step 'intro' template: {{steps.nope}} must name an earlier step",
          "step 'intro' speaker_mapping.model_id abc is not available",
          "step 'other' prompt: something",
          "the space has no default completion model"
        ],
        "intro"
      )
    ).toEqual([
      { field: "template", text: "{{steps.nope}} must name an earlier step" },
      { field: "speaker_mapping", text: "Abc is not available" },
      { field: null, text: "step 'other' prompt: something" },
      { field: null, text: "the space has no default completion model" }
    ]);
  });
});

describe("step keys", () => {
  it("makes a template-safe key from a Swedish name", () => {
    expect(slugifyKey("Sammanfatta beslut")).toBe("sammanfatta_beslut");
    expect(slugifyKey("Läs & strukturera handlingarna!")).toBe("las_strukturera_handlingarna");
    expect(slugifyKey("2 steg")).toBe("steg_2_steg");
    expect(slugifyKey("   ")).toBe("steg");
  });

  it("numbers a key that is taken", () => {
    expect(uniqueKey("Inledning", ["intro"])).toBe("inledning");
    expect(uniqueKey("Inledning", ["inledning", "inledning_2"])).toBe("inledning_3");
  });
});

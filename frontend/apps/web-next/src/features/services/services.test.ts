import { describe, expect, it } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { spaceServices } from "./services";

describe("spaceServices", () => {
  it("sorts by name with the collator it is given (å, ä, ö after z in Swedish)", () => {
    const space = makeSpace({
      services: ["Översättning", "Klassning", "Ärendetyp"].map((name, index) => ({
        id: `service-${index}`,
        name
      }))
    });
    expect(spaceServices(space, new Intl.Collator("sv").compare).map((s) => s.name)).toEqual([
      "Klassning",
      "Ärendetyp",
      "Översättning"
    ]);
  });
});

import { ENTRY_AREAS, ENTRY_TYPES } from "@eneo/whats-new";
import { describe, expect, it } from "vitest";
import { areaLabel, labelFor, typeClass, typeLabel } from "./labels";

describe("what's new labels", () => {
  it("cover every entry type in the schema", () => {
    expect(Object.keys(typeLabel).sort()).toEqual([...ENTRY_TYPES].sort());
    expect(Object.keys(typeClass).sort()).toEqual([...ENTRY_TYPES].sort());
  });

  it("cover every area in the schema", () => {
    expect(Object.keys(areaLabel).sort()).toEqual([...ENTRY_AREAS].sort());
  });

  it("fall back to the raw value for a vocabulary this build does not know", () => {
    expect(labelFor(areaLabel, "reports" as never)).toBe("reports");
  });
});

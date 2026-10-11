import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { securityClassName, securityClassStanding } from "./flowClassificationNames";

// An organisation names and orders its own classes; these are one such set.
const classes = [
  { name: "Öppen", security_level: 1 },
  { name: "Intern", security_level: 2 },
  { name: "Konfidentiell", security_level: 3 },
  { name: "Sekretess", security_level: 4 }
];

describe("securityClassName", () => {
  it("is the name the organisation gave the level", () => {
    expect(securityClassName(classes, 3)).toBe("Konfidentiell");
  });

  it("falls back to the bare level when no class has it, never to an invented name", () => {
    expect(securityClassName(classes, 7)).toBe(m.flow_classification_unnamed_level({ level: "7" }));
    expect(securityClassName([], 2)).toBe(m.flow_classification_unnamed_level({ level: "2" }));
  });
});

describe("securityClassStanding", () => {
  it("places a level among the organisation's classes, however many it has", () => {
    expect(securityClassStanding(classes, 4)).toBe("highest");
    expect(securityClassStanding(classes, 3)).toBe("between");
    expect(securityClassStanding(classes, 2)).toBe("between");
    expect(securityClassStanding(classes, 1)).toBe("lowest");
    // Level 3 is the top of a three-class organisation and the middle of this one.
    expect(securityClassStanding(classes.slice(0, 3), 3)).toBe("highest");
  });

  it("says nothing when there is nothing to compare with", () => {
    expect(securityClassStanding([], 2)).toBeNull();
    expect(securityClassStanding(classes.slice(0, 1), 1)).toBeNull();
  });
});

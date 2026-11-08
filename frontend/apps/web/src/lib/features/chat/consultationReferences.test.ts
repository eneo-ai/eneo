import { describe, expect, it } from "vitest";
import { specialistsByReference } from "./consultationReferences";

describe("specialistsByReference", () => {
  it("names the specialist whose consultation holds each reference", () => {
    const map = specialistsByReference([
      { assistant_name: "Coffee", references: [{ id: "a1" }, { id: "a2" }] },
      { assistant_name: "Outdoors", references: [{ id: "b1" }] }
    ]);

    expect(map.get("a2")).toBe("Coffee");
    expect(map.get("b1")).toBe("Outdoors");
    expect(map.has("own-search")).toBe(false);
  });

  it("keeps the first specialist when two consultations share a reference", () => {
    const map = specialistsByReference([
      { assistant_name: "Coffee", references: [{ id: "shared" }] },
      { assistant_name: "Outdoors", references: [{ id: "shared" }] }
    ]);

    expect(map.get("shared")).toBe("Coffee");
  });

  it("is empty for answers without consultations", () => {
    expect(specialistsByReference(undefined).size).toBe(0);
    expect(specialistsByReference([{ assistant_name: "Coffee", references: null }]).size).toBe(0);
  });
});

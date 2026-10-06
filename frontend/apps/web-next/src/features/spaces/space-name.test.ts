import { describe, expect, it } from "vitest";
import { spaceDisplayName } from "./space-name";

const t = (key: string) => (key === "organization_space" ? "Organisationsyta" : "Personlig");

describe("spaceDisplayName", () => {
  it("translates the organisation and personal spaces, keeps the others' names", () => {
    expect(
      spaceDisplayName({ name: "Organization space", personal: false, organization: true }, t)
    ).toBe("Organisationsyta");
    expect(
      spaceDisplayName({ name: "Personal space", personal: true, organization: false }, t)
    ).toBe("Personlig");
    expect(spaceDisplayName({ name: "Upphandling", personal: false, organization: false }, t)).toBe(
      "Upphandling"
    );
  });
});

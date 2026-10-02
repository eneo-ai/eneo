import { describe, expect, it } from "vitest";
import { displayPartnerName } from "./partner-name";

const t = (key: string) => (key === "personal_assistant" ? "Personlig assistent" : key);

describe("displayPartnerName", () => {
  it("calls the personal space's default assistant the personal assistant, whatever its row is named", () => {
    expect(
      displayPartnerName({ type: "default-assistant", name: "Default", personalSpace: true }, t)
    ).toBe("Personlig assistent");
    expect(
      displayPartnerName({ type: "default-assistant", name: "Eneo", personalSpace: true }, t)
    ).toBe("Personlig assistent");
  });

  it("keeps the given name for every other partner, including another space's default assistant", () => {
    expect(
      displayPartnerName({ type: "default-assistant", name: "Organisationsassistenten" }, t)
    ).toBe("Organisationsassistenten");
    expect(
      displayPartnerName({ type: "default-assistant", name: "Default", personalSpace: false }, t)
    ).toBe("Default");
    expect(displayPartnerName({ type: "assistant", name: "Default", personalSpace: true }, t)).toBe(
      "Default"
    );
    expect(displayPartnerName({ type: "group-chat", name: "Inköpsrådet" }, t)).toBe("Inköpsrådet");
  });
});

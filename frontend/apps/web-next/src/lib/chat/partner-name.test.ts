import { describe, expect, it } from "vitest";
import { displayPartnerName } from "./partner-name";

const t = (key: string, values?: Record<string, string>) =>
  key === "personal_assistant"
    ? "Personlig assistent"
    : key === "space_default_assistant_named"
      ? `Assistent för ${values?.space}`
      : key === "space_default_assistant"
        ? "Ytans assistent"
        : key;

describe("displayPartnerName", () => {
  it("calls the personal space's default assistant the personal assistant, whatever its row is named", () => {
    expect(
      displayPartnerName({ type: "default-assistant", name: "Default", personalSpace: true }, t)
    ).toBe("Personlig assistent");
    expect(
      displayPartnerName({ type: "default-assistant", name: "Eneo", personalSpace: true }, t)
    ).toBe("Personlig assistent");
  });

  it("names a shared space's unrenamed default assistant after its space", () => {
    expect(
      displayPartnerName(
        { type: "default-assistant", name: "Default", personalSpace: false, spaceName: "Ekonomi" },
        t
      )
    ).toBe("Assistent för Ekonomi");
    expect(
      displayPartnerName({ type: "default-assistant", name: "Default", personalSpace: false }, t)
    ).toBe("Ytans assistent");
  });

  it("keeps the given name for every other partner, including a renamed default assistant", () => {
    expect(
      displayPartnerName(
        { type: "default-assistant", name: "Organisationsassistenten", spaceName: "Ekonomi" },
        t
      )
    ).toBe("Organisationsassistenten");
    expect(displayPartnerName({ type: "assistant", name: "Default", personalSpace: true }, t)).toBe(
      "Default"
    );
    expect(displayPartnerName({ type: "group-chat", name: "Inköpsrådet" }, t)).toBe("Inköpsrådet");
  });
});

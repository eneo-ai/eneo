import { describe, expect, it } from "vitest";
import { asString, hostOf } from "./metadata";

describe("asString", () => {
  it("keeps non-blank strings only", () => {
    expect(asString("Avsnitt 4")).toBe("Avsnitt 4");
    expect(asString("  ")).toBeNull();
    expect(asString(4)).toBeNull();
    expect(asString(undefined)).toBeNull();
  });
});

describe("hostOf", () => {
  it("names the host of web addresses only", () => {
    expect(hostOf("https://www.riksdagen.se/lou?x=1")).toBe("riksdagen.se");
    expect(hostOf("http://intranat.kommun.se")).toBe("intranat.kommun.se");
    expect(hostOf("file:///policy.pdf")).toBeNull();
    expect(hostOf("eneo://collection/1")).toBeNull();
    expect(hostOf("https://")).toBeNull();
    expect(hostOf(undefined)).toBeNull();
  });
});

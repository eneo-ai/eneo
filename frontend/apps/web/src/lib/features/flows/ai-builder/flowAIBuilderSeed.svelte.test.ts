import { beforeEach, describe, expect, it } from "vitest";

import { consumeAIBuilderSeed, writeAIBuilderSeed } from "./flowAIBuilderSeed";

const SPACE_A = "space-a";
const SPACE_B = "space-b";

describe("flowAIBuilderSeed", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("round-trips a prompt and consumes it exactly once", () => {
    writeAIBuilderSeed(SPACE_A, "Sammanfatta uppladdade rapporter");
    expect(consumeAIBuilderSeed(SPACE_A)).toBe("Sammanfatta uppladdade rapporter");
    expect(consumeAIBuilderSeed(SPACE_A)).toBeNull();
  });

  it("scopes seeds per space", () => {
    writeAIBuilderSeed(SPACE_A, "För space A");
    expect(consumeAIBuilderSeed(SPACE_B)).toBeNull();
    expect(consumeAIBuilderSeed(SPACE_A)).toBe("För space A");
  });

  it("trims the prompt and ignores whitespace-only seeds", () => {
    writeAIBuilderSeed(SPACE_A, "  Granska remissvar  ");
    expect(consumeAIBuilderSeed(SPACE_A)).toBe("Granska remissvar");

    writeAIBuilderSeed(SPACE_A, "   ");
    expect(consumeAIBuilderSeed(SPACE_A)).toBeNull();
  });
});

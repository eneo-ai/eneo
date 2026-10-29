import { describe, expect, it } from "vitest";
import { parseInstructionReferences, serializeReference } from "@eneo/skill-instructions";
import fixtures from "../../../../../packages/skill-instructions/fixtures.json";

describe("instruction reference text contract", () => {
  for (const fixture of fixtures)
    it(fixture.name, () => {
      if (fixture.error) {
        expect(() => parseInstructionReferences(fixture.text)).toThrow();
        return;
      }
      const references = parseInstructionReferences(fixture.text);
      expect(references.map((item) => item.target)).toEqual(fixture.targets);
      for (const reference of references) {
        expect(fixture.text.slice(reference.start, reference.end)).toBe(reference.text);
        expect(
          parseInstructionReferences(serializeReference(reference.label, reference.target))[0]
            ?.target
        ).toEqual(reference.target);
      }
    });
});

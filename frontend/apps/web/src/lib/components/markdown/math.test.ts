import { Marked } from "marked";
import { describe, expect, it } from "vitest";
import { mathExtensions, promoteDisplayMath } from "./math.js";

const plain = new Marked({ gfm: true, breaks: true });
const math = new Marked({ gfm: true, breaks: true, extensions: mathExtensions });

function fastest(marked: Marked, source: string) {
  let best = Infinity;
  for (let run = 0; run < 3; run++) {
    const started = performance.now();
    promoteDisplayMath(marked.lexer(source));
    best = Math.min(best, performance.now() - started);
  }
  return best;
}

// Measured against marked alone, so a slow runner does not fail the test: a
// search that starts over at each token is tens to hundreds of times slower
// at this size.
describe("math lexing time", () => {
  const answers = {
    "many paragraphs": "Klicka på **Arkiv** och _Alternativ_ <b>nu</b>!\n\n".repeat(8000),
    "many inline tokens without math": "a_ b! c< ".repeat(8000),
    "many empty fences": "$$\n$$\n\n".repeat(8000),
    "many unclosed openers": "\\(a \\[b ".repeat(8000)
  };

  for (const [name, source] of Object.entries(answers)) {
    it(`grows with the answer, as marked does: ${name}`, () => {
      expect(fastest(math, source)).toBeLessThan(5 * fastest(plain, source) + 50);
    });
  }

  it("reads a long run of unclosed openers as text", () => {
    const tokens = math.lexer("\\(a ".repeat(20000));
    expect(JSON.stringify(tokens)).not.toContain("eneoMath");
  });
});

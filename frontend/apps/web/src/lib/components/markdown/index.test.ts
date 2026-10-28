import { Marked, type Token } from "marked";
import { describe, expect, it } from "vitest";
import { eneoMarkdownLexer } from "./index.js";

const plain = new Marked({ gfm: true, breaks: true });
const eneo = eneoMarkdownLexer();

function types(tokens: Token[]): string[] {
  return tokens.flatMap((token) => [
    token.type,
    ...("tokens" in token && token.tokens ? types(token.tokens) : [])
  ]);
}

describe("eneoMarkdownLexer", () => {
  it("finds references and mentions inside a sentence", () => {
    const found = types(eneo.lex('Se <inref id="aaaaaaaa"/> och [[@Anna]] nu.'));
    expect(found).toContain("eneoInref");
    expect(found).toContain("eneoMention");
  });

  it("ends a paragraph at a reference line and at a fence", () => {
    const tokens = eneo.lex('Text\n<inref id="aaaaaaaa"/>\nMer\n$$\nx\n$$');
    expect(tokens.map((token) => `${token.type}:${token.raw.trim()}`)).toEqual([
      "paragraph:Text",
      'eneoInref:<inref id="aaaaaaaa"/>',
      "paragraph:Mer",
      "eneoMath:$$\nx\n$$"
    ]);
  });

  it("does not read a fence into a setext heading", () => {
    const tokens = eneo.lex("Rubrik\n$$\nx\n$$\n===");
    expect(tokens.map((token) => token.type)).toEqual(["paragraph", "eneoMath", "paragraph"]);
  });

  it("keeps code-span dollars out of strikethrough math detection", () => {
    const source = "~~`$x`~~ + `y$`";
    expect(eneo.lex(source)).toEqual(plain.lexer(source));
    expect(types(eneo.lex(source))).toContain("del");
    expect(types(eneo.lex(source))).not.toContain("eneoMath");
  });

  it("keeps formula tildes inside strikethrough", () => {
    expect(types(eneo.lex("~~$x~~y$~~"))).toEqual(["paragraph", "del", "eneoMath"]);
  });
});

function fastest(lex: (source: string) => unknown, source: string) {
  let best = Infinity;
  for (let run = 0; run < 3; run++) {
    const started = performance.now();
    lex(source);
    best = Math.min(best, performance.now() - started);
  }
  return best;
}

// Measured against marked alone, so a slow runner does not fail the test: a
// search that starts over at each token is tens to hundreds of times slower
// at this size. The time limit only stops a hang.
describe("lexing time", () => {
  const answers = {
    "many paragraphs": "Klicka på **Arkiv** och _Alternativ_ <b>nu</b>!\n\n".repeat(8000),
    "many inline tokens without math": "a_ b! c< ".repeat(8000),
    "many lines in one paragraph": "Klicka på Arkiv och sedan Alternativ\n".repeat(8000),
    "many dollars that are not math": "Det kostar 5 $ eller 6 $ nu. ".repeat(16000),
    "many dollars before numbers": "Det kostar $5 eller $6 nu. ".repeat(16000),
    "many empty fences": "$$\n$$\n\n".repeat(8000),
    "many fences without blank lines": "a\n$$\nx\n$$\n".repeat(4000),
    "many tag lines without blank lines": "a\n<b>x</b>\n".repeat(4000),
    "many unclosed openers": "\\(a \\[b ".repeat(8000),
    "many formulas in emphasis": "*$a*b$* och **c** ~~$d~e$~~ ".repeat(8000)
  };

  for (const [name, source] of Object.entries(answers)) {
    it(`grows with the answer, as marked does: ${name}`, { timeout: 30_000 }, () => {
      expect(fastest(eneo.lex, source)).toBeLessThan(
        5 * fastest((text) => plain.lexer(text), source) + 50
      );
    });
  }

  it("reads a long run of unclosed openers as text", () => {
    const tokens = eneo.lex("\\(a ".repeat(20000));
    expect(JSON.stringify(tokens)).not.toContain("eneoMath");
  });
});

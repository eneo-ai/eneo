import { describe, expect, it } from "vitest";
import { documentMarkdown, withFinalNewline } from "./extensions";

// What the document tools write must come back out as the same document.
const markdown = documentMarkdown();
const roundTrip = (source: string) => withFinalNewline(markdown.serialize(markdown.parse(source)));
const types = (source: string) =>
  (markdown.parse(source).content ?? []).map((node) => node.type as string);

describe("a document's Markdown round-trips through the editor model", () => {
  it("keeps headings, emphasis and lists", () => {
    const source =
      "# Plan\n\n## Fas ett\n\n### Mål\n\nEn **viktig** och *lugn* start med ~~ändrat~~ `kod`.\n\n- Ett\n- Två\n  - Två b\n\n3. Tre\n4. Fyra\n";
    expect(roundTrip(source)).toBe(source);
  });

  it("keeps task lists", () => {
    const source = "- [ ] Att göra\n- [x] Klart\n";
    expect(types(source)).toEqual(["taskList"]);
    expect(roundTrip(source)).toBe(source);
  });

  it("keeps tables", () => {
    const source = "| Namn | Antal |\n| --- | ---: |\n| Alfa | 1 |\n| Beta | 22 |\n";
    expect(types(source)).toEqual(["table"]);
    // Columns come back padded to one width; the cells are the same.
    expect(roundTrip(source)).toMatch(/\| Alfa \| 1\s*\|\n\| Beta \| 22\s*\|\n$/);
    expect(roundTrip(source)).toMatch(/^\n*\| Namn \| Antal \|\n\| -+ \| -+: \|\n/);
  });

  it("keeps fenced code with its language, and quotes", () => {
    const source = "```python\nprint(1)\n```\n\n> Ett citat\n>\n> i två stycken\n";
    expect(types(source)).toEqual(["codeBlock", "blockquote"]);
    expect(roundTrip(source)).toBe(source);
  });

  it("keeps web and mail links", () => {
    const source = "Se [sidan](https://example.se/a) eller [skriv](mailto:a@b.se).\n";
    expect(roundTrip(source)).toBe(source);
  });

  it("keeps an image handle and its caption as written", () => {
    const source = '![Figur 1](eneo-file:0123456789abcdef0123456789abcdef "Bildtext")\n';
    // An image on a line of its own stands as a block of its own.
    const [image] = markdown.parse(source).content ?? [];
    expect(image).toMatchObject({
      type: "image",
      attrs: {
        src: "eneo-file:0123456789abcdef0123456789abcdef",
        alt: "Figur 1",
        title: "Bildtext"
      }
    });
    expect(roundTrip(source)).toBe(source);
  });

  it("keeps a page break as the comment the tools understand", () => {
    const source = "Före\n\n<!-- pagebreak -->\n\nEfter\n";
    expect(types(source)).toEqual(["paragraph", "pageBreak", "paragraph"]);
    expect(roundTrip(source)).toBe(source);
  });

  it("shows HTML as text, never as markup", () => {
    const doc = markdown.parse("<script>alert(1)</script>\n\nEn <b>fet</b> rad\n");
    const everyType = new Set<string>();
    const walk = (node: { type?: string; content?: unknown[] }) => {
      if (node.type) everyType.add(node.type);
      (node.content as { type?: string; content?: unknown[] }[] | undefined)?.forEach(walk);
    };
    walk(doc);
    expect([...everyType].sort()).toEqual(["doc", "paragraph", "text"]);
    expect(JSON.stringify(doc)).toContain("<script>alert(1)</script>");
    expect(JSON.stringify(doc)).toContain("<b>fet</b>");
  });
});

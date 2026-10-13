import { describe, expect, test } from "bun:test";
import { highlight } from "../../src/views/kit/highlight";

describe("highlight", () => {
  test("JavaScript tokens get their classes and nothing in the text is lost", () => {
    const html = highlight("const total = new Decimal('0.1').plus(2);", "javascript");
    expect(html).toContain('<span class="hljs-keyword">const</span>');
    expect(html).toContain('<span class="hljs-string">&#x27;0.1&#x27;</span>');
    expect(html).toContain('<span class="hljs-number">2</span>');
    expect(html.replace(/<[^>]+>/g, "").replace(/&#x27;/g, "'")).toBe(
      "const total = new Decimal('0.1').plus(2);",
    );
  });

  test("JSON keys and values are told apart", () => {
    const html = highlight('{"ränta": 0.035, "år": "tio"}', "json");
    expect(html).toContain('<span class="hljs-attr">&quot;ränta&quot;</span>');
    expect(html).toContain('<span class="hljs-number">0.035</span>');
    expect(html).toContain('<span class="hljs-string">&quot;tio&quot;</span>');
  });

  test("text without a language is escaped, never marked up", () => {
    expect(highlight("<b>1 & 2</b>")).toBe("&lt;b&gt;1 &amp; 2&lt;/b&gt;");
  });

  test("code the grammar rejects still comes back whole", () => {
    const broken = "for (;; { ]";
    expect(highlight(broken, "javascript").replace(/<[^>]+>/g, "")).toBe(broken);
  });
});

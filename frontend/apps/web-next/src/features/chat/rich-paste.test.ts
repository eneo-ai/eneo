// @vitest-environment jsdom
import { clipboardHasFormattedText, htmlToMarkdown } from "@eneo/rich-paste";
import { describe, expect, it } from "vitest";

describe("formatted text pasted into the composer", () => {
  it("keeps headings, emphasis and link addresses", () => {
    const html = `
      <h2><b>Riktlinje</b> för inköp</h2>
      <p>Läs <a href="https://example.org/policy (1)">policyn</a> och
        <strong>följ </strong>den, se <a href="https://example.org/">https://example.org</a>.</p>
      <p><a href="/relativ">Intern länk</a> och <a href="javascript:alert(1)">skript</a></p>`;

    expect(htmlToMarkdown(html)).toBe(
      [
        "## Riktlinje för inköp",
        "Läs [policyn](https://example.org/policy%20%281%29) och **följ** den, se https://example.org/.",
        "Intern länk och skript"
      ].join("\n\n")
    );
  });

  it("writes nested lists and tables", () => {
    const html = `
      <ul><li>Ett<ol start="3"><li>Under</li><li><p>Två rader</p><p>här</p></li></ol></li><li>Två</li></ul>
      <table><tr><th>Namn</th><th>Värde</th></tr><tr><td>a | b</td><td><em>1</em></td></tr></table>`;

    expect(htmlToMarkdown(html)).toBe(
      [
        "- Ett\n    3. Under\n    4. Två rader\n        här\n- Två",
        "| Namn | Värde |\n| --- | --- |\n| a \\| b | *1* |"
      ].join("\n\n")
    );
  });

  it("reads a list as Word writes it", () => {
    const html = `
      <p class="MsoListParagraph" style="text-indent:-18pt;mso-list:l0 level1 lfo1"><!--[if !supportLists]--><span
        style="font-family:Symbol"><span style="mso-list:Ignore">·<span style="font:7pt 'Times New Roman'">&nbsp;&nbsp;
        </span></span></span><!--[endif]-->Första<o:p></o:p></p>
      <p class="MsoListParagraph" style="mso-list:l0 level2 lfo1"><span style="mso-list:Ignore">a)<span>&nbsp;</span></span>Andra</p>
      <p class="MsoNormal">Efter listan</p>`;

    expect(htmlToMarkdown(html)).toBe("- Första\n    1. Andra\n\nEfter listan");
  });

  it("takes emphasis from the style where an editor wraps everything in <b>", () => {
    const html = `<b style="font-weight:normal" id="docs-internal-guid-1"><p><span
      style="font-weight:700">Viktigt</span><span style="font-weight:400"> och </span><span
      style="font-style:italic">kursivt</span></p></b>`;

    expect(htmlToMarkdown(html)).toBe("**Viktigt** och *kursivt*");
  });

  it("leaves text without formatting to the plain-text paste", () => {
    const html = `<meta charset="utf-8"><div style="color:#ccc"><span>const a = 1;</span><br><span>a | b</span></div>`;

    expect(htmlToMarkdown(html)).toBeNull();
  });

  it("tells copied text from a copied picture", () => {
    const clipboard = (html: string) => ({ getData: () => html });

    expect(clipboardHasFormattedText(clipboard("<p>Text</p><img src='x.png'>"))).toBe(true);
    expect(clipboardHasFormattedText(clipboard("<img src='x.png' alt='Bild'>"))).toBe(false);
    expect(clipboardHasFormattedText(clipboard(""))).toBe(false);
  });
});

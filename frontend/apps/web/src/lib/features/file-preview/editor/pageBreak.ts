import { Node } from "@tiptap/core";
// The markdown hooks on extensions come from this module's type augmentation.
import "@tiptap/markdown";

export type PageBreakOptions = {
  /** What the break is called where the rule is read aloud or hovered. */
  label: string;
};

/**
 * A page break, which the document tools write as `<!-- pagebreak -->` and
 * honour in Word and PDF. Read in Eneo it is a rule; it goes back out as the
 * same comment.
 */
export const PageBreak = Node.create<PageBreakOptions>({
  name: "pageBreak",
  group: "block",
  atom: true,
  selectable: true,

  addOptions() {
    return { label: "" };
  },

  parseHTML() {
    return [{ tag: "div[data-page-break]" }];
  },

  renderHTML() {
    return [
      "div",
      {
        "data-page-break": "",
        role: "separator",
        "aria-label": this.options.label,
        title: this.options.label,
        class: "page-break"
      }
    ];
  },

  markdownTokenizer: {
    name: "pageBreak",
    level: "block",
    start: (src) => src.indexOf("<!--"),
    tokenize: (src) => {
      const match = /^<!--\s*pagebreak\s*-->[ \t]*(?:\n+|$)/i.exec(src);
      return match ? { type: "pageBreak", raw: match[0] } : undefined;
    }
  },

  parseMarkdown: () => ({ type: "pageBreak" }),

  renderMarkdown: () => "<!-- pagebreak -->"
});

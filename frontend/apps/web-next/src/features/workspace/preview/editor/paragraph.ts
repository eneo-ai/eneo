import { Paragraph } from "@tiptap/extension-paragraph";

/**
 * A paragraph whose Markdown is only an image keeps the image inside it.
 *
 * TipTap's paragraph lifts a lone image out to stand as a block of its own,
 * which suits its block image; the document's image is inline (see
 * `EneoImage`), and a block-level inline node is not a valid document.
 */
export const DocumentParagraph = Paragraph.extend({
  parseMarkdown(token, helpers) {
    const tokens = token.tokens ?? [];
    const loneImage = tokens.length === 1 && tokens[0]?.type === "image";
    if (!loneImage && this.parent) return this.parent(token, helpers);
    return helpers.createNode("paragraph", undefined, helpers.parseInline(tokens));
  }
});

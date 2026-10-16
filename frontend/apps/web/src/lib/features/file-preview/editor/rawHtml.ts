import { Extension } from "@tiptap/core";
import "@tiptap/markdown";

// A tag or comment, as the inline tokenizer takes it off the front of the text.
const TAG = /^(?:<!--[\s\S]*?-->|<\/?[A-Za-z][\w-]*(?:\s[^<>]*)?\/?>)/;

// Nothing to show (an empty token) is no node at all.
const asText = (token: { raw?: string }) => {
  const text = String(token.raw ?? "").replace(/\n+$/, "");
  return text ? [{ type: "text", text }] : [];
};

/**
 * A block of HTML in a document (a line that opens with a tag) is a paragraph
 * of the text it is, never markup: the document tools treat it so, and a
 * document is the model's writing.
 */
const RawHtmlBlock = Extension.create({
  name: "rawHtmlBlock",
  markdownTokenName: "html",

  parseMarkdown: (token) => {
    const content = asText(token);
    if (content.length === 0) return [];
    return token.block ? { type: "paragraph", content } : content;
  }
});

/**
 * A tag inside a line is taken as text before Markdown's own HTML rules see
 * it. Its token is not an HTML token on purpose: those the Markdown
 * extension pairs up and parses as markup.
 */
const RawHtmlTag = Extension.create({
  name: "rawHtmlTag",

  markdownTokenizer: {
    name: "rawHtmlTag",
    level: "inline",
    start: (src) => src.indexOf("<"),
    tokenize: (src) => {
      const match = TAG.exec(src);
      return match ? { type: "rawHtmlTag", raw: match[0], text: match[0] } : undefined;
    }
  },

  parseMarkdown: (token) => asText(token)
});

/** HTML in a document is shown as the text it is. */
export const RawHtml = [RawHtmlBlock, RawHtmlTag];

import { marked, type TokenizerAndRendererExtension } from "marked";
import type { IntricInrefToken, IntricMentionToken } from "./CustomComponents";

export { default as Markdown } from "./Markdown.svelte";
export { sanitizeImageSrc, sanitizeLinkHref } from "./sanitizeUrl.js";
export {
  type CustomRenderers as MarkdownCustomRenderingOptions,
  type IntricInrefCustomComponentProps,
  type IntricMentionCustomComponentProps
} from "./CustomComponents";

export function intricMarkdownLexer() {
  const intricInrefRule = /^<inref\s+id="([^"]+)"(?:\s*\/?>|\s*><\/inref>)/;
  // Sometimes the llm returns references on their own line with whitespaces before
  //  -> In that case we render as a block like element
  const intricInrefBlockRule = /^[\n\r\s]+<inref\s+id="([^"]+)"(?:\s*\/?>|\s*><\/inref>)/;
  // Mention rule for [[@something]] pattern
  const intricMentionRule = /^\[\[@(.*?)\]\]/;

  const intricInref: TokenizerAndRendererExtension = {
    name: "intricInref",
    level: "inline",
    start(src: string) {
      const idx = src.indexOf("<inref");
      return idx;
    },
    tokenizer(src: string): IntricInrefToken | undefined {
      const match = src.match(intricInrefRule);

      if (match) {
        const id = match[1];

        return {
          type: "intricInref",
          level: "inline",
          raw: match[0],
          id
        };
      }
    }
  };

  const intricInrefBlock: TokenizerAndRendererExtension = {
    name: "intricInref",
    level: "block",
    start(src: string) {
      const idx = src.indexOf("\n<");
      return idx;
    },
    tokenizer(src: string): IntricInrefToken | undefined {
      const match = src.match(intricInrefBlockRule);

      if (match) {
        const id = match[1];

        return {
          type: "intricInref",
          level: "block",
          raw: match[0],
          id
        };
      }
    }
  };

  const intricMention: TokenizerAndRendererExtension = {
    name: "intricMention",
    level: "inline",
    start(src: string) {
      const idx = src.indexOf("[[@");
      return idx;
    },
    tokenizer(src: string): IntricMentionToken | undefined {
      const match = src.match(intricMentionRule);

      if (match) {
        return {
          type: "intricMention",
          level: "inline",
          handle: `@${match[1]}`,
          raw: match[0]
        };
      }
    }
  };

  // Configure marked.js to preserve whitespace
  marked.use({
    extensions: [intricInref, intricInrefBlock, intricMention],
    // Preserve whitespace and newlines entered by the user
    breaks: true,
    gfm: true
  });

  return {
    lex(source: string) {
      const tokens = marked.lexer(source);
      return tokens;
    }
  };
}

import { marked, type TokenizerAndRendererExtension } from "marked";
import type { EneoInrefToken, EneoMentionToken } from "./CustomComponents";

export { default as Markdown } from "./Markdown.svelte";
export { sanitizeImageSrc, sanitizeLinkHref } from "./sanitizeUrl.js";
export {
  type CustomRenderers as MarkdownCustomRenderingOptions,
  type EneoInrefCustomComponentProps,
  type EneoMentionCustomComponentProps
} from "./CustomComponents";

export function eneoMarkdownLexer() {
  const eneoInrefRule = /^<inref\s+id="([^"]+)"(?:\s*\/?>|\s*><\/inref>)/;
  // Sometimes the llm returns references on their own line with whitespaces before
  //  -> In that case we render as a block like element
  const eneoInrefBlockRule = /^[\n\r\s]+<inref\s+id="([^"]+)"(?:\s*\/?>|\s*><\/inref>)/;
  // Mention rule for [[@something]] pattern
  const eneoMentionRule = /^\[\[@(.*?)\]\]/;

  const eneoInref: TokenizerAndRendererExtension = {
    name: "eneoInref",
    level: "inline",
    start(src: string) {
      const idx = src.indexOf("<inref");
      return idx;
    },
    tokenizer(src: string): EneoInrefToken | undefined {
      const match = src.match(eneoInrefRule);

      if (match) {
        const id = match[1];

        return {
          type: "eneoInref",
          level: "inline",
          raw: match[0],
          id
        };
      }
    }
  };

  const eneoInrefBlock: TokenizerAndRendererExtension = {
    name: "eneoInref",
    level: "block",
    start(src: string) {
      const idx = src.indexOf("\n<");
      return idx;
    },
    tokenizer(src: string): EneoInrefToken | undefined {
      const match = src.match(eneoInrefBlockRule);

      if (match) {
        const id = match[1];

        return {
          type: "eneoInref",
          level: "block",
          raw: match[0],
          id
        };
      }
    }
  };

  const eneoMention: TokenizerAndRendererExtension = {
    name: "eneoMention",
    level: "inline",
    start(src: string) {
      const idx = src.indexOf("[[@");
      return idx;
    },
    tokenizer(src: string): EneoMentionToken | undefined {
      const match = src.match(eneoMentionRule);

      if (match) {
        return {
          type: "eneoMention",
          level: "inline",
          handle: `@${match[1]}`,
          raw: match[0]
        };
      }
    }
  };

  // Configure marked.js to preserve whitespace
  marked.use({
    extensions: [eneoInref, eneoInrefBlock, eneoMention],
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

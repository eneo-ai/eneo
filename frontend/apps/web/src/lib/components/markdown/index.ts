import { Marked, type TokenizerAndRendererExtension } from "marked";
import type { EneoFileToken, EneoInrefToken, EneoMentionToken } from "./CustomComponents";

export { default as Markdown } from "./Markdown.svelte";
export { sanitizeImageSrc, sanitizeLinkHref } from "./sanitizeUrl.js";
export {
  type CustomRenderers as MarkdownCustomRenderingOptions,
  type EneoFileCustomComponentProps,
  type EneoInrefCustomComponentProps,
  type EneoMentionCustomComponentProps
} from "./CustomComponents";

export function eneoMarkdownLexer({
  breaks = true,
  fileNames = []
}: {
  breaks?: boolean;
  /** Names of the conversation's files; each mention of one becomes a file token. */
  fileNames?: string[];
} = {}) {
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

  // A file is mentioned by its exact name. The longest name is tried first, so
  // "Plan (v2).docx" is not read as a mention of "Plan".
  const names = [...new Set(fileNames)].filter(Boolean).sort((a, b) => b.length - a.length);
  const eneoFile: TokenizerAndRendererExtension = {
    name: "eneoFile",
    level: "inline",
    start(src: string) {
      let first = -1;
      for (const name of names) {
        const idx = src.indexOf(name);
        if (idx !== -1 && (first === -1 || idx < first)) first = idx;
      }
      return first;
    },
    tokenizer(src: string): EneoFileToken | undefined {
      const name = names.find((candidate) => src.startsWith(candidate));
      if (name) return { type: "eneoFile", level: "inline", raw: name, name };
    }
  };

  // A private instance: registering the extensions on the global `marked`
  // appended them once per Markdown component mount (marked does not
  // deduplicate), so lexing got slower with every message rendered.
  const instance = new Marked({
    extensions: [eneoInref, eneoInrefBlock, eneoMention, ...(names.length ? [eneoFile] : [])],
    // Chat text keeps the line breaks as typed; a document's single line
    // breaks are soft, as in the Markdown file it is.
    breaks,
    gfm: true
  });

  return {
    lex(source: string) {
      return instance.lexer(source);
    }
  };
}

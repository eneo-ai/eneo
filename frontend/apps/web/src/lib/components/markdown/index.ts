import { Lexer, Marked, Tokenizer, type Token, type TokenizerAndRendererExtension } from "marked";
import type { EneoFileToken, EneoInrefToken, EneoMentionToken } from "./CustomComponents";
import { hideMathDelimiters, mathExtensions, promoteDisplayMath, startsMathFence } from "./math.js";

export { default as Markdown } from "./Markdown.svelte";
export { sanitizeImageSrc, sanitizeLinkHref, sanitizeWebHref } from "./sanitizeUrl.js";
export { fileHandleId } from "./FileImageContext.js";
export {
  type CustomRenderers as MarkdownCustomRenderingOptions,
  type EneoFileCustomComponentProps,
  type EneoInrefCustomComponentProps,
  type EneoMentionCustomComponentProps
} from "./CustomComponents";

const blankLine = / *(?:\n|$)/y;

/**
 * Where the next block of an extension starts, for marked to end the paragraph
 * there. marked asks before each paragraph, with the rest of the answer, so
 * one search serves both block extensions and ends at the first line one of
 * them starts on, or at a blank line, where the paragraph ends anyway. A search
 * per extension would read on past the other's starts, once per paragraph.
 */
function blockStart(src: string) {
  for (let end = src.indexOf("\n"); end !== -1; end = src.indexOf("\n", end + 1)) {
    if (src[end + 1] === "<") return end;
    blankLine.lastIndex = end + 1;
    if (blankLine.test(src)) return -1;
    if (startsMathFence(src, end + 1)) return end + 1;
  }
  return -1;
}

type InlineText = { src: string; forDelimiters?: string };

/**
 * Keeps the inline text marked is lexing, so emphasis and strikethrough can
 * look for their end with the delimiters inside formulas hidden, worked out
 * once per text. marked 18 has a hook for this, `emStrongMask`.
 */
class MathAwareLexer extends Lexer {
  inlineTexts: InlineText[] = [];

  override inlineTokens(src: string, tokens?: Token[]) {
    this.inlineTexts.push({ src });
    try {
      return super.inlineTokens(src, tokens);
    } finally {
      this.inlineTexts.pop();
    }
  }
}

function inlineText(tokenizer: Tokenizer) {
  return (tokenizer.lexer as MathAwareLexer).inlineTexts.at(-1);
}

export function eneoMarkdownLexer({
  fileNames = []
}: {
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
    // No `start`: marked's text already ends at every `<`.
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
    start: blockStart,
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
    // No `start`: marked's text already ends at every `[`.
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
    extensions: [
      eneoInref,
      eneoInrefBlock,
      eneoMention,
      ...mathExtensions,
      ...(names.length ? [eneoFile] : [])
    ],
    // Chat text keeps the line breaks as typed.
    breaks: true,
    gfm: true,
    tokenizer: {
      // marked tries a setext heading before each paragraph and reads it on
      // to the next blank line, past where blockStart ends the paragraph. A
      // heading's text is a paragraph, so it ends there too.
      lheading(src) {
        const end = blockStart(src.slice(1));
        return end === -1 ? false : Tokenizer.prototype.lheading.call(this, src.slice(0, end + 1));
      },
      emStrong(src, maskedSrc, prevChar) {
        const text = inlineText(this);
        if (!text || (src[0] !== "*" && src[0] !== "_" && src[0] !== "~")) return false;
        // marked calls emStrong before del. Share its code/link/tag mask with
        // strikethrough so dollars inside code cannot hide a real closing ~~.
        text.forDelimiters ??= hideMathDelimiters(text.src, maskedSrc);
        if (src[0] === "~") return false;
        return Tokenizer.prototype.emStrong.call(this, src, text.forDelimiters, prevChar);
      },
      // marked's own, read where the formulas' delimiters are hidden.
      del(src) {
        const text = inlineText(this);
        if (!text?.forDelimiters || src[0] !== "~") return false;
        const cap = this.rules.inline.del.exec(text.forDelimiters.slice(-src.length));
        if (!cap) return;
        const raw = src.slice(0, cap[0].length);
        const inner = raw.slice(cap[1].length, -cap[1].length);
        return { type: "del", raw, text: inner, tokens: this.lexer.inlineTokens(inner) };
      }
    }
  });

  return {
    lex(source: string) {
      return promoteDisplayMath(new MathAwareLexer(instance.defaults).lex(source));
    }
  };
}

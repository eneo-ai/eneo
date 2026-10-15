/**
 * LaTeX math for the marked lexer: `$…$`, `$$…$$`, `\(…\)`, `\[…\]` and
 * ```math fences. Recognised inside marked, so code spans, fences, indented
 * code and link destinations stay marked's and are never searched. When a
 * `$` is money rather than math is decided by @eneo/markdown-math, shared
 * with web-next; both apps are tested against its cases.json.
 */
import { canCloseDollar, canOpenDollar } from "@eneo/markdown-math";
import type { Token, TokenizerAndRendererExtension } from "marked";
import type { EneoMathToken } from "./CustomComponents";

type InlineMath = { raw: string; text: string; displayDelimiter: boolean };

/**
 * `\(…\)` or `\[…\]`: up to the first unescaped closer. A second opener of
 * the same kind first means this one is text, so a run of unclosed openers is
 * read once rather than once per opener.
 */
function matchBracket(src: string, displayDelimiter: boolean): InlineMath | undefined {
  const [open, close] = displayDelimiter ? ["[", "]"] : ["(", ")"];
  for (let i = 2; i < src.length; i++) {
    if (src[i] !== "\\") continue;
    if (src[i + 1] === open) return;
    if (src[i + 1] === close) {
      const text = src.slice(2, i).trim();
      return text ? { raw: src.slice(0, i + 2), text, displayDelimiter } : undefined;
    }
    i++;
  }
}

/**
 * `$$…$$` as remark-math reads it in web-next: the closing run is as long as
 * the opening one, a run of another length is part of the formula, and a
 * backslash escapes nothing.
 */
function matchDollars(src: string, open: number): InlineMath | undefined {
  for (let i = open; i < src.length;) {
    if (src[i] !== "$") {
      i++;
      continue;
    }
    let run = 0;
    while (src[i + run] === "$") run++;
    if (run === open) {
      const text = src.slice(open, i).trim();
      return text ? { raw: src.slice(0, i + run), text, displayDelimiter: true } : undefined;
    }
    i += run;
  }
}

/** `$…$` on one line; only the first unescaped `$` may close it. */
function matchDollar(src: string, prev: string | undefined): InlineMath | undefined {
  if (!canOpenDollar(prev, src[1])) return;
  for (let i = 1; i < src.length; i++) {
    const char = src[i];
    if (char === "\n") return;
    if (char === "\\") {
      if (src[i + 1] === "\n") return; // a hard break, not an escape
      i++;
      continue;
    }
    if (char === "$") {
      if (!canCloseDollar(src[i - 1], src[i + 1])) return;
      return { raw: src.slice(0, i + 1), text: src.slice(1, i), displayDelimiter: false };
    }
  }
}

function matchInlineMath(src: string, prev: string | undefined): InlineMath | undefined {
  if (src.startsWith("\\(")) return matchBracket(src, false);
  if (src.startsWith("\\[")) return matchBracket(src, true);
  if (!src.startsWith("$")) return;
  let open = 0;
  while (src[open] === "$") open++;
  if (open === 1) return matchDollar(src, prev);
  // remark-math never starts math right after another `$`.
  return prev === "$" ? undefined : matchDollars(src, open);
}

const inlineMath: TokenizerAndRendererExtension = {
  name: "eneoMath",
  level: "inline",
  // Text already ends at every backslash, so only `$` needs a cut. A native
  // search, as marked asks again after each text token.
  start: (src: string) => src.indexOf("$"),
  tokenizer(src: string, tokens: Token[]): EneoMathToken | undefined {
    const match = matchInlineMath(src, tokens.at(-1)?.raw.at(-1));
    if (!match) return;
    return { type: "eneoMath", level: "inline", display: false, ...match };
  }
};

// A `$$` fence, as web-next reads it: `$$` alone on its line, TeX inside
// (blank lines allowed), and a closing line of at least as many `$`. Text
// after the opening `$$`, or a fence never closed, stays in the paragraph,
// where `$$…$$` is read as a formula or left as text.
// The first closing line ends it, even right after the opening one.
const fenceRule = /^ {0,3}(\${2,})[ \t]*\n(?:([\s\S]*?)\n)?? {0,3}\1\$*[ \t]*(?:\n+|$)/;

function matchFence(src: string): EneoMathToken | undefined {
  const match = src.match(fenceRule);
  const text = match?.[2]?.trim();
  if (!match || !text) return;
  return {
    type: "eneoMath",
    level: "block",
    display: true,
    displayDelimiter: true,
    raw: match[0],
    text
  };
}

const mathFence: TokenizerAndRendererExtension = {
  name: "eneoMath",
  level: "block",
  // Ends a paragraph only where a whole fence starts. marked asks with the
  // text from the second character on, so `src` itself is not a line start.
  // marked asks again for each paragraph, so the search stops where this
  // paragraph does, at the first blank line.
  // Known limit: after each cut, marked's setext-heading rule reads on to the
  // next blank line, so fences with no blank lines between them cost
  // fences × lines (200 fences: ~3 ms). Override marked's lheading if needed.
  start(src: string) {
    for (const line of src.matchAll(/\n(?:[ \t]*$| {0,3}\${2,}[ \t]*$)/gm)) {
      if (!line[0].includes("$")) return;
      if (matchFence(src.slice(line.index + 1))) return line.index + 1;
    }
  },
  tokenizer: matchFence
};

export const mathExtensions = [mathFence, inlineMath];

function isBlank(token: Token) {
  return token.type === "text" && !token.raw.trim();
}

/**
 * A paragraph that holds nothing but a `$$…$$` or `\[…\]` formula becomes
 * display math; inside a sentence the same formula stays inline. A ```math
 * fence is display math too. Web-next applies the same rule to its tree.
 */
function toDisplayMath(token: Token): EneoMathToken | undefined {
  if (token.type === "code" && token.lang?.trim() === "math" && token.text.trim()) {
    return {
      type: "eneoMath",
      level: "block",
      display: true,
      displayDelimiter: true,
      raw: token.raw,
      text: token.text.trim()
    };
  }
  if ((token.type !== "paragraph" && token.type !== "text") || !token.tokens) return;
  const content = token.tokens.filter((child) => !isBlank(child));
  const only = content.length === 1 ? content[0] : undefined;
  if (only?.type !== "eneoMath" || !only.displayDelimiter) return;
  return { ...(only as EneoMathToken), level: "block", display: true, raw: token.raw };
}

/** Applies {@link toDisplayMath} through lists and quotes. */
export function promoteDisplayMath(tokens: Token[]): Token[] {
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    const display = toDisplayMath(token);
    if (display) {
      tokens[i] = display;
    } else if (token.type === "list") {
      for (const item of token.items) promoteDisplayMath(item.tokens);
    } else if (token.type === "blockquote" && token.tokens) {
      promoteDisplayMath(token.tokens);
    }
  }
  return tokens;
}

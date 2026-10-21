/**
 * LaTeX math for the marked lexer: `$…$`, `$$…$$`, `\(…\)`, `\[…\]` and
 * ```math fences. Recognised inside marked, so code spans, fences, indented
 * code and link destinations stay marked's and are never searched. When a
 * `$` is money rather than math is decided by @eneo/markdown-math, shared
 * with web-next; both apps are tested against its cases.json.
 */
import { canCloseDollar, canOpenDollar } from "@eneo/markdown-math";
import type { Token, TokenizerAndRendererExtension, TokenizerThis, Tokens } from "marked";
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
 * backslash escapes nothing. An empty pair is matched with an empty `text`:
 * it is no formula, but its closing run opens none either.
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
      return {
        raw: src.slice(0, i + run),
        text: src.slice(open, i).trim(),
        displayDelimiter: true
      };
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

// marked asks where math starts again after each text token, with the rest
// of the paragraph. Its text ends before each of these characters anyway, and
// at each line end when line breaks are kept, so the search stops at the first
// one that is not a `$`. A single `$` that opens no formula (`5 $ eller`,
// `$5 eller $6`) is no cut either: the text runs on past it, as marked's
// does, instead of ending at every price in the answer.
const textEnd = /[$\\<![`*~_]/g;
const textOrLineEnd = /[$\\<![`*~_\n]/g;

// marked builds a text token by appending, so reading its last character
// copies all of it, once per `$` in a paragraph. marked lexes a paragraph's
// text in one call, with one token array and the rest of the text as `src`,
// so the character is read from the `src` of the call's last `$` instead.
const srcAtLastDollar = new WeakMap<Token[], string>();

function charBefore(src: string, tokens: Token[]) {
  const earlier = srcAtLastDollar.get(tokens);
  srcAtLastDollar.set(tokens, src);
  return earlier === undefined
    ? tokens.at(-1)?.raw.at(-1)
    : earlier[earlier.length - src.length - 1];
}

const inlineMath: TokenizerAndRendererExtension = {
  name: "eneoMath",
  level: "inline",
  start(this: TokenizerThis, src: string) {
    const end = this.lexer.options.breaks ? textOrLineEnd : textEnd;
    end.lastIndex = 0;
    for (let hit = end.exec(src); hit; hit = end.exec(src)) {
      const at = hit.index;
      if (src[at] !== "$") return -1;
      // The character before the first one is out of sight here.
      if (at === 0 || src[at + 1] === "$" || matchDollar(src.slice(at), src[at - 1])) return at;
    }
    return -1;
  },
  tokenizer(src: string, tokens: Token[]): EneoMathToken | Tokens.Text | undefined {
    // Only a `$` needs the character before it.
    const prev = src[0] === "$" ? charBefore(src, tokens) : undefined;
    const match = matchInlineMath(src, prev);
    if (!match) return;
    if (!match.text) return { type: "text", raw: match.raw, text: match.raw };
    return { type: "eneoMath", level: "inline", display: false, ...match };
  }
};

/**
 * `masked` with each `*`, `_` and `~` inside a formula of `src` replaced, for
 * marked to look for the end of emphasis and strikethrough in. A formula is
 * read before them, as remark-math reads it in web-next, so `*$x*y$*` is one
 * formula in italics. `masked` is marked's copy of `src`, the same length,
 * with code spans, links and tags covered: those never hold math.
 */
export function hideMathDelimiters(src: string, masked = src) {
  let out = "";
  let from = 0;
  for (let i = 0; i < src.length; i++) {
    const char = src[i];
    // marked covers an escape with `+`, and anything else with other characters.
    if ((char !== "$" && char !== "\\") || (masked[i] !== char && masked[i] !== "+")) continue;
    const match = matchInlineMath(src.slice(i), src[i - 1]);
    if (!match) {
      if (char === "\\") i++;
      continue;
    }
    const end = i + match.raw.length;
    out += masked.slice(from, i) + masked.slice(i, end).replace(/[*_~]/g, "a");
    from = end;
    i = end - 1;
  }
  return from === 0 ? masked : out + masked.slice(from);
}

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

const fenceOpening = / {0,3}\${2,}[ \t]*\n/y;

/** Whether a whole fence starts at `at`, the start of a line. */
export function startsMathFence(src: string, at: number) {
  fenceOpening.lastIndex = at;
  return fenceOpening.test(src) && matchFence(src.slice(at)) !== undefined;
}

// No `start`: eneoMarkdownLexer ends a paragraph at a fence with
// startsMathFence, in one search with its other block extension.
const mathFence: TokenizerAndRendererExtension = {
  name: "eneoMath",
  level: "block",
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

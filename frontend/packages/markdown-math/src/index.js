// LaTeX math in assistant answers: what both chat renderers must agree on.
//
// Models write math as `$…$`, `$$…$$`, `\(…\)` and `\[…\]`. Each app finds it
// inside its own Markdown parser (marked in apps/web, micromark in
// apps/web-next), so code, links, lists and quotes stay the parser's. This
// module owns the shared decisions: when a single `$` is a delimiter rather
// than money, and how KaTeX renders. ../cases.json is the behaviour both
// renderers are tested against.

// Letters and digits. A lone UTF-16 surrogate also counts: renderers see
// characters outside the basic plane (𝑎, 𝟚, emoji) one half at a time, and
// reading such a neighbour as part of a word keeps the `$` beside it literal.
const WORD = /[\p{L}\p{N}\uD800-\uDFFF]/u;
const SPACE = /\s/u;

/**
 * A single `$` opens math unless it is glued to a word before it (`a$x$`,
 * `US$5`) or followed by a space (`100 $ och`) or another `$`.
 *
 * @param {string | undefined} prev Character before the `$`; undefined at the start of the text.
 * @param {string | undefined} next Character after the `$`; undefined at the end of the text.
 */
export function canOpenDollar(prev, next) {
  return canFollowWithDollar(prev) && next !== undefined && !SPACE.test(next) && next !== "$";
}

/**
 * The half of {@link canOpenDollar} a parser can ask before it reads on:
 * whether a `$` after `prev` may open math at all.
 *
 * @param {string | undefined} prev Character before the `$`; undefined at the start of the text.
 */
export function canFollowWithDollar(prev) {
  return prev === undefined || !(WORD.test(prev) || prev === "$");
}

/**
 * A single `$` closes math unless it follows a space (`$5 och $10`) or is
 * glued to a word or digit after it (`$x$2`, `$5–$10`). Only the first
 * unescaped `$` after the opener is tried: when it cannot close, the opener is
 * plain text, so `Kostar $5; använd $x$.` keeps the price and finds `x`.
 *
 * @param {string | undefined} prev Character before the `$`.
 * @param {string | undefined} next Character after the `$`; undefined at the end of the text.
 */
export function canCloseDollar(prev, next) {
  if (prev === undefined || SPACE.test(prev)) return false;
  return next === undefined || !(WORD.test(next) || next === "$");
}

/**
 * KaTeX options for one formula. `trust: false` keeps `\href`, `\url`,
 * `\includegraphics` and `\html*` off; `maxSize` (em) bounds `\rule` and
 * sizing commands; invalid TeX renders as an error instead of throwing. No
 * `macros` table is passed, so KaTeX starts every formula with a fresh one and
 * a `\gdef` in one answer never leaks into another.
 *
 * @param {boolean} displayMode
 */
export function katexOptions(displayMode) {
  return {
    displayMode,
    throwOnError: false,
    trust: false,
    strict: "ignore",
    maxSize: 20,
    maxExpand: 1000,
    output: "htmlAndMathml"
  };
}

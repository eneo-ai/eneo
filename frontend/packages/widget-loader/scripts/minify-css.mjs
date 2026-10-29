/**
 * Collapses the loader's stylesheet for the bundle: comments, indentation and
 * the spaces around punctuation. The shipped bytes count against the gzip
 * budget; the readable source stays in src/styles.ts.
 *
 * @param {string} css
 * @returns {string}
 */
export function minifyCss(css) {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\s+/g, " ")
    .replace(/ ?([{};,>]) ?/g, "$1")
    .replace(/: /g, ":")
    .replace(/;}/g, "}")
    .trim();
}

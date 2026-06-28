/**
 * Flags raw colors written into UI source instead of going through eneo's
 * semantic design tokens.
 *
 * The rule inspects string literals in Svelte, JavaScript, and TypeScript,
 * including class strings assembled in scripts, generated markup, attributes,
 * class directives, and component <style> blocks.
 *
 * What it catches:
 *   - Tailwind palette utilities, including white/black and eneo raw palettes
 *   - Hex values and CSS color functions
 *   - Direct references to raw palette variables (`--color-ui-*`, `--color-soil-*`)
 *   - `dark:` variants, since theme differences belong in semantic tokens
 *
 * Escape hatch: use an ESLint disable comment for a genuinely themeless value,
 * such as a fixed brand or flag color.
 *
 * @type {import("eslint").Rule.RuleModule}
 */

const PALETTE =
  "slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|soil|moss|amethyst|pine";
const UTIL =
  "bg|text|border|ring|ring-offset|fill|stroke|from|via|to|divide|outline|decoration|caret|accent|placeholder|shadow";

const PATTERNS = [
  {
    source: `(?<![\\w-])(?:${UTIL})-(?:(?:${PALETTE})-(?:50|100|200|300|400|500|600|700|800|900|950)|white|black)(?![\\w-])`,
    messageId: "rawColor",
  },
  {
    source: `(?<![\\w-])(?:${UTIL})-\\[\\s*(?:#[0-9a-fA-F]{3,8}|rgba?\\(|hsla?\\(|oklch\\(|lab\\(|lch\\(|hwb\\(|color\\()`,
    messageId: "rawColor",
  },
  {
    source: String.raw`(?<!&)#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?|oklch|lab|lch|hwb|color)\s*\(`,
    messageId: "rawColor",
  },
  {
    source: String.raw`var\(\s*--color-(?:ui|soil|moss|amethyst|pine|eneo|white|black)[\w-]*`,
    messageId: "rawColor",
  },
  {
    source: String.raw`(?<![\w-])dark:`,
    messageId: "darkVariant",
  },
];

const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow raw colors in UI source; use eneo semantic design tokens so colors adapt to light/dark.",
    },
    schema: [],
    messages: {
      rawColor:
        "Raw color `{{ token }}` bypasses the theme tokens. Use a semantic token instead (for example bg-negative-dimmer, text-warning-stronger, bg-secondary, text-muted, or border-default).",
      darkVariant:
        "`dark:` variants bypass eneo's data-theme token system. Put the theme difference in a semantic token instead.",
    },
  },

  create(context) {
    const check = (node, text) => {
      const reported = new Set();
      const coveredRanges = [];

      for (const { source, messageId } of PATTERNS) {
        for (const match of text.matchAll(new RegExp(source, "g"))) {
          const start = match.index;
          const end = start + match[0].length;
          if (
            messageId === "rawColor" &&
            coveredRanges.some(([coveredStart, coveredEnd]) => {
              return start >= coveredStart && end <= coveredEnd;
            })
          ) {
            continue;
          }

          const key = `${messageId}:${match.index}:${match[0]}`;
          if (reported.has(key)) continue;
          reported.add(key);
          if (messageId === "rawColor") coveredRanges.push([start, end]);
          context.report({
            node,
            messageId,
            data: { token: match[0] },
          });
        }
      }
    };

    return {
      Literal(node) {
        if (typeof node.value === "string") check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.raw);
      },
      SvelteLiteral(node) {
        if (typeof node.value === "string") check(node, node.value);
      },
      SvelteDirective(node) {
        if (node.kind === "Class") check(node, node.key?.name?.name ?? "");
      },
      SvelteText(node) {
        if (node.parent?.type === "SvelteStyleElement") {
          check(node, node.value);
        }
      },
    };
  },
};

export default rule;

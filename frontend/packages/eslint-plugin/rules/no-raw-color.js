/**
 * Flags raw colors written straight into `class` attributes instead of going
 * through eneo's semantic design tokens.
 *
 * Eneo has a three-layer color system:
 *   1. Raw palette      packages/ui/src/styles/themes/palette.css
 *                       (--color-ui-red-500, --color-soil-500, …) — never used directly.
 *   2. Semantic tokens  themes/light.css + dark.css, scoped to
 *                       :root[data-theme="light"|"dark"] — auto-switch per theme.
 *                       (--negative-*, --warning-*, --accent-*, --background-*,
 *                        --text-*, --border-*, each in dimmer/default/stronger).
 *   3. Tailwind utils   apps/web/src/app.css @theme inline maps layer 2 to
 *                       `bg-negative-default`, `text-warning-stronger`, etc.
 *
 * Writing Tailwind's built-in palette (`bg-orange-50`, `text-red-600`) or an
 * arbitrary literal (`bg-[#fff]`, `text-[rgb(...)]`) bypasses this system: the
 * color does NOT adapt between light/dark (the theme switches via `data-theme`,
 * not via Tailwind's `.dark` class — which is never set in this app, so `dark:`
 * variants are inert). Use a semantic token instead.
 *
 * What it catches (inside `class="…"`, `class={…}` and `class:…` directives):
 *   - Tailwind palette utilities: (bg|text|border|ring|fill|stroke|…)-<color>-<shade>
 *   - Arbitrary color values: …-[#hex] / …-[rgb(…)] / …-[hsl(…)] / …-[oklch(…)]
 *
 * Escape hatch: `<!-- eslint-disable-next-line intric/no-raw-color -->` for the
 * rare genuinely-themeless surface (e.g. a fixed brand logo color).
 *
 * @type {import('eslint').Rule.RuleModule}
 */

// Tailwind's default palette names. eneo's semantic tokens (negative, warning,
// accent, brand-intric, chart-red, …) are intentionally NOT in this list, so
// `bg-negative-default` / `text-chart-red` are never flagged.
const PALETTE =
  "slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const UTIL =
  "bg|text|border|ring|ring-offset|fill|stroke|from|via|to|divide|outline|decoration|caret|accent|placeholder|shadow";

// `(?<![\w-])` lets a variant prefix precede the utility (e.g. `hover:bg-red-500`,
// `dark:bg-red-500`) since the `:` is not a word/dash char.
const RAW_PALETTE = new RegExp(
  `(?<![\\w-])(?:${UTIL})-(?:${PALETTE})-(?:50|100|200|300|400|500|600|700|800|900|950)(?![\\w-])`,
);

// Arbitrary color literals: `bg-[#fff]`, `text-[rgb(…)]`, `border-[oklch(…)]`.
const RAW_ARBITRARY = new RegExp(
  `(?<![\\w-])(?:${UTIL})-\\[\\s*(?:#[0-9a-fA-F]{3,8}|rgba?\\(|hsla?\\(|oklch\\()`,
);

const firstMatch = (text) => {
  const m = RAW_PALETTE.exec(text) ?? RAW_ARBITRARY.exec(text);
  return m ? m[0] : null;
};

const rule = {
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow raw colors in class attributes; use eneo semantic design tokens (bg-negative-dimmer, text-warning-stronger, …) so colors adapt to light/dark.",
    },
    schema: [],
    messages: {
      rawColor:
        "Raw color `{{ token }}` bypasses the theme tokens and won't adapt to light/dark. Use a semantic token instead (e.g. bg-negative-dimmer, text-warning-stronger, bg-secondary, text-muted, border-default).",
    },
  },

  create(context) {
    const sourceCode = context.sourceCode ?? context.getSourceCode();

    const check = (node) => {
      const token = firstMatch(sourceCode.getText(node));
      if (token) {
        context.report({ node, messageId: "rawColor", data: { token } });
      }
    };

    return {
      // Static and dynamic `class` attributes: class="…" / class={…}
      SvelteAttribute(node) {
        if (node.key?.name === "class") check(node);
      },
      // Class directives: class:bg-red-500={…}
      SvelteDirective(node) {
        if (node.kind === "Class") check(node);
      },
    };
  },
};

export default rule;

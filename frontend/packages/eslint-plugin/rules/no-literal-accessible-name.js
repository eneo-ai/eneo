/**
 * Flags literal accessible names and descriptions in JSX, so everything a
 * screen reader announces comes from the app's message layer (next-intl `t()`
 * in web-next) and is read in the user's language.
 *
 * Checked attributes (on DOM elements and components alike):
 *   aria-label, aria-description, aria-roledescription, aria-valuetext,
 *   aria-placeholder, alt, title, placeholder
 *
 * What it catches:
 *  - String literals: aria-label="Stäng", title={"Close"}
 *  - Static template literals: aria-label={`Stäng`}
 *  - Template literals with untranslated words around the values:
 *    aria-label={`Ta bort ${name}`}
 *  - Literals in either branch of `cond ? a : b` and in `a ?? b` / `a || b`
 *
 * Unlike `no-hardcoded-text` there is no ignore list and no "has letters"
 * check: a symbol ("×", "?") is not an accessible name either.
 *
 * Allowed:
 *  - `alt=""`: the way to mark an image as decorative
 *  - Any expression (t("close"), a prop, a variable), and template literals
 *    whose literal parts are only separators (`${t("file")}: ${name}`)
 *
 * Escape hatch, with a reason and an issue link:
 * `// eslint-disable-next-line eneo/no-literal-accessible-name -- <why> <issue>`
 *
 * @type {import('eslint').Rule.RuleModule}
 */
const NAME_ATTRS = new Set([
  "aria-label",
  "aria-description",
  "aria-roledescription",
  "aria-valuetext",
  "aria-placeholder",
  "alt",
  "title",
  "placeholder",
]);

const HAS_LETTER = /\p{L}/u;

const preview = (raw) => {
  const text = raw.trim().replace(/\s+/g, " ");
  return JSON.stringify(text.length > 40 ? text.slice(0, 40) + "…" : text);
};

/** Unwraps TypeScript-only wrappers: `"x" as string`, `"x"!`, `<string>"x"`. */
function unwrap(node) {
  let current = node;
  while (
    current &&
    (current.type === "TSAsExpression" ||
      current.type === "TSNonNullExpression" ||
      current.type === "TSTypeAssertion" ||
      current.type === "TSSatisfiesExpression")
  ) {
    current = current.expression;
  }
  return current;
}

const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow literal accessible names (aria-label, alt, title, placeholder, …) in JSX; they must come from i18n.",
    },
    schema: [],
    messages: {
      literalName:
        'Literal `{{ attr }}` {{ text }}. Accessible names and descriptions must come from i18n (t("…")) so screen readers read them in the user\'s language.',
    },
  },

  create(context) {
    /** Collects the literal parts of an attribute value that are not allowed. */
    function findLiterals(node, attr, found) {
      const value = unwrap(node);
      if (!value) return;

      switch (value.type) {
        case "Literal":
          if (typeof value.value !== "string") return;
          if (attr === "alt" && value.value === "") return;
          found.push({ node: value, text: value.value });
          return;
        case "TemplateLiteral": {
          const raw = value.quasis.map((quasi) => quasi.value.cooked ?? "");
          if (value.expressions.length === 0) {
            const text = raw.join("");
            if (attr === "alt" && text === "") return;
            found.push({ node: value, text });
            return;
          }
          if (raw.some((part) => HAS_LETTER.test(part))) {
            found.push({ node: value, text: raw.join("${…}") });
          }
          return;
        }
        case "ConditionalExpression":
          findLiterals(value.consequent, attr, found);
          findLiterals(value.alternate, attr, found);
          return;
        case "LogicalExpression":
          findLiterals(value.left, attr, found);
          findLiterals(value.right, attr, found);
          return;
        default:
          return;
      }
    }

    return {
      JSXAttribute(node) {
        if (node.name?.type !== "JSXIdentifier") return;
        const attr = node.name.name;
        if (!NAME_ATTRS.has(attr) || !node.value) return;

        const value =
          node.value.type === "JSXExpressionContainer"
            ? node.value.expression
            : node.value;

        const found = [];
        findLiterals(value, attr, found);
        for (const { node: literal, text } of found) {
          context.report({
            node: literal,
            messageId: "literalName",
            data: { attr, text: preview(text) },
          });
        }
      },
    };
  },
};

export default rule;

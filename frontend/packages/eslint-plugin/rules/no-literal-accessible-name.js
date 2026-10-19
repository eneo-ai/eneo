/**
 * Flags literal accessible names and descriptions in JSX, so everything a
 * screen reader announces comes from the app's message layer (next-intl `t()`
 * in web-next) and is read in the user's language.
 *
 * Checked attributes (on DOM elements and components alike):
 *   aria-label, aria-description, aria-roledescription, aria-valuetext,
 *   aria-placeholder, alt, title, placeholder, plus the component props that
 *   become a name or a tooltip: label (Astryx Button, TextInput, Popover, …)
 *   and tooltip. The `attributes` option adds more (e.g. `hint`).
 *
 * This rule owns attribute literals in JSX: run `eneo/no-hardcoded-text` with
 * `attributes: []` next to it, so each literal is reported once.
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
 *  - Props that are not text on a given component (`ignoreComponents`, by
 *    default next/image's `<Image placeholder="blur">`)
 *
 * Options:
 *  - `attributes`: more attribute or prop names to check.
 *  - `ignoreComponents`: component name → attributes that are not accessible
 *    names on it. Replaces the default `{ Image: ["placeholder"] }`.
 *
 * Escape hatch, with a reason and an issue link:
 * `// eslint-disable-next-line eneo/no-literal-accessible-name -- <why> <issue>`
 *
 * @type {import('eslint').Rule.RuleModule}
 */
const NAME_ATTRS = [
  "aria-label",
  "aria-description",
  "aria-roledescription",
  "aria-valuetext",
  "aria-placeholder",
  "alt",
  "title",
  "placeholder",
  "label",
  "tooltip",
];

// next/image: placeholder is "blur" | "empty" | a data URL, never text.
const DEFAULT_IGNORE_COMPONENTS = { Image: ["placeholder"] };

const HAS_LETTER = /\p{L}/u;

const preview = (raw) => {
  const text = raw.trim().replace(/\s+/g, " ");
  return JSON.stringify(text.length > 40 ? text.slice(0, 40) + "…" : text);
};

/** `Image`, `Astryx.Button`, `svg:title`: the name as written in JSX. */
function elementName(name) {
  switch (name?.type) {
    case "JSXIdentifier":
      return name.name;
    case "JSXMemberExpression":
      return `${elementName(name.object)}.${name.property.name}`;
    case "JSXNamespacedName":
      return `${name.namespace.name}:${name.name.name}`;
    default:
      return "";
  }
}

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
    schema: [
      {
        type: "object",
        properties: {
          attributes: {
            type: "array",
            items: { type: "string" },
            description:
              "More attribute or prop names that carry a name or description.",
          },
          ignoreComponents: {
            type: "object",
            additionalProperties: { type: "array", items: { type: "string" } },
            description:
              "Component name → attributes that are not accessible names on it.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      literalName:
        'Literal `{{ attr }}` {{ text }}. Accessible names and descriptions must come from i18n (t("…")) so screen readers read them in the user\'s language.',
    },
  },

  create(context) {
    const options = context.options[0] ?? {};
    const attributes = new Set([...NAME_ATTRS, ...(options.attributes ?? [])]);
    const ignoreComponents =
      options.ignoreComponents ?? DEFAULT_IGNORE_COMPONENTS;

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
        if (!attributes.has(attr) || !node.value) return;
        const component = elementName(node.parent.name);
        if (
          Object.hasOwn(ignoreComponents, component) &&
          ignoreComponents[component].includes(attr)
        ) {
          return;
        }

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

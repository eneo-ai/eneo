/**
 * Flags Tailwind class lists that hide or weaken the keyboard focus indicator
 * (WCAG 2.4.7 Focus Visible and 1.4.11 Non-text Contrast; web-next
 * ACCESSIBILITY.md → Visible focus):
 *
 *  - Translucent focus rings: `ring-ring/50`, `outline-ring/40`, and any ring
 *    or outline colour with an opacity modifier behind a focus variant
 *    (`focus-visible:ring-destructive/20`). A 50% ring is about 2:1 on white;
 *    a focus indicator needs 3:1.
 *  - `outline-none` / `outline-hidden` (plain or behind a variant) without a
 *    replacement in the same class list: a ring or outline width behind a
 *    focus variant (`focus-visible:outline-2`, `focus-visible:ring-2`, …).
 *
 * Use the full-strength ring instead:
 * `focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring`.
 *
 * A class list is a string literal or template literal, or every string inside
 * one `className` attribute or one call to a class helper (`cn`, `clsx`,
 * `cva`, …; cva variants included), so a replacement anywhere in the list
 * counts. An element that is never in the tab order (`tabIndex={-1}`: a
 * heading or <main> the app focuses from script) may drop its outline.
 *
 * Escape hatch, with a reason: when an ancestor draws the ring (a composite
 * control that shows focus around the whole field),
 * `// eslint-disable-next-line eneo/no-weak-focus-indicator -- <why>`.
 *
 * @type {import('eslint').Rule.RuleModule}
 */

const CLASS_HELPERS = new Set([
  "cn",
  "clsx",
  "cx",
  "classnames",
  "classNames",
  "twMerge",
  "twJoin",
  "cva",
  "tv",
]);

// Nodes a class list flows through on its way to a className or class helper.
const PASS_THROUGH = new Set([
  "ArrayExpression",
  "BinaryExpression",
  "ConditionalExpression",
  "LogicalExpression",
  "ObjectExpression",
  "Property",
  "SpreadElement",
  "TemplateLiteral",
  "TSAsExpression",
  "TSNonNullExpression",
  "TSSatisfiesExpression",
  "TSTypeAssertion",
]);

// Cheap pre-filter before a literal is split into class tokens.
const CANDIDATE = /outline-(?:none|hidden)|(?:ring|outline)-[\w-]+\//;

/** Splits `a:b-[c:d]:e` into variants and utility, ignoring `:` inside brackets. */
function parseClass(token) {
  const parts = [];
  let depth = 0;
  let current = "";
  for (const char of token) {
    if (char === "[" || char === "(") depth += 1;
    if (char === "]" || char === ")") depth -= 1;
    if (char === ":" && depth === 0) {
      parts.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  const utility = current.replace(/^!|!$/g, "");
  return { variants: parts, utility };
}

const isFocusVariant = (variant) => variant.includes("focus");

/** `ring-ring/50`, or a focus-state `ring-*`/`outline-*` colour with an opacity. */
function isTranslucentRing({ variants, utility }) {
  const match = /^(ring|outline)-([a-z][\w-]*)\/\S+$/.exec(utility);
  if (!match) return false;
  const color = match[2];
  if (color.startsWith("offset-")) return false;
  return color === "ring" || variants.some(isFocusVariant);
}

const isOutlineRemoval = ({ utility }) =>
  utility === "outline-none" || utility === "outline-hidden";

/** A focus-state ring or outline width: the visible replacement for the outline. */
function isFocusReplacement({ variants, utility }) {
  if (!variants.some(isFocusVariant)) return false;
  if (
    /^outline(?:-(?:\d+|\[[^\]]+\]|solid|dashed|dotted|double))?$/.test(utility)
  ) {
    return utility !== "outline-0";
  }
  if (/^ring(?:-(?:\d+|\[[^\]]+\]))?$/.test(utility))
    return utility !== "ring-0";
  return false;
}

function classTokens(text) {
  return text.split(/\s+/).filter(Boolean).map(parseClass);
}

function calleeName(call) {
  const callee = call.callee;
  if (callee.type === "Identifier") return callee.name;
  if (
    callee.type === "MemberExpression" &&
    callee.property.type === "Identifier"
  ) {
    return callee.property.name;
  }
  return null;
}

function isClassAttribute(node) {
  if (node?.type !== "JSXAttribute" || node.name.type !== "JSXIdentifier")
    return false;
  const name = node.name.name;
  return name === "class" || name === "className" || name.endsWith("ClassName");
}

// Elements the browser puts in the tab order without a tabIndex.
const FOCUSABLE_TAGS = new Set([
  "a",
  "area",
  "audio",
  "button",
  "details",
  "embed",
  "iframe",
  "input",
  "object",
  "select",
  "summary",
  "textarea",
  "video",
]);

const isMinusOne = (node) =>
  (node.type === "Literal" && (node.value === -1 || node.value === "-1")) ||
  (node.type === "UnaryExpression" &&
    node.operator === "-" &&
    node.argument.type === "Literal" &&
    node.argument.value === 1);

const isNullish = (node) =>
  (node.type === "Literal" && node.value === null) ||
  (node.type === "Identifier" && node.name === "undefined");

/**
 * Whether the element is only ever focused from script (`tabIndex={-1}`, or
 * `-1` or nothing on an element that is not focusable by itself): Tab never
 * lands on it, so it needs no focus indicator.
 */
function isNeverTabbable(element) {
  const tabIndex = element.attributes.find(
    (item) => item.type === "JSXAttribute" && item.name.name === "tabIndex",
  );
  if (!tabIndex?.value) return false;
  const value =
    tabIndex.value.type === "JSXExpressionContainer"
      ? tabIndex.value.expression
      : tabIndex.value;
  if (isMinusOne(value)) return true;
  if (value.type !== "ConditionalExpression") return false;
  const tag = element.name.type === "JSXIdentifier" ? element.name.name : "";
  const focusableByItself = !/^[a-z]/.test(tag) || FOCUSABLE_TAGS.has(tag);
  const branches = [value.consequent, value.alternate];
  return (
    branches.some(isMinusOne) &&
    branches.every(
      (branch) =>
        isMinusOne(branch) || (isNullish(branch) && !focusableByItself),
    )
  );
}

const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow translucent focus rings and outline-none without a visible focus-visible replacement in Tailwind class lists.",
    },
    schema: [],
    messages: {
      translucentRing:
        "`{{ token }}` is a translucent focus ring (about 2:1, below the 3:1 a focus indicator needs). Use focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring.",
      outlineRemoved:
        "`{{ token }}` removes the focus outline without a replacement in the same class list. Add focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring, or drop it.",
    },
  },

  create(context) {
    const { sourceCode } = context;
    const checkedLists = new Set();

    /** The outermost node of the class list `node` belongs to. */
    function classListRoot(node) {
      let current = node;
      for (;;) {
        const parent = current.parent;
        if (!parent) return current;
        if (PASS_THROUGH.has(parent.type)) {
          current = parent;
        } else if (
          parent.type === "CallExpression" &&
          parent.arguments.includes(current)
        ) {
          if (!CLASS_HELPERS.has(calleeName(parent) ?? "")) return current;
          current = parent;
        } else if (parent.type === "JSXExpressionContainer") {
          current = parent;
        } else {
          return current;
        }
      }
    }

    /** Every string of a class list, with the node that holds it. */
    function classStrings(root) {
      const strings = [];
      const visit = (node) => {
        if (!node || typeof node.type !== "string") return;
        if (node.type === "Literal" && typeof node.value === "string") {
          strings.push({ node, text: node.value });
          return;
        }
        if (node.type === "TemplateLiteral") {
          strings.push({
            node,
            text: node.quasis
              .map((quasi) => quasi.value.cooked ?? "")
              .join(" "),
          });
        }
        for (const key of sourceCode.visitorKeys[node.type] ?? []) {
          const child = node[key];
          if (Array.isArray(child)) child.forEach(visit);
          else visit(child);
        }
      };
      visit(root);
      return strings;
    }

    function check(node) {
      const root = classListRoot(node);
      if (checkedLists.has(root)) return;
      checkedLists.add(root);

      const strings = classStrings(root).map((entry) => ({
        ...entry,
        tokens: classTokens(entry.text),
      }));
      const attribute = root.parent;
      const exemptFromOutline =
        isClassAttribute(attribute) && isNeverTabbable(attribute.parent);
      const hasReplacement = strings.some(({ tokens }) =>
        tokens.some(isFocusReplacement),
      );

      for (const { node: holder, text, tokens } of strings) {
        const raw = text.split(/\s+/).filter(Boolean);
        tokens.forEach((token, index) => {
          if (isTranslucentRing(token)) {
            context.report({
              node: holder,
              messageId: "translucentRing",
              data: { token: raw[index] },
            });
          } else if (
            isOutlineRemoval(token) &&
            !hasReplacement &&
            !exemptFromOutline
          ) {
            context.report({
              node: holder,
              messageId: "outlineRemoved",
              data: { token: raw[index] },
            });
          }
        });
      }
    }

    return {
      Literal(node) {
        if (typeof node.value === "string" && CANDIDATE.test(node.value))
          check(node);
      },
      TemplateLiteral(node) {
        if (
          node.quasis.some((quasi) => CANDIDATE.test(quasi.value.cooked ?? ""))
        )
          check(node);
      },
    };
  },
};

export default rule;

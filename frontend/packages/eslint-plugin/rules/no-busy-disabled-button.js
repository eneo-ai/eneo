/**
 * Flags a button or switch that disables itself while its own work runs
 * (WCAG 2.4.3 Focus Order; web-next ACCESSIBILITY.md → Forms). The moment it
 * turns disabled, keyboard and screen reader focus drops to the page, and the
 * user has to find their way back. Busy, a button stays enabled, says so with
 * `aria-busy` (Astryx: `isLoading` with `isInterruptible`) and ignores a
 * second press; a switch that saves on toggle stays enabled too
 * (`useSettingSwitch` shows the press at once and queues the next).
 *
 * Reported:
 *  - `disabled` or `isDisabled` whose expression reads a pending-like name
 *    that is not negated (`save.isPending`, `saving`, `busy !== null`,
 *    `isFetchingNextPage`), on:
 *    - a legacy Button (`@/components/ui/button`) or an Astryx Button
 *      (`@astryxdesign/core/Button`), under any local name;
 *    - a legacy Switch (`@/components/ui/switch`) or the Astryx Switch
 *      (`@/components/astryx/switch`, `@astryxdesign/core/Switch`).
 *    A name is pending-like when one of its words (camelCase or snake_case)
 *    is in `names` (default: pending, saving, busy, submitting, running,
 *    fetching, uploading, deleting, removing, restoring, connecting).
 *  - An Astryx Button with `isLoading` or `clickAction` and no
 *    `isInterruptible`: Astryx disables a loading button unless it is
 *    interruptible.
 *
 * Not reported:
 *  - A dismiss button, labelled with one of `dismissLabels` (translation
 *    keys; default cancel, back, close): `<Button>{t("cancel")}</Button>`,
 *    `<Button label={t("cancel")} />`. It may wait while the form's action
 *    runs, since the action holds the focus then.
 *  - A negated name: `isDisabled={!busy && !canSubmit}` is enabled while busy.
 *
 * Escape hatch, with a reason, for a gate that is not the control's own work
 * (a background job the page reports elsewhere, a draft field while its form
 * saves):
 * `// eslint-disable-next-line eneo/no-busy-disabled-button -- <why>`
 *
 * @type {import('eslint').Rule.RuleModule}
 */

const DEFAULT_NAMES = [
  "pending",
  "saving",
  "busy",
  "submitting",
  "running",
  "fetching",
  "uploading",
  "deleting",
  "removing",
  "restoring",
  "connecting",
];
const DEFAULT_DISMISS_LABELS = ["cancel", "back", "close"];

/** Where the checked controls come from: the component imported under `name`. */
const CONTROLS = [
  {
    name: "Button",
    source: /(^|\/)components\/ui\/button$/,
    control: "button",
  },
  {
    name: "Button",
    source: /^@astryxdesign\/core(\/Button)?$/,
    control: "astryxButton",
  },
  {
    name: "Switch",
    source: /(^|\/)components\/ui\/switch$/,
    control: "switch",
  },
  {
    name: "Switch",
    source: /^(@\/components\/astryx\/switch|@astryxdesign\/core(\/Switch)?)$/,
    control: "switch",
  },
];
const DISABLED_PROPS = new Set(["disabled", "isDisabled"]);

/** `isFetchingNextPage` → is, fetching, next, page; `save_pending` → save, pending. */
function words(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .toLowerCase()
    .split(/[\s_$]+/)
    .filter(Boolean);
}

/** A JSX attribute's expression, or null for a string or missing value. */
function attributeExpression(attribute) {
  const value = attribute?.value;
  if (value?.type !== "JSXExpressionContainer") return null;
  return value.expression.type === "JSXEmptyExpression"
    ? null
    : value.expression;
}

function findAttribute(opening, name) {
  return opening.attributes.find(
    (attribute) =>
      attribute.type === "JSXAttribute" && attribute.name?.name === name,
  );
}

/** `isLoading`, `isLoading={x}`: set; `isLoading={false}`: not. */
function isSet(attribute) {
  if (!attribute) return false;
  if (attribute.value === null) return true;
  const expression = attributeExpression(attribute);
  return !(expression?.type === "Literal" && expression.value === false);
}

const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow buttons and switches that disable themselves while their own work runs; keep them enabled with aria-busy so they keep focus.",
    },
    schema: [
      {
        type: "object",
        properties: {
          names: { type: "array", items: { type: "string" } },
          dismissLabels: { type: "array", items: { type: "string" } },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      switchDisabledWhileBusy:
        "`{{ prop }}` reads `{{ name }}`: a switch disabled while its change saves drops focus to the page. Keep it enabled with aria-busy (useSettingSwitch for a setting that saves on toggle) and ignore or queue a toggle made meanwhile (ACCESSIBILITY.md → Forms).",
      disabledWhileBusy:
        "`{{ prop }}` reads `{{ name }}`: a button disabled while its own action runs drops focus to the page. Keep it enabled with aria-busy (Astryx: isLoading + isInterruptible) and ignore a second press in its handler (ACCESSIBILITY.md → Forms).",
      loadingDisables:
        "An Astryx Button with {{ prop }} and no isInterruptible disables itself while busy and drops focus. Add isInterruptible and ignore a second press in its handler (ACCESSIBILITY.md → Forms).",
    },
  },

  create(context) {
    const options = context.options[0] ?? {};
    const names = new Set(
      (options.names ?? DEFAULT_NAMES).map((name) => name.toLowerCase()),
    );
    const dismissLabels = new Set(
      options.dismissLabels ?? DEFAULT_DISMISS_LABELS,
    );
    const { visitorKeys } = context.sourceCode;

    /** Local name → "button" | "astryxButton" | "switch", from this file's imports. */
    const controls = new Map();

    const isPendingName = (name) => words(name).some((word) => names.has(word));

    /** The first pending-like name `node` reads outside a `!`, if any. */
    function pendingName(node, negated = false) {
      if (!node || typeof node.type !== "string") return null;
      switch (node.type) {
        case "Identifier":
          return !negated && isPendingName(node.name) ? node.name : null;
        case "UnaryExpression":
          return pendingName(
            node.argument,
            node.operator === "!" ? !negated : negated,
          );
        case "MemberExpression":
          return (
            pendingName(node.object, negated) ??
            pendingName(node.property, negated)
          );
        case "Property":
          // `{ pending: x }` reads x, not a name `pending`.
          return (
            pendingName(node.value, negated) ??
            (node.computed ? pendingName(node.key, negated) : null)
          );
        case "TSAsExpression":
        case "TSSatisfiesExpression":
        case "TSNonNullExpression":
        case "TSTypeAssertion":
          return pendingName(node.expression, negated);
        default:
          // Types name no state (`as PendingState`).
          if (node.type.startsWith("TS")) return null;
      }
      for (const key of visitorKeys[node.type] ?? []) {
        const child = node[key];
        const children = Array.isArray(child) ? child : [child];
        for (const item of children) {
          const found = pendingName(item, negated);
          if (found) return found;
        }
      }
      return null;
    }

    /** `t("cancel")` with a dismiss key. */
    function isDismissLabel(expression) {
      if (expression?.type !== "CallExpression") return false;
      const [first] = expression.arguments;
      return first?.type === "Literal" && typeof first.value === "string"
        ? dismissLabels.has(first.value)
        : false;
    }

    function isDismissButton(opening) {
      if (isDismissLabel(attributeExpression(findAttribute(opening, "label"))))
        return true;
      const element = opening.parent;
      return (element?.children ?? []).some(
        (child) =>
          child.type === "JSXExpressionContainer" &&
          isDismissLabel(child.expression),
      );
    }

    return {
      ImportDeclaration(node) {
        const source = node.source.value;
        for (const specifier of node.specifiers) {
          if (specifier.type !== "ImportSpecifier") continue;
          const match = CONTROLS.find(
            (entry) =>
              entry.name === specifier.imported.name &&
              entry.source.test(source),
          );
          if (match) controls.set(specifier.local.name, match.control);
        }
      },

      JSXOpeningElement(node) {
        if (node.name.type !== "JSXIdentifier") return;
        const kind = controls.get(node.name.name);
        if (!kind) return;
        const dismiss = kind !== "switch" && isDismissButton(node);

        for (const attribute of node.attributes) {
          if (
            attribute.type !== "JSXAttribute" ||
            !DISABLED_PROPS.has(attribute.name?.name)
          ) {
            continue;
          }
          if (dismiss) continue;
          const name = pendingName(attributeExpression(attribute));
          if (name) {
            context.report({
              node: attribute,
              messageId:
                kind === "switch"
                  ? "switchDisabledWhileBusy"
                  : "disabledWhileBusy",
              data: { prop: attribute.name.name, name },
            });
          }
        }

        if (kind !== "astryxButton" || dismiss) return;
        if (isSet(findAttribute(node, "isInterruptible"))) return;
        for (const prop of ["isLoading", "clickAction"]) {
          const attribute = findAttribute(node, prop);
          if (isSet(attribute)) {
            context.report({
              node: attribute,
              messageId: "loadingDisables",
              data: { prop },
            });
          }
        }
      },
    };
  },
};

export default rule;

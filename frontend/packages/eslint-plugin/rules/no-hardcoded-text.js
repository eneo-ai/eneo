/**
 * Flags hardcoded human-facing text in Svelte markup so every string goes
 * through paraglide (`m.*`) instead of being typed inline.
 *
 * What it catches:
 *  - Template text nodes that contain letters ("Detta kan inte ångras")
 *  - Literal values of human-facing attributes (aria-label, title, alt, …)
 *
 * What it ignores (so it stays low-noise):
 *  - HTML comments and <script>/<style> content (not SvelteText / not markup attrs)
 *  - Whitespace and symbol-only text ("—", "·", "→", ":", numbers)
 *  - `{m.foo()}` and any other mustache expression (those are not text nodes)
 *  - Anything matching an `ignore` regex from the rule options
 *
 * Escape hatch: `<!-- eslint-disable-next-line intric/no-hardcoded-text -->`
 * for the rare genuinely-untranslatable literal (brand names, symbols).
 *
 * @type {import('eslint').Rule.RuleModule}
 */
const HUMAN_ATTRS = new Set([
  // HTML human-facing attributes
  "aria-label",
  "aria-description",
  "aria-placeholder",
  "aria-roledescription",
  "aria-valuetext",
  "title",
  "placeholder",
  "alt",
  // Common component props that carry display text
  "label",
  "submitLabel",
  "hint",
]);

// At least one cased letter (any script, incl. å/ä/ö). Pure symbols, numbers,
// punctuation and whitespace are intentionally allowed.
const HAS_LETTER = /\p{L}/u;

const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow hardcoded human-facing text in Svelte markup; use paraglide messages (m.*) instead.",
    },
    schema: [
      {
        type: "object",
        properties: {
          ignore: {
            type: "array",
            items: { type: "string" },
            description: "Regex patterns for text that is allowed inline.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      hardcodedText:
        "Hardcoded text {{ text }}. Move it to messages/{sv,en}.json and use m.* instead.",
      hardcodedAttr:
        "Hardcoded text in `{{ attr }}` {{ text }}. Use a paraglide message (m.*) instead.",
    },
  },

  create(context) {
    const opts = context.options[0] ?? {};
    const ignore = (opts.ignore ?? []).map((p) => new RegExp(p, "u"));

    const allowed = (raw) => {
      const text = raw.trim();
      if (text === "" || !HAS_LETTER.test(text)) return true;
      return ignore.some((re) => re.test(text));
    };

    const preview = (raw) => {
      const text = raw.trim().replace(/\s+/g, " ");
      return JSON.stringify(text.length > 40 ? text.slice(0, 40) + "…" : text);
    };

    return {
      // Bare text between tags: <p>Detta kan inte ångras</p>
      SvelteText(node) {
        // Attribute literals are also `SvelteText` in older parser versions;
        // handle the attribute case in SvelteLiteral/SvelteAttribute below and
        // skip non-element parents here.
        const parentType = node.parent?.type;
        if (parentType !== "SvelteElement" && parentType !== "SvelteFragment") {
          return;
        }
        if (allowed(node.value)) return;
        context.report({
          node,
          messageId: "hardcodedText",
          data: { text: preview(node.value) },
        });
      },

      // Attribute string literals: aria-label="Tillåt …", title="…"
      SvelteLiteral(node) {
        const attr = node.parent;
        if (attr?.type !== "SvelteAttribute") return;
        const name = attr.key?.name;
        if (typeof name !== "string" || !HUMAN_ATTRS.has(name)) return;
        if (allowed(node.value)) return;
        context.report({
          node,
          messageId: "hardcodedAttr",
          data: { attr: name, text: preview(node.value) },
        });
      },
    };
  },
};

export default rule;

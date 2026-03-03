/**
 * Adds syntax-highlighting <span> wrappers to pretty-printed JSON strings.
 * Designed for output from JSON.stringify(obj, null, 2).
 *
 * Returns HTML safe for {@html ...} rendering in Svelte.
 * Consuming component must define colors for CSS classes:
 *   .json-key, .json-string, .json-number, .json-boolean
 */
export function highlightJson(json: string): string {
  const safe = json.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return safe
    .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
    .replace(/: (true|false|null)\b/g, ': <span class="json-boolean">$1</span>');
}

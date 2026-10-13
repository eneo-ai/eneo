/**
 * Turns source text into highlighted HTML with highlight.js, for the two languages the views
 * show: the JavaScript a calculation ran, and the JSON it was given or returned. The classes
 * in the output are the usual `hljs-*` tokens; `kit.css` maps them onto the theme's colours.
 */
import hljs from "highlight.js/lib/core";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);

export type CodeLanguage = "javascript" | "json";

/** HTML for `text` with tokens wrapped in `hljs-*` spans; plain escaped text for no language. */
export function highlight(text: string, language?: CodeLanguage): string {
  if (!language) return escapeHtml(text);
  return hljs.highlight(text, { language, ignoreIllegals: true }).value;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>]/g, (char) => (char === "&" ? "&amp;" : char === "<" ? "&lt;" : "&gt;"));
}

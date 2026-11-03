import type { CodeHighlighterPlugin, ThemeInput } from "@streamdown/code";

/**
 * Streamdown's Shiki plugin, loaded with the first code block it colours or,
 * earlier, while the browser is idle after an answer has rendered. Shiki is
 * about 50 KB gzip that a new, empty chat never needs. Highlighting is
 * asynchronous anyway: a block shows as plain code until its tokens arrive,
 * so the load only delays the colours of the first block. A failed load is
 * tried again by the next block.
 */
const THEMES: [ThemeInput, ThemeInput] = [
  "github-light-high-contrast",
  "github-dark-high-contrast"
];

let shiki: CodeHighlighterPlugin | null = null;
let loading: Promise<CodeHighlighterPlugin> | null = null;
let preloading = false;

function load(): Promise<CodeHighlighterPlugin> {
  loading ??= import("@streamdown/code").then(
    (module) => (shiki = module.createCodePlugin({ themes: THEMES })),
    (error: unknown) => {
      loading = null;
      throw error;
    }
  );
  return loading;
}

export const code: CodeHighlighterPlugin = {
  name: "shiki",
  type: "code-highlighter",
  getThemes: () => THEMES,
  // Streamdown asks only for the themes and the tokens; until Shiki has
  // loaded, these two answer that no language is known yet.
  supportsLanguage: (language) => shiki?.supportsLanguage(language) ?? false,
  getSupportedLanguages: () => shiki?.getSupportedLanguages() ?? [],
  highlight(options, callback) {
    if (shiki) return shiki.highlight(options, callback);
    load().then(
      (loaded) => {
        // Shiki answers at once from its cache; otherwise it calls back itself.
        const result = loaded.highlight(options, callback);
        if (result) callback?.(result);
      },
      () => {}
    );
    return null;
  }
};

/** Loads Shiki when the browser is next idle; off the page's critical path. */
export function preloadCodeHighlighter(): void {
  if (shiki || preloading) return;
  preloading = true;
  const start = () => void load().catch(() => {});
  if ("requestIdleCallback" in window) window.requestIdleCallback(start);
  else setTimeout(start, 2000);
}

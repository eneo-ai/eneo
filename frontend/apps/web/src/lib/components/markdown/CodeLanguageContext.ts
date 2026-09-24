import { getContext, setContext } from "svelte";

const key = Symbol("markdown-default-code-language");

/** Language for fenced code blocks without a tag; `undefined` lets the code block auto-detect. */
export function setDefaultCodeLanguage(language: () => string | undefined) {
  setContext(key, language);
}

export function getDefaultCodeLanguage(): () => string | undefined {
  return getContext<(() => string | undefined) | undefined>(key) ?? (() => undefined);
}

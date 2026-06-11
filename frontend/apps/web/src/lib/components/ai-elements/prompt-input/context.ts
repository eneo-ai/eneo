import { getContext, setContext } from "svelte";

/** Mirrors the AI SDK chat status union that AI Elements components key off. */
export type PromptInputStatus = "ready" | "submitted" | "streaming" | "error";

export type PromptInputContext = {
  readonly status: PromptInputStatus;
  stop: () => void;
};

const CONTEXT_KEY = Symbol("prompt-input");

export function setPromptInputContext(context: PromptInputContext): PromptInputContext {
  return setContext(CONTEXT_KEY, context);
}

export function getPromptInputContext(): PromptInputContext {
  const context = getContext<PromptInputContext | undefined>(CONTEXT_KEY);
  if (!context) {
    throw new Error("PromptInput sub-components must be rendered inside <PromptInput>");
  }
  return context;
}

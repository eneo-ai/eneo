import { getContext, setContext } from "svelte";

export type ModelSelectorContext = {
  close: () => void;
};

const CONTEXT_KEY = Symbol("model-selector");

export function setModelSelectorContext(context: ModelSelectorContext): ModelSelectorContext {
  return setContext(CONTEXT_KEY, context);
}

export function getModelSelectorContext(): ModelSelectorContext {
  const context = getContext<ModelSelectorContext | undefined>(CONTEXT_KEY);
  if (!context) {
    throw new Error("ModelSelector sub-components must be rendered inside <ModelSelector>");
  }
  return context;
}

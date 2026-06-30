import { getContext, setContext } from "svelte";
import type { CustomRenderers } from "./CustomComponents";
import type { InfoBlob } from "@eneo/eneo-js";

const ctxKey = Symbol("Message references");

// For now we don't need any extra state in here, as the references are already a closure.
// The only prupose is shuffling the API around a bit so it looks more like our other stores
// and turning the explicit function call into a getter.
export function initReferenceContext(params: {
  references: () => InfoBlob[];
  renderer: () => CustomRenderers["inref"];
}) {
  const data = {
    state: {
      references: {
        get current() {
          return params.references();
        }
      }
    },
    get CustomRenderer() {
      return params.renderer();
    }
  };

  setContext(ctxKey, data);
  return data;
}

export function getReferenceContext() {
  return getContext<ReturnType<typeof initReferenceContext>>(ctxKey);
}

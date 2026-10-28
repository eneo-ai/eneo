"use client";

import {
  Typeahead as AstryxTypeahead,
  type SearchableItem,
  type TypeaheadProps
} from "@astryxdesign/core/Typeahead";
import { useAriaInvalidOnError } from "./use-aria-invalid-on-error";

/**
 * Astryx Typeahead whose error status is announced as one (see
 * useAriaInvalidOnError). Lint sends every Typeahead import here.
 */
export function Typeahead<T extends SearchableItem>({ ref, ...props }: TypeaheadProps<T>) {
  const fieldRef = useAriaInvalidOnError(ref, props.status);
  return <AstryxTypeahead {...props} ref={fieldRef} />;
}

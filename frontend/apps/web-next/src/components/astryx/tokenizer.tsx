"use client";

import { Tokenizer as AstryxTokenizer, type TokenizerProps } from "@astryxdesign/core/Tokenizer";
import type { SearchableItem } from "@astryxdesign/core/Typeahead";
import { useAriaInvalidOnError } from "./use-aria-invalid-on-error";

/**
 * Astryx Tokenizer whose error status is announced as one (see
 * useAriaInvalidOnError). Lint sends every Tokenizer import here.
 */
export function Tokenizer<T extends SearchableItem>({ ref, ...props }: TokenizerProps<T>) {
  const fieldRef = useAriaInvalidOnError(ref, props.status);
  return <AstryxTokenizer {...props} ref={fieldRef} />;
}

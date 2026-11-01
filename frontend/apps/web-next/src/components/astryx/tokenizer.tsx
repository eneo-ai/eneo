"use client";

import { Tokenizer as AstryxTokenizer, type TokenizerProps } from "@astryxdesign/core/Tokenizer";
import type { SearchableItem } from "@astryxdesign/core/Typeahead";
import { useAriaInvalidOnError } from "./use-aria-invalid-on-error";

/** What a `KEYBOARD` preset sets: Astryx's Tokenizer keeps these off its input, so the wrapper sets them. */
type KeyboardAttributes = {
  enterKeyHint?: string;
  inputMode?: string;
  autoCapitalize?: string;
  autoCorrect?: string;
  spellCheck?: boolean;
};

/**
 * Astryx Tokenizer whose error status is announced as one (see
 * useAriaInvalidOnError) and whose input takes a `KEYBOARD` preset, as
 * Typeahead's does. Lint sends every Tokenizer import here.
 */
export function Tokenizer<T extends SearchableItem>({
  ref,
  enterKeyHint,
  inputMode,
  autoCapitalize,
  autoCorrect,
  spellCheck,
  ...props
}: TokenizerProps<T> & KeyboardAttributes) {
  const fieldRef = useAriaInvalidOnError(ref, props.status, {
    enterkeyhint: enterKeyHint,
    inputmode: inputMode,
    autocapitalize: autoCapitalize,
    autocorrect: autoCorrect,
    spellcheck: spellCheck
  });
  return <AstryxTokenizer {...props} ref={fieldRef} />;
}

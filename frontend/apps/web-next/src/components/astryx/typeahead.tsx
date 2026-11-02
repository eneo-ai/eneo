import {
  Typeahead as AstryxTypeahead,
  type SearchableItem,
  type TypeaheadProps
} from "@astryxdesign/core/Typeahead";
import { useAriaInvalidOnError } from "./use-aria-invalid-on-error";

/** What a `KEYBOARD` preset sets: Astryx's Typeahead keeps these off its input, so the wrapper sets them. */
type KeyboardAttributes = {
  enterKeyHint?: string;
  inputMode?: string;
  autoCapitalize?: string;
  autoCorrect?: string;
  spellCheck?: boolean;
};

/**
 * Astryx Typeahead whose error status is announced as one (see
 * useAriaInvalidOnError) and whose input takes a `KEYBOARD` preset (spread
 * `{...KEYBOARD.email}`): Astryx does not pass unknown attributes to the
 * `<input>`, so they are set on it after each render. Lint sends every
 * Typeahead import here.
 */
export function Typeahead<T extends SearchableItem>({
  ref,
  enterKeyHint,
  inputMode,
  autoCapitalize,
  autoCorrect,
  spellCheck,
  ...props
}: TypeaheadProps<T> & KeyboardAttributes) {
  const fieldRef = useAriaInvalidOnError(ref, props.status, {
    enterkeyhint: enterKeyHint,
    inputmode: inputMode,
    autocapitalize: autoCapitalize,
    autocorrect: autoCorrect,
    spellcheck: spellCheck
  });
  return <AstryxTypeahead {...props} ref={fieldRef} />;
}

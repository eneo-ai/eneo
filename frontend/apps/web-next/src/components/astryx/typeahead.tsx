import {
  Typeahead as AstryxTypeahead,
  type SearchableItem,
  type TypeaheadProps
} from "@astryxdesign/core/Typeahead";

/** What a `KEYBOARD` preset sets: left out of Astryx's Typeahead types, but passed on to its `<input>`. */
export type KeyboardAttributes = {
  enterKeyHint?: string;
  inputMode?: string;
  autoCapitalize?: string;
  autoCorrect?: string;
  spellCheck?: boolean;
};

/**
 * Astryx Typeahead whose input takes a `KEYBOARD` preset (spread
 * `{...KEYBOARD.email}`). Astryx passes props it does not know on to the
 * `<input>`, which is also what the ref points at. Lint sends every Typeahead
 * import here.
 */
export function Typeahead<T extends SearchableItem>({
  enterKeyHint,
  inputMode,
  autoCapitalize,
  autoCorrect,
  spellCheck,
  ...props
}: TypeaheadProps<T> & KeyboardAttributes) {
  const keyboard: object = { enterKeyHint, inputMode, autoCapitalize, autoCorrect, spellCheck };
  return <AstryxTypeahead {...keyboard} {...props} />;
}

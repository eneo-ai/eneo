import { Tokenizer as AstryxTokenizer, type TokenizerProps } from "@astryxdesign/core/Tokenizer";
import type { SearchableItem } from "@astryxdesign/core/Typeahead";
import type { KeyboardAttributes } from "./typeahead";

/**
 * Astryx Tokenizer whose input takes a `KEYBOARD` preset, as Typeahead's
 * does. Lint sends every Tokenizer import here.
 */
export function Tokenizer<T extends SearchableItem>({
  enterKeyHint,
  inputMode,
  autoCapitalize,
  autoCorrect,
  spellCheck,
  ...props
}: TokenizerProps<T> & KeyboardAttributes) {
  const keyboard: object = { enterKeyHint, inputMode, autoCapitalize, autoCorrect, spellCheck };
  return <AstryxTokenizer {...keyboard} {...props} />;
}

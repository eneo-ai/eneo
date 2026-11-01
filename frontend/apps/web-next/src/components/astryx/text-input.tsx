import { useMergedRefs } from "@astryxdesign/core/hooks";
import {
  TextInput as AstryxTextInput,
  type TextInputProps as AstryxTextInputProps
} from "@astryxdesign/core/TextInput";
import { type InputHTMLAttributes, useRef } from "react";

// Astryx 0.7.3 forwards native input attributes but omits maxLength from its type.
export type TextInputProps = AstryxTextInputProps &
  Pick<InputHTMLAttributes<HTMLInputElement>, "maxLength">;

/** Astryx TextInput with the phone keyboard's search key. Lint sends every TextInput import here. */
export function TextInput({ ref, onEnter, ...props }: TextInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const mergedRef = useMergedRefs(ref, inputRef);

  // The search key on a phone's keyboard (KEYBOARD.search) means "show me": the
  // filter already ran as it was typed, so the keyboard goes and the list is
  // what is left on screen.
  const isSearch = (props as { enterKeyHint?: string }).enterKeyHint === "search";
  const handleEnter = isSearch
    ? () => {
        onEnter?.();
        inputRef.current?.blur();
      }
    : onEnter;

  return <AstryxTextInput {...props} onEnter={handleEnter} ref={mergedRef} />;
}

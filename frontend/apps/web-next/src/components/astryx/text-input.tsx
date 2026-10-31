import {
  TextInput as AstryxTextInput,
  type TextInputProps as AstryxTextInputProps
} from "@astryxdesign/core/TextInput";
import type { InputHTMLAttributes } from "react";

// Astryx 0.7.3 forwards native input attributes but omits maxLength from its type.
export type TextInputProps = AstryxTextInputProps &
  Pick<InputHTMLAttributes<HTMLInputElement>, "maxLength">;

export function TextInput(props: TextInputProps) {
  return <AstryxTextInput {...props} />;
}

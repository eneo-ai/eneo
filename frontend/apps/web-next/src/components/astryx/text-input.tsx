"use client";

import { useMergedRefs } from "@astryxdesign/core/hooks";
import {
  TextInput as AstryxTextInput,
  type TextInputProps as AstryxTextInputProps
} from "@astryxdesign/core/TextInput";
import { useLayoutEffect, useRef } from "react";

export type TextInputProps = AstryxTextInputProps & {
  /**
   * Ids of more elements that describe the field, such as a password policy
   * checklist next to it, read after its own description and status.
   */
  describedBy?: string;
};

/**
 * Astryx TextInput that other elements can describe. Astryx 0.6.3 sets the
 * input's aria-describedby to its own description and status, over any the
 * caller passes, so `describedBy` is added to it after each render: Astryx
 * rewrites the attribute only when its own ids change, which a render of this
 * wrapper follows.
 */
export function TextInput({ describedBy, ref, ...props }: TextInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const mergedRef = useMergedRefs(ref, inputRef);

  // No dependency list: whatever Astryx wrote this render is extended.
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input || !describedBy) return;
    const ids = (input.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean);
    const missing = describedBy.split(" ").filter((id) => id && !ids.includes(id));
    if (missing.length > 0) input.setAttribute("aria-describedby", [...ids, ...missing].join(" "));
  });

  return <AstryxTextInput {...props} ref={mergedRef} />;
}

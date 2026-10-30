"use client";

import { useMergedRefs } from "@astryxdesign/core/hooks";
import { TextInput as AstryxTextInput, type TextInputProps } from "@astryxdesign/core/TextInput";
import { useLayoutEffect, useRef } from "react";

export type { TextInputProps };

/**
 * Astryx TextInput whose `aria-describedby` works. Astryx 0.6.4 sets the
 * input's aria-describedby to its own description and status and drops the
 * caller's, so the caller's ids (a password policy checklist next to the
 * field, say) are added after Astryx's own after each render: Astryx rewrites
 * the attribute only when its own ids change, which a render of this wrapper
 * follows. Lint sends every TextInput import here.
 */
export function TextInput({
  "aria-describedby": describedBy,
  ref,
  onEnter,
  ...props
}: TextInputProps) {
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

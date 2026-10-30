"use client";

import {
  ChatComposerInput as AstryxChatComposerInput,
  type ChatComposerInputProps
} from "@astryxdesign/core/Chat";
import { useMergedRefs } from "@astryxdesign/core/hooks";
import { useLayoutEffect, useRef } from "react";

export type { ChatComposerInputProps };

/**
 * Astryx ChatComposerInput whose `aria-describedby` reaches the element you
 * type in. Astryx 0.7.3 spreads a caller's attributes on the input's wrapper,
 * so the hint and validation state would otherwise never be read
 * out with the field. The ids are written on the editable element after each
 * render; Astryx sets no `aria-describedby` of its own there, so nothing is
 * overwritten.
 */
export function ChatComposerInput({
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
  ref,
  ...props
}: ChatComposerInputProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const mergedRef = useMergedRefs(ref, rootRef);

  // No dependency list: the editable is re-rendered by Astryx as its state
  // changes, and the attribute must survive every render.
  useLayoutEffect(() => {
    const editable = rootRef.current?.querySelector<HTMLElement>("[contenteditable]");
    if (!editable) return;
    if (describedBy) editable.setAttribute("aria-describedby", describedBy);
    else editable.removeAttribute("aria-describedby");
    if (invalid) editable.setAttribute("aria-invalid", String(invalid));
    else editable.removeAttribute("aria-invalid");
  });

  return <AstryxChatComposerInput {...props} ref={mergedRef} />;
}

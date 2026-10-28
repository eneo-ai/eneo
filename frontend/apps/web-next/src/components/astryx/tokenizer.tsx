"use client";

import { useMergedRefs } from "@astryxdesign/core/hooks";
import { Tokenizer as AstryxTokenizer, type TokenizerProps } from "@astryxdesign/core/Tokenizer";
import type { SearchableItem } from "@astryxdesign/core/Typeahead";
import { useLayoutEffect, useRef } from "react";

/**
 * Astryx Tokenizer whose error status is announced as one: as with its
 * Typeahead (typeahead.tsx), Astryx 0.6.4 paints an error status but never
 * sets the input's aria-invalid. That is set here after each render. Lint
 * sends every Tokenizer import here.
 */
export function Tokenizer<T extends SearchableItem>({ ref, ...props }: TokenizerProps<T>) {
  const fieldRef = useRef<HTMLDivElement>(null);
  const mergedRef = useMergedRefs(ref, fieldRef);
  const invalid = props.status?.type === "error";

  // No dependency list: the input re-renders with Astryx's own attributes.
  useLayoutEffect(() => {
    const input = fieldRef.current?.querySelector("input");
    if (invalid) input?.setAttribute("aria-invalid", "true");
    else input?.removeAttribute("aria-invalid");
  });

  return <AstryxTokenizer {...props} ref={mergedRef} />;
}

"use client";

import { useMergedRefs } from "@astryxdesign/core/hooks";
import {
  Typeahead as AstryxTypeahead,
  type SearchableItem,
  type TypeaheadProps
} from "@astryxdesign/core/Typeahead";
import { useLayoutEffect, useRef } from "react";

/**
 * Astryx Typeahead whose error status is announced as one. Astryx 0.6.4 paints
 * an error status and names its message in aria-describedby, but unlike its
 * TextInput it never sets the input's aria-invalid; that is set here after each
 * render. Lint sends every Typeahead import here.
 */
export function Typeahead<T extends SearchableItem>({ ref, ...props }: TypeaheadProps<T>) {
  const fieldRef = useRef<HTMLDivElement>(null);
  const mergedRef = useMergedRefs(ref, fieldRef);
  const invalid = props.status?.type === "error";

  // No dependency list: the input re-renders with Astryx's own attributes.
  useLayoutEffect(() => {
    const input = fieldRef.current?.querySelector("input");
    if (invalid) input?.setAttribute("aria-invalid", "true");
    else input?.removeAttribute("aria-invalid");
  });

  return <AstryxTypeahead {...props} ref={mergedRef} />;
}

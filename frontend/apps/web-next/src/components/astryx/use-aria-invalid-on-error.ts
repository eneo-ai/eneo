import { useMergedRefs } from "@astryxdesign/core/hooks";
import { useLayoutEffect, useRef, type Ref } from "react";

/**
 * Astryx 0.7.3 paints a Typeahead's or Tokenizer's error status and names its
 * message in aria-describedby, but unlike its TextInput never sets the
 * input's aria-invalid. This sets it after each render; give the returned ref
 * (merged with the caller's) to the field.
 */
export function useAriaInvalidOnError(
  ref: Ref<HTMLInputElement> | undefined,
  status: { type: string } | undefined
) {
  const fieldRef = useRef<HTMLInputElement>(null);
  const mergedRef = useMergedRefs(ref, fieldRef);
  const invalid = status?.type === "error";

  // No dependency list: the input re-renders with Astryx's own attributes.
  useLayoutEffect(() => {
    const input = fieldRef.current;
    if (invalid) input?.setAttribute("aria-invalid", "true");
    else input?.removeAttribute("aria-invalid");
  });

  return mergedRef;
}

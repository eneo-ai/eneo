"use client";

import { useCallback, useState, type ReactNode } from "react";
import { collapseWhitespace } from "./text";

/**
 * The text an autosaved field shows while the server echoes its value back.
 *
 * The API stores texts normalised, so the echo of "Välkommen till " is
 * "Välkommen till". Written into the field being typed in, that eats the
 * space and glues the next word on. The draft keeps what the editor typed
 * while the saved value is only its normalised form, follows the saved value
 * whenever it really changes (another editor, a template, a reload), and
 * settles on the saved form once the field is left.
 */
export function useTextDraft(
  saved: string,
  normalize: (text: string) => string | null = collapseWhitespace
): {
  text: string;
  setText: (text: string) => void;
  onFocus: () => void;
  onBlur: () => void;
} {
  const [text, setText] = useState(saved);
  const [focused, setFocused] = useState(false);
  // A fresh response with the same content is not news: adjusted during
  // render (React's pattern for deriving state from a prop change).
  const [seen, setSeen] = useState(saved);
  if (saved !== seen) {
    setSeen(saved);
    if (!(focused && saved === normalize(text))) setText(saved);
  }

  const onFocus = useCallback(() => setFocused(true), []);
  const onBlur = useCallback(() => {
    setFocused(false);
    setText((current) => (saved !== current && saved === normalize(current) ? saved : current));
  }, [saved, normalize]);

  return { text, setText, onFocus, onBlur };
}

/**
 * Astryx's text input has no focus events of its own; they bubble to this
 * wrapper, which is nothing to assistive technology.
 */
export function DraftWrapper({
  onFocus,
  onBlur,
  className,
  children
}: {
  onFocus: () => void;
  onBlur: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div role="presentation" className={className} onFocus={onFocus} onBlur={onBlur}>
      {children}
    </div>
  );
}

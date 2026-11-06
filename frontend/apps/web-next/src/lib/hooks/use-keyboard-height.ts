import { useEffect } from "react";

/**
 * iOS lays its keyboard over the page: it ignores `interactive-widget`, keeps the layout viewport
 * and pans the page, so what is under a focused field (a composer's send button) stays hidden.
 * While something covers the page this sets `--keyboard-height` on the root to the height left,
 * for the frame to fit it, marks the root `data-keyboard` (the `keyboard:` variant), takes the
 * pan back and brings the focused field into the frame. A pinch zoom shrinks the visual viewport
 * too; that is the reader looking closer, not less room.
 */
export function useKeyboardHeight() {
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const root = document.documentElement;
    const fit = () => {
      // Not `innerHeight`: Safari shrinks that with the keyboard, the root's height it keeps.
      // The root's height is rounded and the viewport's is not: a pixel is no keyboard.
      const covered = viewport.scale === 1 && root.clientHeight - viewport.height > 1;
      root.toggleAttribute("data-keyboard", covered);
      if (!covered) {
        root.style.removeProperty("--keyboard-height");
        return;
      }
      root.style.setProperty("--keyboard-height", `${viewport.height}px`);
      // A dialog lies outside the frame: Safari's pan is what brings its lower fields into view.
      const field = document.activeElement;
      if (field?.closest("dialog")) return;
      window.scrollTo(0, 0);
      field?.scrollIntoView({ block: "nearest" });
    };
    viewport.addEventListener("resize", fit);
    // Safari pans after the keyboard's resize, towards where the field stood before the page fit.
    viewport.addEventListener("scroll", fit);
    return () => {
      viewport.removeEventListener("resize", fit);
      viewport.removeEventListener("scroll", fit);
      root.removeAttribute("data-keyboard");
      root.style.removeProperty("--keyboard-height");
    };
  }, []);
}

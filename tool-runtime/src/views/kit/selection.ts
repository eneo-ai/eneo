/// <reference lib="dom" />
import { useEffect } from "react";

/** How near an edge of the rows the pointer scrolls them, and how far a frame at most. */
const EDGE = 20;
const MAX_STEP = 20;

/**
 * Keeps the host's page still while a selection is dragged in scrolling rows.
 *
 * A browser scrolls such rows itself when the pointer nears their edge, and asks every frame
 * above to bring a point just past that edge into sight. Rows reach the edge of the view, so
 * that point lies outside the frame, and Chrome then scrolls the host's page to the top of
 * the view instead: the conversation jumps under the pointer and the selection with it.
 *
 * So while the reader drags, the rows are no scroller of their own to the browser. They keep
 * their place and the room of their scrollbars, and are scrolled from here when the pointer
 * nears an edge, as the browser would have.
 */
export function useSteadySelection() {
  useEffect(() => {
    let rows: HTMLElement | null = null;
    let pointer = { x: 0, y: 0 };
    let frame = 0;

    const past = (at: number, start: number, end: number) =>
      at < start + EDGE ? at - (start + EDGE) : at > end - EDGE ? at - (end - EDGE) : 0;
    const step = (distance: number) => Math.max(-MAX_STEP, Math.min(MAX_STEP, distance));
    const scroll = () => {
      frame = 0;
      if (!rows) return;
      const box = rows.getBoundingClientRect();
      const dx = past(pointer.x, box.left, box.right);
      const dy = past(pointer.y, box.top, box.bottom);
      if (dx === 0 && dy === 0) return;
      const { scrollLeft, scrollTop } = rows;
      rows.scrollBy(step(dx), step(dy));
      // At the end of the rows there is nothing more to bring; the next move asks again.
      if (rows.scrollLeft === scrollLeft && rows.scrollTop === scrollTop) return;
      frame = requestAnimationFrame(scroll);
    };

    const release = () => {
      if (!rows) return;
      cancelAnimationFrame(frame);
      frame = 0;
      delete rows.dataset.selecting;
      rows.style.paddingRight = "";
      rows.style.paddingBottom = "";
      rows = null;
    };
    const press = (event: PointerEvent) => {
      release();
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      const target = event.target instanceof Element ? event.target : null;
      const found = target?.closest<HTMLElement>(".eneo-rows");
      // A press on the rows themselves is on their scrollbar, or on nothing to select.
      if (!found || found === target) return;
      if (found.scrollHeight <= found.clientHeight && found.scrollWidth <= found.clientWidth)
        return;
      rows = found;
      pointer = { x: event.clientX, y: event.clientY };
      // Scrollbars that take room leave it, so nothing moves under the pointer.
      const across = found.offsetWidth - found.clientWidth;
      const down = found.offsetHeight - found.clientHeight;
      if (across > 0) found.style.paddingRight = `${across}px`;
      if (down > 0) found.style.paddingBottom = `${down}px`;
      found.dataset.selecting = "";
    };
    const move = (event: PointerEvent) => {
      if (!rows) return;
      // A release that was never heard of, as outside the frame.
      if (event.buttons === 0) return release();
      pointer = { x: event.clientX, y: event.clientY };
      if (frame === 0) frame = requestAnimationFrame(scroll);
    };

    document.addEventListener("pointerdown", press, true);
    document.addEventListener("pointermove", move, true);
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", release, true);
    window.addEventListener("blur", release);
    return () => {
      release();
      document.removeEventListener("pointerdown", press, true);
      document.removeEventListener("pointermove", move, true);
      document.removeEventListener("pointerup", release, true);
      document.removeEventListener("pointercancel", release, true);
      window.removeEventListener("blur", release);
    };
  }, []);
}

/** Follow rendered replies, including tool views that resize after streaming ends. */
export function followConversationScroll(
  container: HTMLElement,
  content: HTMLElement[],
  onAway: (away: boolean) => void
) {
  const threshold = 150;
  let following = true;
  let frame: number | undefined;
  let destroyed = false;
  const bottom = () => Math.max(0, container.scrollHeight - container.clientHeight);
  let lastBottom = bottom();
  let lastTop = container.scrollTop;

  const remember = () => {
    lastBottom = bottom();
    lastTop = container.scrollTop;
    onAway(lastBottom - lastTop > threshold);
  };
  const settle = () => {
    frame = undefined;
    if (destroyed) return;
    // Instant positioning avoids a smooth animation falling behind repeated
    // iframe resize notifications or late streamed content.
    if (following) container.scrollTop = bottom();
    remember();
  };
  const schedule = () => {
    if (!destroyed && frame === undefined) frame = requestAnimationFrame(settle);
  };
  const onScroll = () => {
    const currentBottom = bottom();
    const top = container.scrollTop;
    const layoutChanged = currentBottom !== lastBottom;
    // Growing content can itself emit a scroll event (browser anchoring).
    // That must not turn off following before the resize observer runs.
    // An upward scroll still takes precedence when the content grows.
    if (!layoutChanged || (top < lastTop && currentBottom >= lastBottom)) {
      following = currentBottom - top <= threshold;
    }
    remember();
    if (layoutChanged) schedule();
  };
  const observer = new ResizeObserver(schedule);
  observer.observe(container);
  for (const element of content) observer.observe(element);
  container.addEventListener("scroll", onScroll);
  schedule();

  return {
    toBottom() {
      following = true;
      schedule();
    },
    destroy() {
      destroyed = true;
      observer.disconnect();
      container.removeEventListener("scroll", onScroll);
      if (frame !== undefined) cancelAnimationFrame(frame);
    }
  };
}

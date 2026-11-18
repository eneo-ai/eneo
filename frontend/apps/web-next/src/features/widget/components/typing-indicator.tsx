/** Three pulsing dots while an answer is on its way. Decorative: the chat announces the wait. */
export function TypingIndicator() {
  return (
    <span className="widget-typing" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

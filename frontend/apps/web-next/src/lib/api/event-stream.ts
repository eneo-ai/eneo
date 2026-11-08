/** Read SSE data fields; callers own their endpoint's payload and completion contract. */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onMessage: (data: string) => void
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let complete = false;

  try {
    for (;;) {
      const result = await reader.read();
      if (result.done) {
        complete = true;
        break;
      }
      buffer += decoder.decode(result.value, { stream: true });
      buffer = consumeCompleteEvents(buffer, onMessage);
    }

    buffer += decoder.decode();
    if (buffer.trim().length > 0) onMessage(parseEventData(buffer));
  } finally {
    // A parser/consumer failure must close the response, not just unlock a live reader.
    if (!complete) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function consumeCompleteEvents(buffer: string, onMessage: (data: string) => void): string {
  let rest = buffer;

  for (;;) {
    const boundary = findEventBoundary(rest);
    if (!boundary) return rest;

    const event = rest.slice(0, boundary.index);
    onMessage(parseEventData(event));
    rest = rest.slice(boundary.index + boundary.length);
  }
}

function findEventBoundary(buffer: string): { index: number; length: number } | null {
  const boundaries = [
    { index: buffer.indexOf("\r\n\r\n"), length: 4 },
    { index: buffer.indexOf("\n\n"), length: 2 },
    { index: buffer.indexOf("\r\r"), length: 2 }
  ].filter((candidate) => candidate.index >= 0);

  if (boundaries.length === 0) return null;
  return boundaries.reduce((first, candidate) =>
    candidate.index < first.index ? candidate : first
  );
}

function parseEventData(event: string): string {
  return event
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).replace(/^ /, ""))
    .join("\n");
}

// The promise's value, or `fallback` if it has not settled within `ms`. The timer is
// cleared either way, so a prompt answer leaves nothing pending.
export async function withinTime<T, F>(
  promise: Promise<T>,
  ms: number,
  fallback: F
): Promise<T | F> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<F>((resolve) => (timer = setTimeout(() => resolve(fallback), ms)))
    ]);
  } finally {
    clearTimeout(timer);
  }
}

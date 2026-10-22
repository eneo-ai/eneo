// A recording's length: the clock it is measured on and how it is said.

// Recorded time is measured on a monotonic clock: a system clock set back or
// forward during a meeting must not change how long the recording is.
export const monotonicNow = (): number => performance.now();

// "5 h", "4 h 30 min" or "45 min": a recording limit as the dialog says it.
export function formatRecordingLength(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  const hours = Math.floor(minutes / 60);
  if (hours === 0) return `${minutes} min`;
  return minutes % 60 === 0 ? `${hours} h` : `${hours} h ${minutes % 60} min`;
}

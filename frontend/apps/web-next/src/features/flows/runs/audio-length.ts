/** How long the browser waits for an audio file's length before leaving the check to the server. */
const MEASURE_TIMEOUT_MS = 5_000;

/**
 * An audio file's length in seconds as the browser reads it from the file's
 * own metadata, or null when it cannot tell (a format it does not play, a
 * file without a stated length, or no answer in time). Nothing is played.
 */
export function measureAudioSeconds(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = document.createElement("audio");
    let settled = false;
    const done = (seconds: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      audio.removeAttribute("src");
      URL.revokeObjectURL(url);
      resolve(seconds);
    };
    const timer = setTimeout(() => done(null), MEASURE_TIMEOUT_MS);
    audio.preload = "metadata";
    audio.onloadedmetadata = () =>
      done(Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : null);
    audio.onerror = () => done(null);
    audio.src = url;
  });
}

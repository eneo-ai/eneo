import type { RunCreateRequest, RuntimeInput } from "./runs-api";

/**
 * Pure rules for the start dialog's extras: the run's own name, and the
 * audio check against the length one file of an input can hold.
 */

/** The most characters a run's name may have, as the core counts them (code points). */
export const RUN_LABEL_MAX_LENGTH = 120;

/**
 * The name as the core takes it: one line (line breaks and control
 * characters become spaces) of at most `RUN_LABEL_MAX_LENGTH` characters.
 * `cut` says whether characters past the limit were left out.
 */
export function fitRunLabel(text: string): { label: string; cut: boolean } {
  const oneLine = text.replace(/[\p{Cc}\u2028\u2029]+/gu, " ");
  const characters = Array.from(oneLine);
  if (characters.length <= RUN_LABEL_MAX_LENGTH) return { label: oneLine, cut: false };
  return { label: characters.slice(0, RUN_LABEL_MAX_LENGTH).join(""), cut: true };
}

/** The start request with the run's name, trimmed; a blank name is left out. */
export function withRunLabel(body: RunCreateRequest, label: string): RunCreateRequest {
  const trimmed = label.trim();
  return trimmed ? { ...body, run_label: trimmed } : body;
}

/** An audio file longer than one file of the input can hold, by its measured length. */
export type OverLongAudio = { name: string; seconds: number; maxSeconds: number };

/**
 * Splits picked files into those to upload and audio files the input could
 * not transcribe because they run longer than `max_duration_seconds`. A file
 * whose length the browser cannot read goes on to the server, which checks
 * it too; only a length the browser measured refuses a file here.
 */
export async function screenAudioFiles(
  input: Pick<RuntimeInput, "input_format" | "max_duration_seconds">,
  files: readonly File[],
  measure: (file: File) => Promise<number | null>
): Promise<{ accepted: File[]; refused: OverLongAudio[] }> {
  const maxSeconds = input.max_duration_seconds;
  if (input.input_format !== "audio" || maxSeconds == null) {
    return { accepted: [...files], refused: [] };
  }
  const lengths = await Promise.all(files.map((file) => measure(file)));
  const accepted: File[] = [];
  const refused: OverLongAudio[] = [];
  files.forEach((file, index) => {
    const seconds = lengths[index];
    if (seconds != null && Math.floor(seconds) > maxSeconds) {
      refused.push({ name: file.name, seconds, maxSeconds });
    } else {
      accepted.push(file);
    }
  });
  return { accepted, refused };
}

import type { ShownSegment } from "./transcript";

/**
 * The reviewed transcript as plain text, as the reader sees it: corrected
 * text, reassigned speakers and their names, one line per speaker part with
 * its time span; a speaker still marked unsure says so in words. A
 * recording in several files gets a heading per file. Pure.
 */

export type ExportWords = {
  /** "Del 2": the heading of a recording's second file. */
  part: (number: number) => string;
  unknownSpeaker: string;
  unsureSpeaker: string;
};

/** `01:02:05`: seconds as the export writes them. */
export function exportClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(Math.floor(whole / 3600))}:${pad(Math.floor((whole % 3600) / 60))}:${pad(whole % 60)}`;
}

export function transcriptText(shown: readonly ShownSegment[], words: ExportWords): string {
  const multiFile = new Set(shown.map((segment) => segment.fileIndex)).size > 1;
  const out: string[] = [];
  let file = -1;
  for (const segment of shown) {
    if (multiFile && segment.fileIndex !== file) {
      if (out.length > 0) out.push("");
      out.push(`## ${words.part(segment.fileIndex + 1)}`, "");
      file = segment.fileIndex;
    }
    const time = `[${exportClock(segment.start)} - ${exportClock(segment.end)}]`;
    for (const part of segment.parts) {
      const text = part.text.trim();
      if (!text) continue;
      const name = part.name ?? part.speaker ?? words.unknownSpeaker;
      const unsure =
        part.decision === "unresolved" || (segment.parts.length === 1 && segment.unsure);
      out.push(`${time} ${unsure ? `${name} (${words.unsureSpeaker})` : name}: ${text}`);
    }
  }
  return `${out.join("\n")}\n`;
}

/** Hands the text to the person as a file. */
export function saveText(text: string, fileName: string, type = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

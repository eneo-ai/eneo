// Copyright (c) 2026 Sundsvalls Kommun

/** "Primär indata vid körning: Dokument." → "Dokument".
 *
 *  The server states the input and the result as sentences. Beside a list of
 *  short decisions they read as boilerplate, so the recap keeps the thing that
 *  is named and drops the sentence around it.
 */
export function summaryTerm(sentence: string | null | undefined): string {
  const text = (sentence ?? "").trim();
  const named = text.includes(":") ? text.slice(text.indexOf(":") + 1) : text;
  return named.trim().replace(/[.\s]+$/, "");
}

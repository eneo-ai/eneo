const CANDIDATE_DELIMITERS = [",", ";", "\t"] as const;

/**
 * The delimiter of a CSV file, read from its first record: the candidate that
 * separates the most fields outside quotes. Spreadsheets in Swedish locales
 * export semicolons, so the comma cannot be assumed.
 */
export function sniffDelimiter(text: string): string {
  const counts = new Map<string, number>(CANDIDATE_DELIMITERS.map((d) => [d, 0]));
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') quoted = !quoted;
    else if (!quoted && (char === "\n" || char === "\r")) break;
    else if (!quoted && counts.has(char)) counts.set(char, counts.get(char)! + 1);
  }
  let best: string = ",";
  for (const delimiter of CANDIDATE_DELIMITERS) {
    if (counts.get(delimiter)! > counts.get(best)!) best = delimiter;
  }
  return best;
}

/**
 * Parses delimiter-separated text (RFC 4180 quoting: quoted fields may hold the
 * delimiter, line breaks and doubled quotes). Blank lines are skipped.
 */
export function parseDelimited(text: string, delimiter = sniffDelimiter(text)): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  // A field that opened with a quote stays a field even when empty ("").
  let wasQuoted = false;

  const endRow = () => {
    if (row.length > 0 || field !== "" || wasQuoted) {
      row.push(field);
      rows.push(row);
    }
    row = [];
    field = "";
    wasQuoted = false;
  };

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char !== '"') field += char;
      else if (text[i + 1] === '"') {
        field += '"';
        i++;
      } else quoted = false;
    } else if (char === '"' && field === "") {
      quoted = true;
      wasQuoted = true;
    } else if (char === delimiter) {
      row.push(field);
      field = "";
      wasQuoted = false;
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      endRow();
    } else field += char;
  }
  endRow();
  return rows;
}

type FencedCodeBlock = {
  start: number;
  raw: string;
  lang: string;
  body: string;
};

type SourceLine = {
  start: number;
  end: number;
  text: string;
};

function sourceLines(text: string): SourceLine[] {
  const lines: SourceLine[] = [];
  let start = 0;

  while (start < text.length) {
    const nextBreak = text.indexOf("\n", start);
    const end = nextBreak === -1 ? text.length : nextBreak + 1;
    lines.push({ start, end, text: text.slice(start, end) });
    start = end;
  }

  if (text.length === 0) lines.push({ start: 0, end: 0, text: "" });
  return lines;
}

function lineWithoutBreak(line: string): string {
  return line.replace(/\r?\n$/, "");
}

function openerLang(line: string): string | null {
  const match = /^```([A-Za-z0-9_-]*)\s*$/.exec(lineWithoutBreak(line).trimEnd());
  return match ? (match[1] ?? "") : null;
}

function isClosingFence(line: string): boolean {
  return lineWithoutBreak(line).trimEnd() === "```";
}

function stripOneTrailingLineBreak(text: string): string {
  if (text.endsWith("\r\n")) return text.slice(0, -2);
  if (text.endsWith("\n")) return text.slice(0, -1);
  return text;
}

export function findFencedCodeBlocks(text: string): FencedCodeBlock[] {
  const lines = sourceLines(text);
  const blocks: FencedCodeBlock[] = [];

  for (let i = 0; i < lines.length; i++) {
    const lang = openerLang(lines[i]?.text ?? "");
    if (lang === null) continue;

    for (let j = i + 1; j < lines.length; j++) {
      if (!isClosingFence(lines[j]?.text ?? "")) continue;

      const opener = lines[i];
      const closer = lines[j];
      if (!opener || !closer) break;

      const body = stripOneTrailingLineBreak(text.slice(opener.end, closer.start));
      blocks.push({
        start: opener.start,
        raw: text.slice(opener.start, closer.end),
        lang,
        body
      });
      i = j;
      break;
    }
  }

  return blocks;
}

export function findUnclosedFenceOpener(text: string, lang: string): number | null {
  const lines = sourceLines(text);

  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line || openerLang(line.text) !== lang) continue;

    for (let j = i + 1; j < lines.length; j++) {
      if (isClosingFence(lines[j]?.text ?? "")) return null;
    }
    return line.start;
  }

  return null;
}

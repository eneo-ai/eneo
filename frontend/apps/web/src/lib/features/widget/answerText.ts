import { marked, type Token, type Tokens } from "marked";

// With the space before it, so "9–17 <inref/>." reads "9–17."
const INREF = /\s*<inref\s+id="[^"]+"(?:\s*\/?>|\s*><\/inref>)/g;

/**
 * An answer as a screen reader should hear it: the words without Markdown
 * syntax, citation markers or raw HTML, one line per block. Ordered lists
 * keep their numbers and table cells are read row by row.
 */
export function answerText(markdown: string): string {
  const tokens = marked.lexer(markdown.replace(INREF, ""), { gfm: true });
  return blocks(tokens)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

function blocks(tokens: Token[]): string {
  return tokens.map(block).join("\n");
}

function block(token: Token): string {
  switch (token.type) {
    case "list": {
      const list = token as Tokens.List;
      const start = typeof list.start === "number" ? list.start : 1;
      return list.items
        .map((item, index) => (list.ordered ? `${start + index}. ` : "") + blocks(item.tokens))
        .join("\n");
    }
    case "blockquote":
      return blocks((token as Tokens.Blockquote).tokens);
    case "code":
      return (token as Tokens.Code).text;
    case "table": {
      const table = token as Tokens.Table;
      const row = (cells: Tokens.TableCell[]) =>
        cells.map((cell) => inline(cell.tokens)).join(", ");
      return [row(table.header), ...table.rows.map(row)].join("\n");
    }
    case "html":
    case "space":
    case "hr":
    case "def":
      return "";
    default:
      // Headings, paragraphs and the text of tight list items.
      return inline([token]);
  }
}

function inline(tokens: Token[]): string {
  return tokens
    .map((token) => {
      switch (token.type) {
        case "html":
          return "";
        case "br":
          return "\n";
        default:
          if ("tokens" in token && token.tokens?.length) return inline(token.tokens);
          return "text" in token && typeof token.text === "string" ? token.text : "";
      }
    })
    .join("");
}

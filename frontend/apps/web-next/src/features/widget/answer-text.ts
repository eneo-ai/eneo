import type { Root, RootContent, PhrasingContent, TableCell } from "mdast";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";

// With the space before it, so "9–17 <inref/>." reads "9–17."
const INREF = /\s*<inref\s+id="[^"]+"(?:\s*\/?>|\s*><\/inref>)/g;

const parser = unified().use(remarkParse).use(remarkGfm);

/**
 * An answer as a screen reader should hear it: the words without Markdown
 * syntax, citation markers or raw HTML, one line per block. Ordered lists
 * keep their numbers and table cells are read row by row.
 */
export function answerText(markdown: string): string {
  const tree = parser.parse(markdown.replace(INREF, "")) as Root;
  return blocks(tree.children)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

function blocks(nodes: RootContent[]): string {
  return nodes.map(block).join("\n");
}

function block(node: RootContent): string {
  switch (node.type) {
    case "list": {
      const start = typeof node.start === "number" ? node.start : 1;
      return node.children
        .map((item, index) => (node.ordered ? `${start + index}. ` : "") + blocks(item.children))
        .join("\n");
    }
    case "blockquote":
      return blocks(node.children);
    case "code":
      return node.value;
    case "table": {
      const row = (cells: TableCell[]) => cells.map((cell) => inline(cell.children)).join(", ");
      return node.children.map((tableRow) => row(tableRow.children)).join("\n");
    }
    case "html":
    case "thematicBreak":
    case "definition":
    case "footnoteDefinition":
    case "yaml":
      return "";
    default:
      return "children" in node ? inline(node.children as PhrasingContent[]) : "";
  }
}

function inline(nodes: PhrasingContent[]): string {
  return nodes
    .map((node) => {
      switch (node.type) {
        case "html":
          return "";
        case "break":
          return "\n";
        case "inlineCode":
        case "text":
          return node.value;
        case "image":
        case "imageReference":
          // An image is its description, as a screen reader reads it.
          return node.alt ?? "";
        default:
          return "children" in node ? inline(node.children as PhrasingContent[]) : "";
      }
    })
    .join("");
}

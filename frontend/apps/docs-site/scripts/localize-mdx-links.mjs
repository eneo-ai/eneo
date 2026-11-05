// Markdown links use the MDX `a` override. Explicit JSX links need the same
// adapter, including cards in historical content selected from release refs.
export default function localizeMdxLinks() {
  return function visit(node) {
    if (
      node.type === "mdxJsxFlowElement" ||
      node.type === "mdxJsxTextElement"
    ) {
      if (node.name === "a") node.name = "DocsLink";
      if (node.name === "Cards.Card") node.name = "DocsCard";
    }
    for (const child of node.children || []) visit(child);
  };
}
